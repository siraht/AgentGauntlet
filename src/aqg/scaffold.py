"""One-command repository onboarding and stack-specific toolchain generation."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from .constants import DEFAULT_EXCLUDES, __version__
from .detect import Detection, detect_project
from .errors import ConfigurationError, InfrastructureError
from .policy import render_policy
from .project import load_project
from .util import (
    atomic_write,
    command_exists,
    detect_base_ref,
    merge_gitignore,
    read_json,
    run_command,
    utc_now,
    write_json,
)

PACKAGE_ROOT = Path(__file__).resolve().parent
PACKAGE_RESOURCES = resources.files(__package__.split(".", 1)[0])
_MAX_TOOLCHAIN_PYTHON = "3.13"
_UV_BOOTSTRAP_VERSION = "0.11.32"
_PROJECT_COMMAND = '''#!/usr/bin/env python3
"""Project-local Agent Quality Gauntlet command. Managed by `aqg upgrade`."""
from pathlib import Path
import os
import sys

launcher = Path(__file__).resolve().parent / "quality" / "qg.py"
os.execv(sys.executable, [sys.executable, str(launcher), *sys.argv[1:]])
'''


def _resource(relative: str) -> Traversable:
    current = PACKAGE_RESOURCES
    for part in Path(relative).parts:
        current = current.joinpath(part)
    return current


def _copy_text(template: str, destination: Path, *, force: bool = False) -> bool:
    if destination.exists() and not force:
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(_resource(f"templates/{template}").read_bytes())
    return True


def _copy_resource_tree(source: Any, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.name in {"__pycache__", ".DS_Store"} or item.name.endswith(".pyc"):
            continue
        target = destination / item.name
        if item.is_dir():
            _copy_resource_tree(item, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.read_bytes())


def _copy_runtime(root: Path) -> None:
    destination = root / "quality" / "_aqg"
    if destination.exists():
        shutil.rmtree(destination)
    source_checkout = root / "src" / "aqg"
    is_source_checkout = (
        PACKAGE_ROOT.is_dir()
        and source_checkout.exists()
        and source_checkout.resolve() == PACKAGE_ROOT.resolve()
    )
    if is_source_checkout:
        wrapper = '''#!/usr/bin/env python3
"""Agent Quality Gauntlet source-checkout launcher."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from aqg.cli import main
raise SystemExit(main())
'''
    else:
        _copy_resource_tree(PACKAGE_RESOURCES, destination)
        wrapper = '''#!/usr/bin/env python3
"""Project-local Agent Quality Gauntlet runtime. Managed by `qg upgrade`."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _aqg.cli import main
raise SystemExit(main())
'''
    atomic_write(root / "quality" / "qg.py", wrapper, mode=0o755)
    if not is_source_checkout:
        atomic_write(root / "aqg", _PROJECT_COMMAND, mode=0o755)


def _parse_command(value: str | None) -> list[str] | None:
    return shlex.split(value) if value and value.strip() else None


def _infer_web(
    detection: Detection, root: Path, start_override: str | None, base_url: str | None
) -> dict[str, Any]:
    start = _parse_command(start_override) or detection.start_command
    url = base_url
    frameworks = set(detection.frameworks)
    if start is None and detection.html:
        directory = "."
        for candidate in ("dist", "public", "static", "site", "."):
            if any((root / candidate).glob("*.html")):
                directory = candidate
                break
        start = [
            sys.executable,
            "-m",
            "http.server",
            "4173",
            "--bind",
            "127.0.0.1",
            "--directory",
            directory,
        ]
        url = url or "http://127.0.0.1:4173"
    if url is None:
        if "vite" in frameworks:
            url = "http://127.0.0.1:5173"
        elif "astro" in frameworks:
            url = "http://127.0.0.1:4321"
        else:
            url = "http://127.0.0.1:3000"
    return {"base_url": url, "start_command": start}


def _feature_files_exist(root: Path) -> bool:
    return any((root / "features").glob("*.feature")) if (root / "features").exists() else False


def _acceptance_files_exist(root: Path) -> bool:
    patterns = ["**/e2e/**/*", "**/acceptance/**/*", "**/*acceptance*.py", "**/*e2e*.py"]
    ignored_roots = {"quality", ".aqg", "node_modules", ".venv", "venv", "dist", "build"}
    for pattern in patterns:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if rel.parts and rel.parts[0] in ignored_roots:
                continue
            return True
    return False


def _golden_configured(root: Path) -> bool:
    return (root / "quality" / "golden" / "scenarios.json").exists()


def _gate(applicable: bool, reason: str, **extra: Any) -> dict[str, Any]:
    return {"applicable": applicable, "reason": reason, **extra}


def _js_exec_command(manager: str | None, executable: str, *arguments: str) -> list[str]:
    """Build a non-shell package-manager command that works on every supported OS."""
    if manager == "pnpm":
        return ["pnpm", "exec", executable, *arguments]
    if manager == "yarn":
        return ["yarn", "exec", executable, *arguments]
    if manager == "bun":
        return ["bun", "x", executable, *arguments]
    return ["npm", "exec", "--", executable, *arguments]


def _javascript_unit_command(detection: Detection) -> list[str]:
    manager = detection.package_manager or "npm"
    runner = detection.js_test_runner or "vitest"
    targets = detection.test_files or detection.test_paths
    if "test" in detection.package_scripts:
        return [manager, "run", "test"] if manager in {"npm", "bun"} else [manager, "test"]
    if runner == "vitest":
        return [
            "$AQG_JS_BIN/vitest",
            "run",
            "--config",
            "quality/tools/js/config/vitest.config.mjs",
        ]
    if runner == "node":
        return ["node", "--test", *targets]
    if runner == "jest":
        return _js_exec_command(manager, "jest", "--runTestsByPath", *targets)
    return _js_exec_command(manager, runner, *targets)


def _javascript_evidence_commands(detection: Detection) -> tuple[list[str], list[str]]:
    manager = detection.package_manager or "npm"
    runner = detection.js_test_runner or "vitest"
    targets = detection.test_files or detection.test_paths
    coverage_root = ".aqg/work/coverage/js"
    if runner == "vitest":
        collect = [
            "$AQG_JS_BIN/vitest",
            "list",
            "--config",
            "quality/tools/js/config/vitest.config.mjs",
        ]
        coverage = [
            "$AQG_JS_BIN/vitest",
            "run",
            "--coverage",
            "--config",
            "quality/tools/js/config/vitest.config.mjs",
        ]
        return collect, coverage
    if runner == "jest":
        collect = _js_exec_command(manager, "jest", "--listTests", "--runTestsByPath", *targets)
        coverage = _js_exec_command(
            manager,
            "jest",
            "--runTestsByPath",
            *targets,
            "--coverage",
            f"--coverageDirectory={coverage_root}",
            "--coverageReporters=json",
            "--coverageReporters=json-summary",
        )
        return collect, coverage
    return _c8_evidence_commands(manager, runner, targets, coverage_root)


def _c8_evidence_commands(
    manager: str, runner: str, targets: list[str], coverage_root: str
) -> tuple[list[str], list[str]]:
    target = ["node", "--test", *targets]
    if runner != "node":
        target = _js_exec_command(manager, runner, *targets)
    collect_args = {
        "mocha": ["--dry-run", "--reporter", "json"],
        "ava": ["--tap"],
        "node": [],
    }.get(runner, [])
    coverage = [
        "$AQG_JS_BIN/c8",
        f"--reports-dir={coverage_root}",
        "--reporter=json",
        "--reporter=json-summary",
        *target,
    ]
    return [*target, *collect_args], coverage


def _javascript_commands(detection: Detection) -> dict[str, list[str] | None]:
    if not detection.javascript:
        return {"unit": None, "collect": None, "coverage": None}
    collect, coverage = _javascript_evidence_commands(detection)
    return {
        "unit": _javascript_unit_command(detection),
        "collect": collect,
        "coverage": coverage,
    }


def _python_commands(detection: Detection) -> dict[str, list[str] | None]:
    if not detection.python:
        return {"unit": None, "collect": None}
    if detection.python_test_runner == "tox":
        return {
            "unit": ["$AQG_PY_BIN/tox", "run"],
            "collect": ["$AQG_PY_BIN/tox", "run", "--", "--collect-only", "-q"],
        }
    return {"unit": None, "collect": None}


def _default_thresholds() -> dict[str, Any]:
    return {
        "coverage": {
            "lines": 85,
            "branches": 75,
            "functions": 80,
            "statements": 85,
            "changed_lines": 90,
            "allow_missing": False,
        },
        "structure": {
            "max_function_lines": 50,
            "max_cyclomatic_complexity": 10,
            "max_crap": 15,
            "max_nesting_depth": 4,
        },
        "mutation": {
            "minimum_score": 70,
            "maximum_survivors": 0,
            "minimum_selection_coverage": 80,
            "changed_only": True,
        },
        "security": {"audit_level": "high", "allow_unreviewed_ignores": False},
        "performance": {
            "lighthouse_performance": 0.8,
            "lighthouse_accessibility": 0.95,
            "sample_count": 3,
            "warmup_runs": 1,
            "max_score_spread": 0.1,
        },
    }


def _assurance_thresholds() -> dict[str, Any]:
    return {
        "fast": {},
        "pr": {},
        "deep": {
            "coverage": {
                "lines": 90,
                "branches": 85,
                "functions": 90,
                "statements": 90,
                "changed_lines": 95,
            },
            "structure": {
                "max_function_lines": 40,
                "max_cyclomatic_complexity": 8,
                "max_crap": 8,
                "max_nesting_depth": 4,
            },
            "mutation": {
                "minimum_score": 85,
                "maximum_survivors": 0,
                "minimum_selection_coverage": 90,
            },
            "performance": {"lighthouse_performance": 0.9, "lighthouse_accessibility": 0.98},
        },
        "release": {
            "coverage": {
                "lines": 95,
                "branches": 90,
                "functions": 95,
                "statements": 95,
                "changed_lines": 95,
            },
            "structure": {
                "max_function_lines": 30,
                "max_cyclomatic_complexity": 5,
                "max_crap": 5,
                "max_nesting_depth": 3,
            },
            "mutation": {
                "minimum_score": 90,
                "maximum_survivors": 0,
                "minimum_selection_coverage": 95,
            },
            "performance": {"lighthouse_performance": 0.95, "lighthouse_accessibility": 0.99},
        },
    }


def _core_gates(detection: Detection, has_code: bool) -> dict[str, dict[str, Any]]:
    source_reason = "No supported source files were detected."
    code_reason = "No JavaScript/TypeScript/Python production source was detected."
    return {
        "format": _gate(has_code or detection.html or detection.css, source_reason),
        "lint": _gate(has_code or detection.html or detection.css, source_reason),
        "typecheck": _gate(
            detection.typescript or detection.python, "No TypeScript or Python source was detected."
        ),
        "test_integrity": _gate(has_code, code_reason),
        "unit": _gate(has_code, code_reason),
        "structure": _gate(has_code, code_reason),
        "coverage": _gate(has_code, "No coverable production source was detected."),
        "mutation_changed": _gate(has_code, "No mutable production source was detected."),
        "review": _gate(True, "Review analysis is always applicable."),
        "secrets": _gate(True, "Secret scanning is always applicable."),
        "security_fast": _gate(
            has_code, "No supported dependency or source ecosystem was detected."
        ),
        "security_deep": _gate(
            has_code, "No supported dependency or source ecosystem was detected."
        ),
    }


def _extended_gates(
    root: Path,
    detection: Detection,
    *,
    has_acceptance: bool,
    has_contracts: bool,
    has_web: bool,
    web: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return {
        "contracts": _gate(
            has_contracts,
            "No contract-test directory was detected; add tests/contracts or mark a project command.",
        ),
        "acceptance": _gate(
            has_acceptance,
            "No web surface, Gherkin feature, or acceptance-test directory was detected.",
        ),
        "golden": _gate(
            _golden_configured(root), "No quality/golden/scenarios.json is configured."
        ),
        "mutation_acceptance": _gate(
            _feature_files_exist(root),
            "No Gherkin Examples-based acceptance specifications were detected.",
        ),
        "supply_chain": _gate(
            detection.javascript or detection.python,
            "No supported JavaScript or Python dependency ecosystem was detected.",
        ),
        "performance": _gate(
            bool(has_web and web.get("start_command")), "No runnable web surface was detected."
        ),
        "reproducible_build": _gate(
            bool(detection.build_command), "No deterministic build command was detected."
        ),
        "release_readiness": _gate(True, "Release evidence is always applicable."),
    }


def _stack_settings(
    detection: Detection,
    js_commands: dict[str, list[str] | None],
    python_commands: dict[str, list[str] | None],
) -> dict[str, Any]:
    python_sources = [
        path for path in detection.source_paths if path not in {"tests", "test", "."}
    ] or ["."]
    return {
        "javascript": {
            "package_manager": detection.package_manager,
            "test_runner": detection.js_test_runner or ("vitest" if detection.javascript else None),
            "unit_command": js_commands["unit"],
            "collect_command": js_commands["collect"],
            "coverage_command": js_commands["coverage"],
            "build_command": detection.build_command,
        },
        "python": {
            "manager": detection.python_manager,
            "test_runner": detection.python_test_runner,
            "source_paths": python_sources,
            "test_paths": detection.test_paths or ["tests", "test"],
            "pytest_args": ["--strict-config", "--strict-markers", "-ra"],
            "mutation_timeout_multiplier": 5.0,
            "mutation_timeout_constant": 1.0,
            "mutation_max_changed_lines": 250,
            "unit_command": python_commands["unit"],
            "collect_command": python_commands["collect"],
        },
    }


def _has_web_surface(detection: Detection) -> bool:
    web_frameworks = {"react", "vue", "svelte", "sveltekit", "next", "nuxt", "astro", "vite"}
    return (
        detection.html or detection.css or bool(web_frameworks.intersection(detection.frameworks))
    )


def _project_identity(detection: Detection) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "name": detection.name,
        "generated_by": f"agent-quality-gauntlet/{__version__}",
        "stacks": {
            "javascript": detection.javascript,
            "typescript": detection.typescript,
            "python": detection.python,
            "html": detection.html,
            "css": detection.css,
        },
        "frameworks": detection.frameworks,
    }


def _project_paths(detection: Detection) -> dict[str, list[str]]:
    return {
        "source": detection.source_paths,
        "tests": detection.test_paths,
        "html": detection.html_paths,
        "css": detection.css_paths,
        "exclude": list(DEFAULT_EXCLUDES),
    }


def _enforcement_settings(root: Path, mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "stage": "shadow" if mode == "adopt" else "strict",
        "scope": "changed" if mode == "adopt" else "full",
        "base_ref": detect_base_ref(root),
        "new_code_must_meet_current_policy": True,
        "existing_debt_must_not_increase": True,
    }


def build_project_config(
    root: Path,
    detection: Detection,
    *,
    base_url: str | None = None,
    start_command: str | None = None,
    mode: str = "adopt",
) -> dict[str, Any]:
    if mode not in {"adopt", "greenfield"}:
        raise ConfigurationError("mode must be adopt or greenfield")
    has_code = detection.javascript or detection.python
    has_web = _has_web_surface(detection)
    web = (
        _infer_web(detection, root, start_command, base_url)
        if has_web
        else {"base_url": None, "start_command": None}
    )
    has_acceptance = has_web or _feature_files_exist(root) or _acceptance_files_exist(root)
    has_contracts = any(
        (root / path).exists() for path in ("tests/contracts", "test/contracts", "contracts")
    )
    js_commands = _javascript_commands(detection)
    python_commands = _python_commands(detection)
    gates = _core_gates(detection, has_code)
    gates.update(
        _extended_gates(
            root,
            detection,
            has_acceptance=has_acceptance,
            has_contracts=has_contracts,
            has_web=has_web,
            web=web,
        )
    )
    stack_settings = _stack_settings(detection, js_commands, python_commands)
    return {
        **_project_identity(detection),
        "paths": _project_paths(detection),
        **stack_settings,
        "web": web,
        "enforcement": _enforcement_settings(root, mode),
        "thresholds": _default_thresholds(),
        "profile_thresholds": _assurance_thresholds(),
        "assurance": None,
        "gates": gates,
        "notes": detection.notes,
    }


def _render_agents_addendum() -> str:
    return """\n## Agent Quality Gauntlet\n\nThis repository uses the Agent Quality Gauntlet. Before changing code, read `QUALITY.md`, `KEYSTONE.md`, the applicable files under `feature-spec/`, and `quality/change-risk.json`. Run `python3 quality/qg.py status`, then `python3 quality/qg.py check-risk --keep-going` before declaring completion. Never modify policy-plane files, approve golden changes, suppress a checker, weaken a test, or update mutation baselines unless the user explicitly assigns a policy-maintenance task.\n"""


def _append_once(path: Path, marker: str, content: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if marker in existing:
        return
    atomic_write(path, existing.rstrip() + "\n" + content.lstrip())


def _merge_hooks(path: Path, root_variable: str, matcher: str) -> None:
    payload: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except json.JSONDecodeError:
            backup = path.with_suffix(path.suffix + ".before-aqg")
            shutil.copy2(path, backup)
            payload = {}
    hooks = payload.setdefault("hooks", {})
    command = f'python3 "{root_variable}/quality/qg.py" hook-pretool'
    stop_command = f'python3 "{root_variable}/quality/qg.py" hook-stop'
    pre = hooks.setdefault("PreToolUse", [])
    if not any("hook-pretool" in json.dumps(item) for item in pre):
        pre.append(
            {"matcher": matcher, "hooks": [{"type": "command", "command": command, "timeout": 30}]}
        )
    stop = hooks.setdefault("Stop", [])
    if not any("hook-stop" in json.dumps(item) for item in stop):
        stop.append(
            {"matcher": "", "hooks": [{"type": "command", "command": stop_command, "timeout": 600}]}
        )
    write_json(path, payload)


def _write_agent_integrations(root: Path) -> None:
    _append_once(root / "AGENTS.md", "## Agent Quality Gauntlet", _render_agents_addendum())
    _append_once(root / "CLAUDE.md", "## Agent Quality Gauntlet", _render_agents_addendum())
    _merge_hooks(
        root / ".claude" / "settings.json",
        "$CLAUDE_PROJECT_DIR",
        "Bash|Edit|Write|MultiEdit|NotebookEdit|mcp__.*",
    )
    _merge_hooks(
        root / ".codex" / "hooks.json",
        "$(git rev-parse --show-toplevel)",
        "Bash|Edit|Write|apply_patch|mcp__.*",
    )
    skill = """---\nname: quality-gauntlet\ndescription: Run and interpret the repository's deterministic quality gauntlet, create test and QA evidence, and prepare review packets.\n---\n# Quality Gauntlet\n\n1. Read `QUALITY.md`, `KEYSTONE.md`, applicable `feature-spec/` files, and `quality/change-risk.json`.\n2. Run `python3 quality/qg.py status` before editing.\n3. Keep product behavior and tests aligned; do not weaken policy or approve expected-output changes.\n4. Use `python3 quality/qg.py guidance <topic>` for test-writing instructions.\n5. Run `python3 quality/qg.py check fast` during work and `python3 quality/qg.py check-risk --keep-going` before completion.\n6. Generate the review packet with `python3 quality/qg.py review --write`.\n7. Report every failed, skipped, stale, or inapplicable gate explicitly.\n"""
    atomic_write(root / ".agents" / "skills" / "quality-gauntlet" / "SKILL.md", skill)
    atomic_write(root / ".claude" / "skills" / "quality-gauntlet" / "SKILL.md", skill)
    verifier = """# Quality verifier\n\nAct as an independent, read-only verifier. Do not edit source, tests, snapshots, policies, waivers, baselines, or generated evidence. Inspect the risk card and behavior contracts, run the required AQG profile, examine raw gate evidence and review findings, and report unsupported claims, skipped controls, stale evidence, surviving mutants, unreviewed expected-output changes, and rollback gaps.\n"""
    atomic_write(root / ".claude" / "agents" / "quality-verifier.md", verifier)
    atomic_write(
        root / ".codex" / "agents" / "quality-verifier.toml",
        'name = "quality-verifier"\ndescription = "Independent read-only verification of AQG evidence and behavior contracts"\nmodel = "default"\n',
    )


def _write_ci(
    root: Path, codeowner: str | None = None, project: dict[str, Any] | None = None
) -> None:
    project = project or build_project_config(root, detect_project(root))
    stacks = project.get("stacks", {})
    has_js = bool(stacks.get("javascript") or stacks.get("html") or stacks.get("css"))
    browser_option = (
        " --browsers" if project.get("gates", {}).get("acceptance", {}).get("applicable") else ""
    )
    node_step = (
        """
      - uses: actions/setup-node@820762786026740c76f36085b0efc47a31fe5020 # v7.0.0
        with:
          node-version: '22'
          cache: npm
          cache-dependency-path: quality/tools/js/package-lock.json
"""
        if has_js
        else ""
    )
    workflow = f"""name: Agent Quality Gauntlet

on:
  pull_request:
  push:
  workflow_dispatch:

permissions:
  contents: read
  security-events: write
  id-token: write

concurrency:
  group: aqg-${{{{ github.workflow }}}}-${{{{ github.ref }}}}
  cancel-in-progress: true

jobs:
  quality:
    runs-on: ubuntu-latest
    timeout-minutes: 120
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          ref: ${{{{ github.event.pull_request.head.sha || github.sha }}}}
          fetch-depth: 0
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: '3.12'
{node_step}      - name: Resolve comparison base
        shell: bash
        run: |
          if [[ "${{{{ github.event_name }}}}" == "pull_request" ]]; then
            git fetch --no-tags origin "${{{{ github.base_ref }}}}"
            AQG_BASE="origin/${{{{ github.base_ref }}}}"
          elif [[ "${{{{ github.event_name }}}}" == "workflow_dispatch" ]]; then
            AQG_TARGET="${{{{ github.event.repository.default_branch }}}}"
            if [[ -z "$AQG_TARGET" ]]; then
              echo "Repository default branch is unavailable; refusing manual dispatch." >&2
              exit 2
            fi
            git fetch --no-tags origin "$AQG_TARGET"
            AQG_BASE="origin/$AQG_TARGET"
          else
            AQG_BASE="${{{{ github.event.before }}}}"
            if [[ -z "$AQG_BASE" || "$AQG_BASE" =~ ^0+$ ]] || ! git cat-file -e "$AQG_BASE^{{commit}}" 2>/dev/null; then
              echo "Push comparison base is unavailable; refusing non-authoritative evidence." >&2
              exit 2
            fi
          fi
          git cat-file -e "$AQG_BASE^{{commit}}" 2>/dev/null || {{
            echo "Comparison base does not resolve: $AQG_BASE" >&2
            exit 2
          }}
          echo "AQG_DIFF_BASE=$AQG_BASE" >> "$GITHUB_ENV"
          echo "Comparison base: $AQG_BASE"
      - name: Install locked AQG toolchains
        run: python3 quality/qg.py tools install --ci{browser_option}
      - name: Prove checker failure behavior
        run: python3 quality/qg.py conformance --tools
      - name: Validate policy, project model, and risk card
        run: |
          python3 quality/qg.py doctor --strict-tools
          python3 quality/qg.py risk-card --json
      - name: Run required quality profile
        run: python3 quality/qg.py check-risk --keep-going
      - name: Generate review packet and SARIF
        if: always()
        continue-on-error: true
        run: |
          python3 quality/qg.py review --write --sarif --github-summary "$GITHUB_STEP_SUMMARY"
      - name: Upload AQG SARIF
        if: always() && hashFiles('.aqg/review/review.sarif') != ''
        uses: github/codeql-action/upload-sarif@7211b7c8077ea37d8641b6271f6a365a22a5fbfa # v4.36.0
        with:
          sarif_file: .aqg/review/review.sarif
          category: aqg-review
      - name: Upload quality evidence
        if: always()
        uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        with:
          name: aqg-evidence-${{{{ github.run_id }}}}
          path: |
            .aqg/runs
            .aqg/review
            .aqg/conformance
            .aqg/work
          if-no-files-found: warn
          retention-days: 30
"""
    path = root / ".github" / "workflows" / "quality-gauntlet.yml"
    if not path.exists():
        atomic_write(path, workflow)
    owner = codeowner or "@OWNER"
    if owner != "@OWNER" and not owner.startswith("@"):
        owner = "@" + owner
    codeowners = """# Policy and human-review planes
/quality/ @OWNER
/.github/workflows/ @OWNER
/.github/CODEOWNERS @OWNER
/AGENTS.md @OWNER
/CLAUDE.md @OWNER
/QUALITY.md @OWNER
/KEYSTONE.md @OWNER
/feature-spec/ @OWNER
/features/ @OWNER
/qa/procedures/ @OWNER
/quality/approvals/ @OWNER
""".replace("@OWNER", owner)
    path = root / ".github" / "CODEOWNERS"
    if not path.exists():
        atomic_write(path, codeowners)


def _write_docs(root: Path) -> None:
    quality_doc = """# Quality policy\n\nThis repository uses **Agent Quality Gauntlet 2**. `quality/policy.toml` defines cumulative execution profiles and `quality/project.json` defines stack applicability, commands, paths, and thresholds. Exit 0 means checked and passed; exit 1 means the checker found a quality defect; exit 2 means policy or configuration is invalid; exit 3 means infrastructure failed or trustworthy evidence was not produced.\n\n## Required workflow\n\n1. Update `quality/change-risk.json` in observable product terms.\n2. Read `KEYSTONE.md` and applicable `feature-spec/` documents.\n3. Run `python3 quality/qg.py check fast` during implementation.\n4. Run `python3 quality/qg.py check-risk --keep-going` and `python3 quality/qg.py review --write` before review.\n5. A human reviews behavior contracts, QA procedures, expected-output changes, waivers, surviving mutations, and release controls according to the resolved risk profile.\n\nPolicy-plane files may change only during an explicit policy-maintenance task. A passing local hook is advisory; protected CI and code-owner review are authoritative.\n"""
    if not (root / "QUALITY.md").exists():
        atomic_write(root / "QUALITY.md", quality_doc)
    keystone = """# Keystone agent guidance\n\nThis project keeps durable product intent beside the code. Active specifications under `feature-spec/` describe implemented behavior that must remain true. Files prefixed with `TODO.` describe intended behavior that is not yet active. Before changing behavior, resolve the most specific applicable active specification and its parent requirements. A mismatch between an active specification, tests, and implementation is a defect; do not silently weaken the specification.\n\n## Feature context\n\nReplace this section with the product purpose, users, executable surfaces, shared behavior, and the natural dot-separated feature namespaces.\n"""
    if not (root / "KEYSTONE.md").exists():
        atomic_write(root / "KEYSTONE.md", keystone)
    (root / "feature-spec").mkdir(exist_ok=True)
    (root / "features").mkdir(exist_ok=True)
    (root / "qa" / "procedures").mkdir(parents=True, exist_ok=True)


def _onboarding_state(root: Path, detection: Detection, project: dict[str, Any]) -> dict[str, Any]:
    feature_dir = root / "feature-spec"
    active_specs = (
        sorted(
            path.relative_to(root).as_posix()
            for path in feature_dir.glob("*.md")
            if not path.name.startswith(("README", "EXAMPLE", "TODO."))
        )
        if feature_dir.exists()
        else []
    )
    todo_specs = (
        sorted(path.relative_to(root).as_posix() for path in feature_dir.glob("TODO.*.md"))
        if feature_dir.exists()
        else []
    )
    feature_files = (
        sorted(path.relative_to(root).as_posix() for path in (root / "features").glob("*.feature"))
        if (root / "features").exists()
        else []
    )
    qa_files = (
        sorted(
            path.relative_to(root).as_posix() for path in (root / "qa" / "procedures").glob("*.md")
        )
        if (root / "qa" / "procedures").exists()
        else []
    )
    return {
        "stacks": project.get("stacks", {}),
        "detected_stacks": {
            "javascript": detection.javascript,
            "typescript": detection.typescript,
            "python": detection.python,
            "html": detection.html,
            "css": detection.css,
        },
        "detected_test_paths": detection.test_paths,
        "active_specs": active_specs,
        "todo_specs": todo_specs,
        "gherkin_features": feature_files,
        "qa_procedures": qa_files,
        "contracts_present": any(
            (root / value).exists() for value in ("tests/contracts", "test/contracts", "contracts")
        ),
        "golden_configured": _golden_configured(root),
        "acceptance_present": _acceptance_files_exist(root),
        "keystone_placeholder": (root / "KEYSTONE.md").exists()
        and "Replace this section"
        in (root / "KEYSTONE.md").read_text(encoding="utf-8", errors="replace"),
        "codeowners_placeholder": (root / ".github" / "CODEOWNERS").exists()
        and "@OWNER"
        in (root / ".github" / "CODEOWNERS").read_text(encoding="utf-8", errors="replace"),
        "js_lock": (root / "quality" / "tools" / "js" / "package-lock.json").exists(),
        "python_lock": (root / "quality" / "tools" / "python" / "requirements.lock.txt").exists(),
        "ci_present": (root / ".github" / "workflows" / "quality-gauntlet.yml").exists(),
        "agent_integrations": all(
            (root / value).exists()
            for value in ("AGENTS.md", "CLAUDE.md", ".claude/settings.json", ".codex/hooks.json")
        ),
    }


def _state_fingerprint(state: dict[str, Any]) -> str:
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_onboarding(root: Path, detection: Detection, project: dict[str, Any]) -> dict[str, Any]:
    state = _onboarding_state(root, detection, project)
    gaps: list[dict[str, str]] = []

    configured_stacks = project.get("stacks", {})
    drifted_stacks = [
        name
        for name, enabled in state["detected_stacks"].items()
        if enabled and not configured_stacks.get(name)
    ]
    if drifted_stacks:
        gaps.append(
            {
                "code": "project-model-stack-drift",
                "severity": "blocker",
                "message": f"New supported stacks are present but absent from the protected project model: {', '.join(drifted_stacks)}.",
                "next_step": "During explicit policy maintenance, run `AQG_POLICY_MAINTENANCE=1 python3 quality/qg.py detect --write`, review every applicability and threshold change, then rerun conformance.",
            }
        )
    if (detection.javascript or detection.python) and not detection.test_paths:
        gaps.append(
            {
                "code": "missing-tests",
                "severity": "blocker",
                "message": "Production source exists but no executable unit-test location was detected.",
                "next_step": "Use `qg guidance unit-tests` and add characterization tests before relying on agent-written changes.",
            }
        )
    if state["keystone_placeholder"]:
        gaps.append(
            {
                "code": "product-context-placeholder",
                "severity": "review",
                "message": "KEYSTONE.md still contains generated product-context instructions rather than the actual product boundaries.",
                "next_step": "Define purpose, users, executable surfaces, shared behavior, and natural feature namespaces; have the product owner review the result.",
            }
        )
    if not state["active_specs"]:
        gaps.append(
            {
                "code": "missing-product-contract",
                "severity": "review",
                "message": "No project-specific active feature specification exists yet.",
                "next_step": "Create the smallest durable behavior contract with `qg new spec Product.Feature` and review it before implementation.",
            }
        )
    if project["gates"]["acceptance"]["applicable"] and not state["acceptance_present"]:
        gaps.append(
            {
                "code": "acceptance-bootstrap",
                "severity": "review",
                "message": "A behavioral surface is configured but no project-specific acceptance test was detected.",
                "next_step": "Use `qg new feature Product.Feature`, implement narrow step adapters or Playwright journeys through the real application boundary, and connect each scenario to an active feature specification.",
            }
        )
    if state["gherkin_features"] and not project["gates"]["mutation_acceptance"]["applicable"]:
        gaps.append(
            {
                "code": "acceptance-applicability-drift",
                "severity": "blocker",
                "message": "Gherkin features now exist but acceptance mutation remains marked not applicable in quality/project.json.",
                "next_step": "Refresh the protected project model during policy maintenance, then run `qg acceptance lint` and `qg acceptance mutate`.",
            }
        )
    if state["contracts_present"] and not project["gates"]["contracts"]["applicable"]:
        gaps.append(
            {
                "code": "contract-applicability-drift",
                "severity": "blocker",
                "message": "A contract-test directory now exists but the contracts gate remains not applicable.",
                "next_step": "Refresh quality/project.json during policy maintenance and bind the contracts gate to the real command.",
            }
        )
    if state["golden_configured"] and not project["gates"]["golden"]["applicable"]:
        gaps.append(
            {
                "code": "golden-applicability-drift",
                "severity": "blocker",
                "message": "Golden scenarios are configured but the protected project model still marks the golden gate not applicable.",
                "next_step": "Refresh quality/project.json during policy maintenance, verify normalization rules, and require explicit reviewed updates.",
            }
        )
    if not state["golden_configured"]:
        gaps.append(
            {
                "code": "golden-not-configured",
                "severity": "info",
                "message": "Golden sessions are not enabled because no scenarios.json is configured.",
                "next_step": "Enable them only for complex stable traces; copy quality/golden/scenarios.example.json after reading `qg guidance golden-session-testing`.",
            }
        )
    if not state["contracts_present"]:
        gaps.append(
            {
                "code": "contracts-not-configured",
                "severity": "info",
                "message": "No contract-test directory was detected.",
                "next_step": "Add tests/contracts when the project owns an API, event, file format, database, or third-party boundary.",
            }
        )
    stacks = project.get("stacks", {})
    if (stacks.get("javascript") or stacks.get("html") or stacks.get("css")) and not state[
        "js_lock"
    ]:
        gaps.append(
            {
                "code": "javascript-tools-unlocked",
                "severity": "blocker",
                "message": "The isolated JavaScript/web checker environment has no committed package-lock.json.",
                "next_step": "Run `qg tools install`, commit the exact protected lock, and run tool conformance before trusting JavaScript/web gates.",
            }
        )
    if stacks.get("python") and not state["python_lock"]:
        gaps.append(
            {
                "code": "python-tools-unlocked",
                "severity": "blocker",
                "message": "The isolated Python checker environment has no hash-locked requirements.lock.txt.",
                "next_step": "Run `qg tools install`, commit the hash lock, and run tool conformance before trusting Python gates.",
            }
        )
    if not state["ci_present"]:
        gaps.append(
            {
                "code": "authoritative-ci-missing",
                "severity": "blocker",
                "message": "The repository has no generated authoritative quality workflow.",
                "next_step": "Install and protect .github/workflows/quality-gauntlet.yml, or implement an equivalent clean-CI workflow on the hosting platform.",
            }
        )
    if not state["agent_integrations"]:
        gaps.append(
            {
                "code": "agent-integrations-missing",
                "severity": "review",
                "message": "Codex/Claude working agreements or hooks are incomplete.",
                "next_step": "Run `qg upgrade` during policy maintenance and verify the installed hook schema against the current agent clients.",
            }
        )
    if state["codeowners_placeholder"]:
        gaps.append(
            {
                "code": "codeowners-placeholder",
                "severity": "blocker",
                "message": "CODEOWNERS still contains @OWNER and cannot identify the human authority for policy and behavioral changes.",
                "next_step": "Replace @OWNER with real GitHub users or teams and require their approval in branch protection.",
            }
        )

    severity_rank = {"blocker": 0, "review": 1, "info": 2}
    gaps.sort(key=lambda item: (severity_rank.get(item["severity"], 9), item["code"]))
    stages = [
        {
            "id": "toolchains",
            "title": "Lock checker toolchains",
            "status": "blocked"
            if any(
                g["code"] in {"javascript-tools-unlocked", "python-tools-unlocked"} for g in gaps
            )
            else "complete",
            "command": "python3 quality/qg.py tools install",
        },
        {
            "id": "intent",
            "title": "Define product intent",
            "status": "needs_review"
            if any(
                g["code"] in {"product-context-placeholder", "missing-product-contract"}
                for g in gaps
            )
            else "complete",
            "command": "python3 quality/qg.py new spec Product.Feature",
        },
        {
            "id": "tests",
            "title": "Establish executable tests",
            "status": "blocked" if any(g["code"] == "missing-tests" for g in gaps) else "complete",
            "command": "python3 quality/qg.py guidance test-strategy",
        },
        {
            "id": "acceptance",
            "title": "Connect observable behavior",
            "status": "needs_review"
            if any(
                g["code"] in {"acceptance-bootstrap", "acceptance-applicability-drift"}
                for g in gaps
            )
            else "complete",
            "command": "python3 quality/qg.py new feature Product.Feature",
        },
        {
            "id": "governance",
            "title": "Protect the control plane",
            "status": "blocked"
            if any(
                g["code"] in {"authoritative-ci-missing", "codeowners-placeholder"} for g in gaps
            )
            else "complete",
            "command": "python3 quality/qg.py doctor --strict-tools",
        },
        {
            "id": "proof",
            "title": "Prove the gauntlet",
            "status": "pending",
            "command": "python3 quality/qg.py conformance --tools",
        },
        {
            "id": "first-run",
            "title": "Generate current evidence",
            "status": "pending",
            "command": "python3 quality/qg.py check-risk --keep-going",
        },
        {
            "id": "review",
            "title": "Generate review packet",
            "status": "pending",
            "command": "python3 quality/qg.py review --write",
        },
    ]
    first = next((gap for gap in gaps if gap["severity"] in {"blocker", "review"}), None)
    return {
        "schema_version": 2,
        "generated_at": utc_now(),
        "generated_by": f"agent-quality-gauntlet/{__version__}",
        "mode": project.get("enforcement", {}).get("mode"),
        "state_fingerprint": _state_fingerprint(state),
        "state": state,
        "detected": detection.as_dict(),
        "summary": {
            "blockers": sum(gap["severity"] == "blocker" for gap in gaps),
            "review": sum(gap["severity"] == "review" for gap in gaps),
            "info": sum(gap["severity"] == "info" for gap in gaps),
            "ready_for_guarded_use": not any(gap["severity"] == "blocker" for gap in gaps),
        },
        "gaps": gaps,
        "stages": stages,
        "next_action": first
        or {
            "code": "run-proof",
            "severity": "info",
            "message": "No setup blocker remains.",
            "next_step": "Run conformance, check-risk, and review against the final change.",
        },
        "required_human_input": [
            "Confirm the real product context and active behavior contracts.",
            "Review Gherkin scenarios and QA procedures for critical user journeys.",
            "Assign real code owners and enable protected-branch requirements.",
            "Approve expected-output, dependency, policy, waiver, and release changes at the resolved risk level.",
        ],
        "next_commands": [stage["command"] for stage in stages],
    }


def _project_named_detection(detection: Detection, project: dict[str, Any]) -> Detection:
    payload = detection.as_dict()
    payload["name"] = str(project.get("name") or detection.name)
    return Detection(**payload)


def refresh_onboarding(root: Path) -> dict[str, Any]:
    root = root.resolve()
    project = load_project(root)
    detection = _project_named_detection(detect_project(root), project)
    payload = build_onboarding(root, detection, project)
    write_json(root / "quality" / "onboarding.json", payload)
    return payload


def current_onboarding(root: Path) -> dict[str, Any]:
    payload = read_json(root / "quality" / "onboarding.json", default={})
    project = load_project(root)
    detection = _project_named_detection(detect_project(root), project)
    current = build_onboarding(root, detection, project)
    if not isinstance(payload, dict):
        payload = {}
    return {
        "stored": payload,
        "current": current,
        "stale": payload.get("state_fingerprint") != current.get("state_fingerprint"),
    }


def initialize_project(
    root: Path,
    *,
    owner: str | None = None,
    force: bool = False,
    install: bool = False,
    ci: bool = True,
    base_url: str | None = None,
    start_command: str | None = None,
    mode: str = "auto",
    browsers: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if mode == "auto":
        if (root / ".git").exists():
            history = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            mode = "adopt" if history.returncode == 0 else "greenfield"
        else:
            mode = "greenfield" if not any(root.iterdir()) else "adopt"
    detection = detect_project(root)
    project = build_project_config(
        root, detection, base_url=base_url, start_command=start_command, mode=mode
    )
    quality = root / "quality"
    quality.mkdir(exist_ok=True)
    _copy_runtime(root)
    policy_owner = owner or getpass.getuser()
    atomic_write(quality / "policy.toml", render_policy(policy_owner))
    write_json(quality / "project.json", project)
    _copy_text("common/change-risk.json", quality / "change-risk.json", force=force)
    for directory in ("baselines", "waivers", "conformance", "golden", "approvals", "guidance"):
        (quality / directory).mkdir(parents=True, exist_ok=True)
    _copy_resource_tree(_resource("templates/common/schemas"), quality / "schemas")
    if detection.javascript or detection.html or detection.css:
        for template, destination in (
            ("js/package.json", "quality/tools/js/package.json"),
            ("js/eslint.config.mjs", "quality/tools/js/config/eslint.config.mjs"),
            ("js/stylelint.config.mjs", "quality/tools/js/config/stylelint.config.mjs"),
            ("js/htmlvalidate.json", "quality/tools/js/config/htmlvalidate.json"),
            ("js/vitest.config.mjs", "quality/tools/js/config/vitest.config.mjs"),
            ("js/playwright.config.mjs", "quality/tools/js/config/playwright.config.mjs"),
            ("js/stryker.config.mjs", "quality/tools/js/config/stryker.config.mjs"),
            ("js/tsconfig.aqg.json", "quality/config/js/tsconfig.aqg.json"),
            ("js/lighthouserc.json", "quality/tools/js/config/lighthouserc.json"),
        ):
            _copy_text(template, root / destination, force=True)
        if project["gates"]["acceptance"]["applicable"] and not _acceptance_files_exist(root):
            _copy_text(
                "js/aqg-smoke.spec.mjs",
                root / "tests" / "aqg-browser" / "aqg-smoke.spec.mjs",
                force=False,
            )
    if detection.python:
        for template, destination in (
            ("python/requirements.in", "quality/tools/python/requirements.in"),
            ("python/ruff.toml", "quality/config/python/ruff.toml"),
            ("python/mypy.ini", "quality/config/python/mypy.ini"),
            ("python/pytest.ini", "quality/config/python/pytest.ini"),
            ("python/bandit.yaml", "quality/config/python/bandit.yaml"),
        ):
            _copy_text(template, root / destination, force=True)
    _copy_text(
        "common/golden-scenarios.json", quality / "golden" / "scenarios.example.json", force=False
    )
    _copy_text("common/golden-readme.md", quality / "golden" / "README.md", force=False)
    _copy_text("common/acceptance-adapter.md", quality / "acceptance-adapter.md", force=False)
    if project["gates"]["performance"]["applicable"]:
        _copy_text(
            "web/qa-procedure.md",
            root / "qa" / "procedures" / "web-primary-journey.md",
            force=False,
        )
    _write_docs(root)
    guides_src = _resource("guides")
    if guides_src.is_dir():
        for guide in guides_src.iterdir():
            if not guide.name.endswith(".md"):
                continue
            guide_destination = quality / "guidance" / guide.name
            if force or not guide_destination.exists():
                guide_destination.write_bytes(guide.read_bytes())
    _write_agent_integrations(root)
    if ci:
        _write_ci(root, owner, project)
    merge_gitignore(
        root,
        [
            ".aqg/",
            ".coverage",
            "__pycache__/",
            "*.py[cod]",
            "*.egg-info/",
            ".pytest_cache/",
            ".mypy_cache/",
            ".ruff_cache/",
            ".tox/",
            ".venv/",
            "venv/",
            "node_modules/",
            ".yarn/",
            ".pnp.*",
            "quality/tools/js/node_modules/",
            "quality/tools/python/.venv/",
            "playwright-report/",
            "test-results/",
            "coverage/",
            "htmlcov/",
            "mutants/",
        ],
    )
    result = {
        "root": str(root),
        "detection": detection.as_dict(),
        "project": project,
        "installed": False,
    }
    if install:
        install_toolchains(root, ci=False, browsers=browsers)
        result["installed"] = True
    result["onboarding"] = refresh_onboarding(root)
    return result


def _venv_python(root: Path) -> Path:
    if os.name == "nt":
        return root / ".aqg" / "venv" / "Scripts" / "python.exe"
    return root / ".aqg" / "venv" / "bin" / "python"


def _venv_tool(root: Path, name: str) -> Path:
    if os.name == "nt":
        return root / ".aqg" / "venv" / "Scripts" / f"{name}.exe"
    return root / ".aqg" / "venv" / "bin" / name


def _pin_js_manifest_from_lock(tool_dir: Path) -> bool:
    package_path = tool_dir / "package.json"
    lock_path = tool_dir / "package-lock.json"
    if not package_path.exists() or not lock_path.exists():
        return False
    package = json.loads(package_path.read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    packages = lock.get("packages", {}) if isinstance(lock, dict) else {}
    dependencies = package.get("devDependencies", {})
    changed = False
    for name in list(dependencies):
        entry = packages.get(f"node_modules/{name}", {}) if isinstance(packages, dict) else {}
        version = entry.get("version") if isinstance(entry, dict) else None
        if isinstance(version, str) and version and dependencies[name] != version:
            dependencies[name] = version
            changed = True
    if changed:
        package_path.write_text(
            json.dumps(package, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return changed


def _direct_requirement_markers(path: Path) -> dict[str, str]:
    markers: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-") or ";" not in line:
            continue
        requirement, marker = (part.strip() for part in line.split(";", 1))
        match = re.match(r"^([A-Za-z0-9_.-]+)", requirement)
        if match and marker:
            markers[re.sub(r"[-_.]+", "-", match.group(1)).lower()] = marker
    return markers


def _restore_direct_requirement_markers(requirements_in: Path, requirements_lock: Path) -> None:
    markers = _direct_requirement_markers(requirements_in)
    if not markers:
        return
    output: list[str] = []
    package_line = re.compile(r"^([A-Za-z0-9_.-]+)(.*?)(\s+\\)$")
    for line in requirements_lock.read_text(encoding="utf-8").splitlines():
        match = package_line.match(line)
        name = re.sub(r"[-_.]+", "-", match.group(1)).lower() if match else ""
        marker = markers.get(name)
        if marker and ";" not in line:
            line = f"{line[:-2].rstrip()} ; {marker} \\"
        output.append(line)
    requirements_lock.write_text("\n".join(output) + "\n", encoding="utf-8")


def _pinned_uv_command(root: Path, python: Path) -> str:
    candidates: list[str] = []
    local_uv = _venv_tool(root, "uv")
    if local_uv.exists():
        candidates.append(str(local_uv))
    if command_exists("uv"):
        candidates.append("uv")
    for candidate in candidates:
        version = run_command([candidate, "--version"], cwd=root, timeout=30)
        if version.code == 0 and version.stdout.strip() == f"uv {_UV_BOOTSTRAP_VERSION}":
            return candidate

    ensurepip = run_command(
        [str(python), "-m", "ensurepip", "--upgrade"],
        cwd=root,
        timeout=300,
        stream=True,
    )
    if ensurepip.code != 0:
        raise InfrastructureError(
            "Python's ensurepip failed while bootstrapping the pinned lock resolver"
        )
    bootstrap = run_command(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            f"uv=={_UV_BOOTSTRAP_VERSION}",
        ],
        cwd=root,
        timeout=900,
        stream=True,
    )
    if bootstrap.code != 0 or not local_uv.exists():
        raise InfrastructureError(
            "pinned uv bootstrap failed while creating the protected Python tool lock"
        )
    return str(local_uv)


def _compile_python_lock(
    root: Path, python: Path, requirements_in: Path, requirements_lock: Path
) -> None:
    uv = _pinned_uv_command(root, python)
    command = [
        uv,
        "pip",
        "compile",
        str(requirements_in),
        "--python-version",
        _MAX_TOOLCHAIN_PYTHON,
        "--universal",
        "--generate-hashes",
        "--custom-compile-command",
        "qg tools install (universal Python 3.11-3.13)",
        "--output-file",
        str(requirements_lock),
    ]
    result = run_command(command, cwd=root, timeout=1800, stream=True)
    if result.code != 0 or not requirements_lock.exists():
        raise InfrastructureError(
            "failed to generate quality/tools/python/requirements.lock.txt with hashes"
        )
    _restore_direct_requirement_markers(requirements_in, requirements_lock)


def install_toolchains(root: Path, *, ci: bool = False, browsers: bool = False) -> dict[str, Any]:
    from .project import load_project

    project = load_project(root)
    results: dict[str, Any] = {}
    if (
        project["stacks"].get("javascript")
        or project["stacks"].get("html")
        or project["stacks"].get("css")
    ):
        tool_dir = root / "quality" / "tools" / "js"
        if not command_exists("npm"):
            raise ConfigurationError(
                "Node.js/npm is required for the JavaScript and web adapter pack"
            )
        npm_command = (
            ["npm", "ci", "--ignore-scripts", "--no-audit", "--fund=false"]
            if (tool_dir / "package-lock.json").exists()
            else ["npm", "install", "--ignore-scripts", "--no-audit", "--fund=false"]
        )
        result = run_command(npm_command, cwd=tool_dir, timeout=1800, stream=True)
        if result.code != 0:
            raise InfrastructureError(
                f"JavaScript quality tool installation failed with exit {result.code}"
            )
        if _pin_js_manifest_from_lock(tool_dir):
            relock = run_command(
                [
                    "npm",
                    "install",
                    "--package-lock-only",
                    "--ignore-scripts",
                    "--no-audit",
                    "--fund=false",
                ],
                cwd=tool_dir,
                timeout=900,
                stream=True,
            )
            if relock.code != 0:
                raise InfrastructureError(
                    "failed to rewrite the JavaScript quality lock after exact-version pinning"
                )
        results["javascript_tools"] = "installed_and_exactly_locked"
        root_package = root / "package.json"
        if root_package.exists() and not (root / "node_modules").exists():
            manager = project.get("javascript", {}).get("package_manager") or "npm"
            lock_commands = {
                "npm": ["npm", "ci"]
                if (root / "package-lock.json").exists()
                else ["npm", "install"],
                "pnpm": ["pnpm", "install", "--frozen-lockfile"]
                if (root / "pnpm-lock.yaml").exists()
                else ["pnpm", "install"],
                "yarn": ["yarn", "install", "--immutable"]
                if (root / "yarn.lock").exists()
                else ["yarn", "install"],
                "bun": ["bun", "install", "--frozen-lockfile"]
                if (root / "bun.lock").exists()
                else ["bun", "install"],
            }
            command = lock_commands.get(manager, ["npm", "install"])
            app_result = run_command(command, cwd=root, timeout=1800, stream=True)
            if app_result.code != 0:
                raise InfrastructureError(
                    f"project dependency installation failed with exit {app_result.code}"
                )
            results["project_javascript_dependencies"] = "installed"
        if browsers and project["gates"].get("acceptance", {}).get("applicable"):
            playwright = (
                tool_dir
                / "node_modules"
                / ".bin"
                / ("playwright.cmd" if os.name == "nt" else "playwright")
            )
            browser_command = (
                [str(playwright), "install", "--with-deps", "chromium"]
                if ci
                else [str(playwright), "install", "chromium"]
            )
            browser_result = run_command(browser_command, cwd=root, timeout=1800, stream=True)
            if browser_result.code != 0:
                raise InfrastructureError("Playwright Chromium installation failed")
            results["playwright_chromium"] = "installed"
    if project["stacks"].get("python"):
        venv = root / ".aqg" / "venv"
        venv.parent.mkdir(parents=True, exist_ok=True)
        if not _venv_python(root).exists():
            if command_exists("uv"):
                result = run_command(["uv", "venv", str(venv)], cwd=root, timeout=300, stream=True)
            else:
                result = run_command(
                    [sys.executable, "-m", "venv", str(venv)], cwd=root, timeout=300, stream=True
                )
            if result.code != 0:
                raise InfrastructureError("Python quality virtual environment creation failed")
        python = _venv_python(root)
        requirements_in = root / "quality" / "tools" / "python" / "requirements.in"
        requirements_lock = root / "quality" / "tools" / "python" / "requirements.lock.txt"
        if ci and not requirements_lock.exists():
            raise ConfigurationError(
                "CI requires quality/tools/python/requirements.lock.txt; run `qg tools install` locally and commit it"
            )
        if not requirements_lock.exists():
            _compile_python_lock(root, python, requirements_in, requirements_lock)
        if command_exists("uv"):
            install_result = run_command(
                [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(python),
                    "--require-hashes",
                    "-r",
                    str(requirements_lock),
                ],
                cwd=root,
                timeout=1800,
                stream=True,
            )
        else:
            install_result = run_command(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--require-hashes",
                    "-r",
                    str(requirements_lock),
                ],
                cwd=root,
                timeout=1800,
                stream=True,
            )
        if install_result.code != 0:
            raise InfrastructureError(
                "Python quality tool installation from the protected hash lock failed"
            )
        if (
            (root / "pyproject.toml").exists()
            or (root / "setup.py").exists()
            or (root / "setup.cfg").exists()
        ):
            editable = run_command(
                [str(python), "-m", "pip", "install", "-e", "."],
                cwd=root,
                timeout=1800,
                stream=True,
            )
            if editable.code != 0:
                raise InfrastructureError("editable project installation for tests failed")
        results["python_tools"] = "installed_from_hash_lock"
    return results


def upgrade_runtime(root: Path) -> None:
    _copy_runtime(root)
