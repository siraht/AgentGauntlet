"""JavaScript, TypeScript, HTML, CSS, and Python gate adapters."""

from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from .acceptance import run_acceptance_mutation
from .approvals import validate_required_approvals
from .checks import crap_score, lint_features, scan_secrets, scan_test_integrity
from .constants import (
    CONFIGURATION_ERROR,
    INFRASTRUCTURE_ERROR,
    PASS,
    QUALITY_FAILURE,
    STATUS_NAMES,
)
from .errors import ConfigurationError
from .golden import run_goldens
from .policy import load_policy, risk_summary
from .project import excludes, gate_applicable, load_project, source_paths
from .review import analyze_review, review_exit_code, write_review_packet
from .sbom import generate_sboms
from .util import (
    git_changed_files,
    git_diff,
    iter_files,
    read_json,
    run_command,
    sha256_file,
    utc_now,
    write_json,
)

JS_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}
WEB_SUFFIXES = {".html", ".htm", ".css", ".scss", ".sass", ".less"}
PY_SUFFIXES = {".py", ".pyi"}
CommandSpec = (
    tuple[list[str], int, dict[str, str] | None]
    | tuple[list[str], int, dict[str, str] | None, tuple[int, ...]]
)


def _bin(root: Path, name: str, ecosystem: str) -> Path:
    if ecosystem == "js":
        suffix = ".cmd" if os.name == "nt" else ""
        return root / "quality" / "tools" / "js" / "node_modules" / ".bin" / f"{name}{suffix}"
    suffix = ".exe" if os.name == "nt" else ""
    directory = "Scripts" if os.name == "nt" else "bin"
    return root / ".aqg" / "venv" / directory / f"{name}{suffix}"


def _tool(root: Path, name: str, ecosystem: str) -> str:
    path = _bin(root, name, ecosystem)
    if not path.exists():
        raise ConfigurationError(
            f"missing {name} in the AQG {ecosystem} toolchain; run `python3 quality/qg.py tools install`"
        )
    return str(path)


def _relative_files(
    root: Path, suffixes: set[str], project: dict[str, Any], *, tests: bool | None = None
) -> list[str]:
    files = iter_files(root, suffixes, excludes(project))
    result: list[str] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        is_test = _is_test_path(rel)
        if tests is None or tests == is_test:
            result.append(rel)
    return result


def _base_ref(project: dict[str, Any]) -> str:
    return os.environ.get("AQG_DIFF_BASE") or str(
        project.get("enforcement", {}).get("base_ref", "HEAD")
    )


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = {
        key: value.copy() if isinstance(value, dict) else value for key, value in base.items()
    }
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _effective_thresholds(project: dict[str, Any]) -> dict[str, Any]:
    profile = os.environ.get("AQG_PROFILE", "pr")
    overrides = project.get("profile_thresholds", {}).get(profile, {})
    return _deep_merge(
        project.get("thresholds", {}), overrides if isinstance(overrides, dict) else {}
    )


def _adopt_mode(project: dict[str, Any]) -> bool:
    return str(project.get("enforcement", {}).get("scope", "full")) == "changed"


def _scoped_files(root: Path, project: dict[str, Any], files: list[str]) -> list[str]:
    if not _adopt_mode(project):
        return files
    changed = set(git_changed_files(root, _base_ref(project)))
    return [path for path in files if path in changed]


def _existing_paths(root: Path, values: Iterable[str]) -> list[str]:
    return [str(value) for value in values if (root / str(value)).exists()]


def _changed_production_files(root: Path, project: dict[str, Any], suffixes: set[str]) -> list[str]:
    return [
        path
        for path in git_changed_files(root, _base_ref(project))
        if Path(path).suffix.lower() in suffixes
        and not _is_test_path(path)
        and (root / path).is_file()
    ]


def _is_test_path(path: str) -> bool:
    parts = [part.lower() for part in Path(path).parts]
    name = Path(path).name.lower()
    return (
        any(
            part in {"test", "tests", "spec", "specs", "__tests__", "e2e", "acceptance"}
            for part in parts
        )
        or name.startswith("test_")
        or name.endswith("_test.py")
        or bool(re.search(r"(?:^|[._-])(test|spec)(?:[._-]|$)", name))
    )


def _chunks(values: list[str], size: int = 150) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)] or [[]]


def _run_many(
    root: Path,
    commands: Iterable[CommandSpec],
    *,
    stop_on_failure: bool = False,
) -> tuple[int, list[dict[str, Any]]]:
    final = PASS
    results: list[dict[str, Any]] = []
    for spec in commands:
        command, timeout, env = spec[:3]
        quality_exit_codes = spec[3] if len(spec) == 4 else (1,)
        result = run_command(
            command,
            cwd=root,
            timeout=timeout,
            env=env,
            quality_exit_codes=quality_exit_codes,
        )
        results.append(result.as_dict())
        mapped = {
            STATUS_NAMES[PASS]: PASS,
            STATUS_NAMES[QUALITY_FAILURE]: QUALITY_FAILURE,
            STATUS_NAMES[CONFIGURATION_ERROR]: CONFIGURATION_ERROR,
            STATUS_NAMES[INFRASTRUCTURE_ERROR]: INFRASTRUCTURE_ERROR,
        }.get(result.status, INFRASTRUCTURE_ERROR)
        final = max(final, mapped)
        if stop_on_failure and mapped != PASS:
            break
    return final, results


def _write_report(
    root: Path, gate: str, code: int, details: dict[str, Any]
) -> tuple[int, dict[str, Any]]:
    work = root / ".aqg" / "work" / gate
    work.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": 2,
        "gate": gate,
        "generated_at": utc_now(),
        "status": STATUS_NAMES.get(code, "unknown"),
        "exit_code": code,
        **details,
    }
    write_json(work / "report.json", report)
    return code, report


def _not_applicable(root: Path, gate: str, reason: str) -> tuple[int, dict[str, Any]]:
    return _write_report(
        root, gate, PASS, {"applicability": "not_applicable", "reason": reason, "commands": []}
    )


def _format(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    commands: list[tuple[list[str], int, dict[str, str] | None]] = []
    stacks = project["stacks"]
    scoped: dict[str, list[str]] = {}
    if stacks.get("javascript") or stacks.get("html") or stacks.get("css"):
        files = _scoped_files(
            root,
            project,
            _relative_files(
                root, JS_SUFFIXES | WEB_SUFFIXES | {".json", ".md", ".yaml", ".yml"}, project
            ),
        )
        scoped["prettier"] = files
        if files:
            prettier = _tool(root, "prettier", "js")
            for group in _chunks(files):
                commands.append(([prettier, "--check", "--ignore-unknown", *group], 300, None))
    if stacks.get("python"):
        files = _scoped_files(root, project, _relative_files(root, PY_SUFFIXES, project))
        scoped["python"] = files
        if files:
            ruff = _tool(root, "ruff", "python")
            commands.append(
                (
                    [
                        ruff,
                        "format",
                        "--check",
                        "--config",
                        "quality/config/python/ruff.toml",
                        *files,
                    ],
                    300,
                    None,
                )
            )
    code, results = _run_many(root, commands)
    return _write_report(
        root,
        "format",
        code,
        {
            "applicability": "applicable",
            "scope": "changed" if _adopt_mode(project) else "full",
            "scoped_files": scoped,
            "commands": results,
        },
    )


def _lint(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    commands: list[CommandSpec] = []
    scoped: dict[str, list[str]] = {}
    js_files = _scoped_files(root, project, _relative_files(root, JS_SUFFIXES, project))
    scoped["javascript"] = js_files
    if js_files:
        eslint = _tool(root, "eslint", "js")
        for group in _chunks(js_files):
            commands.append(
                (
                    [
                        eslint,
                        "--config",
                        "quality/tools/js/config/eslint.config.mjs",
                        "--report-unused-disable-directives",
                        "--max-warnings",
                        "0",
                        *group,
                    ],
                    600,
                    None,
                )
            )
    css_files = _scoped_files(
        root, project, _relative_files(root, {".css", ".scss", ".sass", ".less"}, project)
    )
    scoped["css"] = css_files
    if css_files:
        stylelint = _tool(root, "stylelint", "js")
        for group in _chunks(css_files):
            commands.append(
                (
                    [stylelint, "--config", "quality/tools/js/config/stylelint.config.mjs", *group],
                    600,
                    None,
                    (1, 2),
                )
            )
    html_files = _scoped_files(root, project, _relative_files(root, {".html", ".htm"}, project))
    scoped["html"] = html_files
    if html_files:
        html_validate = _tool(root, "html-validate", "js")
        for group in _chunks(html_files):
            commands.append(
                (
                    [
                        html_validate,
                        "--config",
                        "quality/tools/js/config/htmlvalidate.json",
                        *group,
                    ],
                    600,
                    None,
                )
            )
    if project["stacks"].get("python"):
        py_files = _scoped_files(root, project, _relative_files(root, PY_SUFFIXES, project))
        scoped["python"] = py_files
        if py_files:
            ruff = _tool(root, "ruff", "python")
            commands.append(
                (
                    [ruff, "check", "--config", "quality/config/python/ruff.toml", *py_files],
                    600,
                    None,
                )
            )
    code, results = _run_many(root, commands)
    return _write_report(
        root,
        "lint",
        code,
        {
            "applicability": "applicable",
            "scope": "changed" if _adopt_mode(project) else "full",
            "scoped_files": scoped,
            "commands": results,
        },
    )


def _typecheck(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    commands: list[CommandSpec] = []
    if project["stacks"].get("typescript"):
        tsc = _tool(root, "tsc", "js")
        config = (
            "tsconfig.json"
            if (root / "tsconfig.json").exists()
            else "quality/config/js/tsconfig.aqg.json"
        )
        commands.append(([tsc, "--noEmit", "--pretty", "false", "-p", config], 900, None, (1, 2)))
    if project["stacks"].get("python"):
        mypy = _tool(root, "mypy", "python")
        py_targets = _existing_paths(root, source_paths(project))
        if not py_targets:
            raise ConfigurationError(
                "Python typecheck is applicable but no configured source path exists"
            )
        commands.append(
            ([mypy, "--config-file", "quality/config/python/mypy.ini", *py_targets], 900, None)
        )
    code, results = _run_many(root, commands)
    return _write_report(
        root, "typecheck", code, {"applicability": "applicable", "commands": results}
    )


def _test_integrity(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    scan = scan_test_integrity(root, project)
    commands: list[tuple[list[str], int, dict[str, str] | None]] = []
    if project["stacks"].get("python"):
        pytest = _tool(root, "pytest", "python")
        existing = [
            path
            for path in project.get("python", {}).get("test_paths", ["tests", "test"])
            if (root / path).exists()
        ]
        if existing:
            commands.append(
                (
                    [
                        pytest,
                        "--collect-only",
                        "-q",
                        "--strict-config",
                        "--strict-markers",
                        *existing,
                    ],
                    600,
                    {"PYTHONHASHSEED": "0"},
                )
            )
    if (
        project["stacks"].get("javascript")
        and project.get("javascript", {}).get("test_runner") == "vitest"
    ):
        vitest = _tool(root, "vitest", "js")
        commands.append(
            (
                [vitest, "list", "--config", "quality/tools/js/config/vitest.config.mjs"],
                600,
                {"CI": "1", "TZ": "UTC"},
            )
        )
    command_code, results = _run_many(root, commands)
    code = max(command_code, QUALITY_FAILURE if scan["errors"] else PASS)
    return _write_report(
        root,
        "test_integrity",
        code,
        {"applicability": "applicable", "integrity": scan, "commands": results},
    )


def _expand_project_command(root: Path, command: list[str]) -> list[str]:
    js_bin = str(root / "quality" / "tools" / "js" / "node_modules" / ".bin")
    py_bin = str(_bin(root, "python", "python").parent)
    return [part.replace("$AQG_JS_BIN", js_bin).replace("$AQG_PY_BIN", py_bin) for part in command]


def _unit(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    commands: list[tuple[list[str], int, dict[str, str] | None]] = []
    if project["stacks"].get("javascript"):
        command = project.get("javascript", {}).get("unit_command")
        if isinstance(command, list) and command:
            commands.append(
                (
                    _expand_project_command(root, [str(value) for value in command]),
                    1800,
                    {"CI": "1", "TZ": "UTC", "FORCE_COLOR": "0"},
                )
            )
        else:
            vitest = _tool(root, "vitest", "js")
            commands.append(
                (
                    [vitest, "run", "--config", "quality/tools/js/config/vitest.config.mjs"],
                    1800,
                    {"CI": "1", "TZ": "UTC"},
                )
            )
    if project["stacks"].get("python"):
        pytest = _tool(root, "pytest", "python")
        existing = [
            path
            for path in project.get("python", {}).get("test_paths", ["tests", "test"])
            if (root / path).exists()
        ]
        commands.append(
            (
                [pytest, "--strict-config", "--strict-markers", "-ra", "--timeout=120", *existing],
                1800,
                {"PYTHONHASHSEED": "0", "TZ": "UTC"},
            )
        )
    code, results = _run_many(root, commands)
    return _write_report(root, "unit", code, {"applicability": "applicable", "commands": results})


def _structure(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    commands: list[tuple[list[str], int, dict[str, str] | None]] = []
    scoped: dict[str, list[str]] = {}
    js_files = _scoped_files(
        root, project, _relative_files(root, JS_SUFFIXES, project, tests=False)
    )
    scoped["javascript"] = js_files
    if js_files:
        eslint = _tool(root, "eslint", "js")
        for group in _chunks(js_files):
            commands.append(
                (
                    [
                        eslint,
                        "--config",
                        "quality/tools/js/config/eslint.config.mjs",
                        "--max-warnings",
                        "0",
                        *group,
                    ],
                    900,
                    None,
                )
            )
    radon_payload: Any = None
    radon_dict: dict[str, Any] | None = None
    if project["stacks"].get("python"):
        py_files = _scoped_files(
            root, project, _relative_files(root, PY_SUFFIXES, project, tests=False)
        )
        scoped["python"] = py_files
        if py_files:
            xenon = _tool(root, "xenon", "python")
            radon = _tool(root, "radon", "python")
            commands.append(
                (
                    [
                        xenon,
                        "--max-absolute",
                        "B",
                        "--max-modules",
                        "B",
                        "--max-average",
                        "A",
                        *py_files,
                    ],
                    900,
                    None,
                )
            )
            radon_result = run_command([radon, "cc", "-j", "-s", *py_files], cwd=root, timeout=900)
            try:
                radon_payload = json.loads(radon_result.stdout) if radon_result.code == 0 else None
            except json.JSONDecodeError:
                radon_payload = None
            radon_dict = radon_result.as_dict()
    code, results = _run_many(root, commands)
    if radon_dict:
        results.append(radon_dict)
        code = max(
            code,
            PASS
            if radon_dict["code"] == 0
            else QUALITY_FAILURE
            if radon_dict["code"] == 1
            else INFRASTRUCTURE_ERROR,
        )
    return _write_report(
        root,
        "structure",
        code,
        {
            "applicability": "applicable",
            "scope": "changed" if _adopt_mode(project) else "full",
            "scoped_files": scoped,
            "commands": results,
            "radon": radon_payload,
        },
    )


def _changed_lines(root: Path, project: dict[str, Any]) -> dict[str, set[int]]:
    result: dict[str, set[int]] = {}
    path = ""
    line_no = 0
    for line in git_diff(root, _base_ref(project), unified=0).splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            line_no = int(match.group(1)) if match else 0
        elif line.startswith("+") and not line.startswith("+++"):
            result.setdefault(path, set()).add(line_no)
            line_no += 1
        elif not line.startswith("-"):
            line_no += 1
    return result


def _python_coverage_metrics(root: Path, path: Path, project: dict[str, Any]) -> dict[str, Any]:
    payload = read_json(path)
    totals = payload.get("totals", {})
    line_pct = float(totals.get("percent_covered", 0.0))
    branches = int(totals.get("num_branches", 0))
    covered_branches = int(totals.get("covered_branches", 0))
    branch_pct = 100.0 if branches == 0 else covered_branches * 100 / branches
    changed = _changed_lines(root, project)
    relevant = 0
    covered = 0
    files = payload.get("files", {})
    for filename, changed_set in changed.items():
        if not filename.endswith(".py") or _is_test_path(filename):
            continue
        data = files.get(filename) or files.get(str((root / filename).resolve()))
        if not isinstance(data, dict):
            continue
        executable = set(data.get("executed_lines", [])) | set(data.get("missing_lines", []))
        relevant_lines = changed_set & executable
        relevant += len(relevant_lines)
        covered += len(relevant_lines & set(data.get("executed_lines", [])))
    changed_pct = None if relevant == 0 else covered * 100 / relevant
    thresholds = _effective_thresholds(project)["coverage"]
    failures: list[str] = []
    changed_production = [
        path for path in changed if path.endswith(".py") and not _is_test_path(path)
    ]
    if not _adopt_mode(project):
        if line_pct < float(thresholds["lines"]):
            failures.append(f"line coverage {line_pct:.1f}% < {thresholds['lines']}%")
        if branch_pct < float(thresholds["branches"]):
            failures.append(f"branch coverage {branch_pct:.1f}% < {thresholds['branches']}%")
    if changed_production and changed_pct is None:
        failures.append("changed Python production lines are absent from coverage evidence")
    elif changed_pct is not None and changed_pct < float(thresholds["changed_lines"]):
        failures.append(
            f"changed-line coverage {changed_pct:.1f}% < {thresholds['changed_lines']}%"
        )
    return {
        "mode": "changed" if _adopt_mode(project) else "full",
        "lines": line_pct,
        "branches": branch_pct,
        "changed_lines": changed_pct,
        "changed_executable_lines": relevant,
        "changed_production_files": changed_production,
        "failures": failures,
    }


def _js_coverage_metrics(
    root: Path, summary_path: Path, final_path: Path, project: dict[str, Any]
) -> dict[str, Any]:
    summary = read_json(summary_path)
    total = summary.get("total", {})
    metrics: dict[str, Any] = {
        name: float(total.get(name, {}).get("pct", 0.0))
        for name in ("lines", "branches", "functions", "statements")
    }
    changed = _changed_lines(root, project)
    relevant = covered = 0
    if final_path.exists():
        final = read_json(final_path)
        for filename, data in final.items():
            try:
                rel = Path(filename).resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                rel = filename
            if rel not in changed or _is_test_path(rel):
                continue
            changed_set = changed[rel]
            statement_map = data.get("statementMap", {})
            counts = data.get("s", {})
            for key, location in statement_map.items():
                line = int(location.get("start", {}).get("line", 0))
                if line in changed_set:
                    relevant += 1
                    covered += int(counts.get(key, 0)) > 0
    metrics["changed_lines"] = None if relevant == 0 else covered * 100 / relevant
    metrics["changed_executable_lines"] = relevant
    thresholds = _effective_thresholds(project)["coverage"]
    failures: list[str] = []
    changed_production = [
        path
        for path in changed
        if Path(path).suffix.lower() in JS_SUFFIXES and not _is_test_path(path)
    ]
    if not _adopt_mode(project):
        for name in ("lines", "branches", "functions", "statements"):
            if metrics[name] < float(thresholds[name]):
                failures.append(f"{name} coverage {metrics[name]:.1f}% < {thresholds[name]}%")
    if changed_production and metrics["changed_lines"] is None:
        failures.append(
            "changed JavaScript/TypeScript production lines are absent from coverage evidence"
        )
    elif metrics["changed_lines"] is not None and metrics["changed_lines"] < float(
        thresholds["changed_lines"]
    ):
        failures.append(
            f"changed-line coverage {metrics['changed_lines']:.1f}% < {thresholds['changed_lines']}%"
        )
    metrics["mode"] = "changed" if _adopt_mode(project) else "full"
    metrics["changed_production_files"] = changed_production
    metrics["failures"] = failures
    return metrics


def _python_crap(
    root: Path, project: dict[str, Any], coverage_path: Path, files: list[str] | None = None
) -> dict[str, Any]:
    radon = _tool(root, "radon", "python")
    targets = files or _existing_paths(root, source_paths(project))
    if not targets:
        return {"functions": [], "failures": [], "scope": "none"}
    result = run_command([radon, "cc", "-j", "-s", *targets], cwd=root, timeout=900)
    if result.code != 0:
        return {
            "error": result.stderr or result.stdout,
            "functions": [],
            "failures": ["radon could not produce complexity evidence"],
        }
    try:
        complexity = json.loads(result.stdout)
        coverage = read_json(coverage_path)
    except (json.JSONDecodeError, ConfigurationError) as exc:
        return {
            "error": str(exc),
            "functions": [],
            "failures": ["complexity or coverage evidence is unreadable"],
        }
    functions: list[dict[str, Any]] = []
    maximum = float(_effective_thresholds(project)["structure"]["max_crap"])
    failures: list[str] = []
    coverage_files = coverage.get("files", {})
    for filename, blocks in complexity.items():
        data = (
            coverage_files.get(filename)
            or coverage_files.get(str((root / filename).resolve()))
            or {}
        )
        executed = set(data.get("executed_lines", []))
        missing = set(data.get("missing_lines", []))
        executable = executed | missing
        for block in blocks:
            if block.get("type") not in {"function", "method"}:
                continue
            start = int(block.get("lineno", 0))
            end = int(block.get("endline", start))
            relevant = {line for line in executable if start <= line <= end}
            coverage_fraction = 1.0 if not relevant else len(relevant & executed) / len(relevant)
            complexity_value = int(block.get("complexity", 1))
            score = crap_score(complexity_value, coverage_fraction)
            item = {
                "path": filename,
                "name": block.get("name"),
                "line": start,
                "end_line": end,
                "complexity": complexity_value,
                "coverage": coverage_fraction * 100,
                "crap": score,
            }
            functions.append(item)
            if score > maximum:
                failures.append(
                    f"{filename}:{start} {block.get('name')} CRAP {score:.1f} > {maximum:.1f}"
                )
    functions.sort(key=lambda item: item["crap"], reverse=True)
    return {"functions": functions, "failures": failures, "maximum_allowed": maximum}


def _coverage(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    final = PASS
    if project["stacks"].get("javascript"):
        runner = project.get("javascript", {}).get("test_runner")
        custom = project.get("javascript", {}).get("coverage_command")
        if isinstance(custom, list) and custom:
            command = _expand_project_command(root, [str(value) for value in custom])
        elif runner == "vitest":
            command = [
                _tool(root, "vitest", "js"),
                "run",
                "--coverage",
                "--config",
                "quality/tools/js/config/vitest.config.mjs",
            ]
        else:
            raise ConfigurationError(
                "JavaScript coverage needs javascript.coverage_command or a Vitest test runner"
            )
        result = run_command(command, cwd=root, timeout=2400, env={"CI": "1", "TZ": "UTC"})
        commands.append(result.as_dict())
        final = max(
            final,
            PASS
            if result.code == 0
            else QUALITY_FAILURE
            if result.code == 1
            else INFRASTRUCTURE_ERROR,
        )
        summary = root / ".aqg" / "work" / "coverage" / "js" / "coverage-summary.json"
        final_json = root / ".aqg" / "work" / "coverage" / "js" / "coverage-final.json"
        if result.code == 0 and summary.exists():
            js_metrics = _js_coverage_metrics(root, summary, final_json, project)
            metrics["javascript"] = js_metrics
            if js_metrics["failures"]:
                final = max(final, QUALITY_FAILURE)
        elif result.code == 0:
            final = max(final, INFRASTRUCTURE_ERROR)
            metrics["javascript"] = {
                "failures": ["coverage command passed but coverage-summary.json was not produced"]
            }
    if project["stacks"].get("python"):
        pytest = _tool(root, "pytest", "python")
        coverage_path = root / ".aqg" / "work" / "coverage" / "python-coverage.json"
        coverage_path.parent.mkdir(parents=True, exist_ok=True)
        existing_tests = [
            path
            for path in project.get("python", {}).get("test_paths", ["tests", "test"])
            if (root / path).exists()
        ]
        cov_args = [
            argument
            for source in project.get("python", {}).get("source_paths", source_paths(project))
            for argument in ("--cov", source)
        ]
        command = [
            pytest,
            "--strict-config",
            "--strict-markers",
            "--cov-branch",
            *cov_args,
            f"--cov-report=json:{coverage_path}",
            "--cov-report=term-missing",
            *existing_tests,
        ]
        result = run_command(
            command,
            cwd=root,
            timeout=2400,
            env={
                "COVERAGE_FILE": str(coverage_path.parent / ".coverage"),
                "PYTHONHASHSEED": "0",
                "TZ": "UTC",
            },
        )
        commands.append(result.as_dict())
        final = max(
            final,
            PASS
            if result.code == 0
            else QUALITY_FAILURE
            if result.code == 1
            else INFRASTRUCTURE_ERROR,
        )
        if result.code == 0 and coverage_path.exists():
            py_metrics = _python_coverage_metrics(root, coverage_path, project)
            crap_targets = _scoped_files(
                root, project, _relative_files(root, PY_SUFFIXES, project, tests=False)
            )
            crap = _python_crap(root, project, coverage_path, crap_targets)
            py_metrics["crap"] = crap
            metrics["python"] = py_metrics
            if py_metrics["failures"] or crap["failures"]:
                final = max(final, QUALITY_FAILURE)
        elif result.code == 0:
            final = max(final, INFRASTRUCTURE_ERROR)
            metrics["python"] = {"failures": ["pytest passed but coverage JSON was not produced"]}
    return _write_report(
        root,
        "coverage",
        final,
        {"applicability": "applicable", "commands": commands, "metrics": metrics},
    )


def _contract_paths(root: Path) -> list[str]:
    return [
        path
        for path in ("tests/contracts", "test/contracts", "contracts")
        if (root / path).exists()
    ]


def _contracts(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    paths = _contract_paths(root)
    if not paths:
        raise ConfigurationError("contracts gate is applicable but no contract-test path exists")
    commands: list[tuple[list[str], int, dict[str, str] | None]] = []
    if project["stacks"].get("python"):
        commands.append(
            (
                [
                    _tool(root, "pytest", "python"),
                    "--strict-config",
                    "--strict-markers",
                    "-ra",
                    *paths,
                ],
                1800,
                {"PYTHONHASHSEED": "0"},
            )
        )
    if project["stacks"].get("javascript"):
        commands.append(
            (
                [
                    _tool(root, "vitest", "js"),
                    "run",
                    "--config",
                    "quality/tools/js/config/vitest.config.mjs",
                    *paths,
                ],
                1800,
                {"CI": "1"},
            )
        )
    code, results = _run_many(root, commands)
    return _write_report(
        root, "contracts", code, {"applicability": "applicable", "commands": results}
    )


def _acceptance(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    lint = lint_features(root)
    final = QUALITY_FAILURE if lint["errors"] else PASS
    commands: list[dict[str, Any]] = []
    executed = False
    custom = project.get("acceptance_command")
    if isinstance(custom, list) and custom:
        result = run_command(
            _expand_project_command(root, [str(value) for value in custom]),
            cwd=root,
            timeout=2400,
            env={"CI": "1", "TZ": "UTC"},
        )
        commands.append(result.as_dict())
        final = max(
            final,
            PASS
            if result.code == 0
            else QUALITY_FAILURE
            if result.code == 1
            else INFRASTRUCTURE_ERROR,
        )
        executed = True
    browser_files = [
        path
        for path in _relative_files(root, {".js", ".mjs", ".ts"}, project, tests=True)
        if any(token in path.lower() for token in ("e2e", "acceptance", "aqg-browser"))
    ]
    if (
        project["stacks"].get("html") or project.get("web", {}).get("start_command")
    ) and browser_files:
        result = run_command(
            [
                _tool(root, "playwright", "js"),
                "test",
                "--config",
                "quality/tools/js/config/playwright.config.mjs",
            ],
            cwd=root,
            timeout=2400,
            env={"CI": "1", "TZ": "UTC"},
        )
        commands.append(result.as_dict())
        final = max(
            final,
            PASS
            if result.code == 0
            else QUALITY_FAILURE
            if result.code == 1
            else INFRASTRUCTURE_ERROR,
        )
        executed = True
    if project["stacks"].get("python"):
        python_acceptance = [
            path
            for path in _relative_files(root, {".py"}, project, tests=True)
            if "acceptance" in Path(path).name.lower() or "e2e" in path.lower()
        ]
        if python_acceptance:
            result = run_command(
                [
                    _tool(root, "pytest", "python"),
                    "--strict-config",
                    "--strict-markers",
                    "-ra",
                    *python_acceptance,
                ],
                cwd=root,
                timeout=2400,
                env={"PYTHONHASHSEED": "0", "TZ": "UTC"},
            )
            commands.append(result.as_dict())
            final = max(
                final,
                PASS
                if result.code == 0
                else QUALITY_FAILURE
                if result.code == 1
                else INFRASTRUCTURE_ERROR,
            )
            executed = True
    if not executed:
        final = max(final, CONFIGURATION_ERROR)
    return _write_report(
        root,
        "acceptance",
        final,
        {
            "applicability": "applicable",
            "feature_lint": lint,
            "executed": executed,
            "commands": commands,
            "configuration_error": None
            if executed
            else "No executable acceptance command or test suite was found.",
        },
    )


def _golden(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    code, report = run_goldens(root)
    return _write_report(root, "golden", code, {"applicability": "applicable", "golden": report})


def _copy_for_mutmut(root: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    ignore = shutil.ignore_patterns(
        ".git",
        ".aqg",
        ".venv",
        "venv",
        "node_modules",
        "quality/tools",
        "quality/_aqg",
        "dist",
        "build",
        "coverage",
        "htmlcov",
        "mutants",
        "__pycache__",
        "*.pyc",
    )
    shutil.copytree(root, destination, ignore=ignore)


def _upsert_toml_array(text: str, section: str, key: str, values: list[str]) -> str:
    """Upsert a simple array key in a TOML section inside a disposable sandbox."""
    lines = text.splitlines()
    section_header = f"[{section}]"
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == section_header)
    except StopIteration:
        suffix = "\n" if text.endswith("\n") else "\n\n"
        return text + suffix + section_header + "\n" + key + " = " + json.dumps(values) + "\n"
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].strip().startswith("[") and lines[index].strip().endswith("]")
        ),
        len(lines),
    )
    filtered: list[str] = []
    index = start + 1
    while index < end:
        line = lines[index]
        if re.match(rf"^\s*{re.escape(key)}\s*=", line):
            balance = line.count("[") - line.count("]")
            index += 1
            while balance > 0 and index < end:
                balance += lines[index].count("[") - lines[index].count("]")
                index += 1
            continue
        filtered.append(line)
        index += 1
    replacement = lines[: start + 1] + [f"{key} = {json.dumps(values)}", *filtered] + lines[end:]
    return "\n".join(replacement).rstrip() + "\n"


def _append_mutmut_config(
    project_copy: Path, project: dict[str, Any], only_mutate: list[str]
) -> None:
    pyproject = project_copy / "pyproject.toml"
    original = (
        pyproject.read_text(encoding="utf-8")
        if pyproject.exists()
        else "[project]\nname='aqg-mutation-sandbox'\nversion='0.0.0'\n"
    )
    sources = project.get("python", {}).get("source_paths", source_paths(project))
    tests = project.get("python", {}).get("test_paths", ["tests", "test"])
    if "[tool.mutmut]" not in original:
        original = original.rstrip() + "\n\n[tool.mutmut]\n"
        original += "source_paths = " + json.dumps(sources) + "\n"
        original += (
            "pytest_add_cli_args_test_selection = "
            + json.dumps([path for path in tests if (project_copy / path).exists()])
            + "\n"
        )
        original += "mutate_only_covered_lines = true\nmax_stack_depth = 8\non_dependency_change = 'rerun'\n"
    original = _upsert_toml_array(original, "tool.mutmut", "only_mutate", only_mutate)
    pyproject.write_text(original, encoding="utf-8")


def _mutation_python(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    if os.name == "nt":
        return CONFIGURATION_ERROR, {
            "configuration_error": "mutmut requires fork support; run the mutation gate inside WSL on Windows"
        }
    changed = (
        _changed_production_files(root, project, PY_SUFFIXES)
        if _effective_thresholds(project)["mutation"].get("changed_only", True)
        else _relative_files(root, PY_SUFFIXES, project, tests=False)
    )
    if not changed:
        return PASS, {
            "scope": "changed",
            "mutated_files": [],
            "reason": "no changed Python production files",
        }
    work = root / ".aqg" / "work" / "mutation" / "python-project"
    _copy_for_mutmut(root, work)
    _append_mutmut_config(work, project, changed)
    mutmut = _tool(root, "mutmut", "python")
    python_path = os.pathsep.join([str(work), str(work / "src"), os.environ.get("PYTHONPATH", "")])
    run = run_command(
        [mutmut, "run"],
        cwd=work,
        timeout=7200,
        env={"PYTHONPATH": python_path, "PYTHONHASHSEED": "0", "TZ": "UTC"},
    )
    results = run_command(
        [mutmut, "results"], cwd=work, timeout=300, env={"PYTHONPATH": python_path}
    )
    text = run.stdout + "\n" + run.stderr + "\n" + results.stdout + "\n" + results.stderr
    survivors = 0
    for pattern in (r"(?i)survived\D+(\d+)", r"🙁\s*(\d+)"):
        match = re.search(pattern, text)
        if match:
            survivors = max(survivors, int(match.group(1)))
    listed = [
        line
        for line in results.stdout.splitlines()
        if re.search(r"(?i)(survived|x_.*__mutmut_)", line)
    ]
    survivors = max(survivors, len(listed))
    maximum = int(_effective_thresholds(project)["mutation"].get("maximum_survivors", 0))
    if run.code not in {0, 1} or results.code not in {0, 1}:
        code = INFRASTRUCTURE_ERROR
    elif survivors > maximum:
        code = QUALITY_FAILURE
    elif run.code == 1 and not survivors:
        code = INFRASTRUCTURE_ERROR
    else:
        code = PASS
    return code, {
        "scope": "changed",
        "mutated_files": changed,
        "run": run.as_dict(),
        "results": results.as_dict(),
        "survivors": survivors,
        "maximum_survivors": maximum,
        "survivor_lines": listed[:200],
    }


def _collect_mutant_statuses(value: Any, output: list[str]) -> None:
    if isinstance(value, dict):
        status = value.get("status")
        if isinstance(status, str) and "id" in value:
            output.append(status)
        for child in value.values():
            _collect_mutant_statuses(child, output)
    elif isinstance(value, list):
        for child in value:
            _collect_mutant_statuses(child, output)


def _mutation_js(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    changed = (
        _changed_production_files(root, project, JS_SUFFIXES)
        if _effective_thresholds(project)["mutation"].get("changed_only", True)
        else _relative_files(root, JS_SUFFIXES, project, tests=False)
    )
    if not changed:
        return PASS, {
            "scope": "changed",
            "mutated_files": [],
            "reason": "no changed JavaScript/TypeScript production files",
        }
    stryker = _tool(root, "stryker", "js")
    work = root / ".aqg" / "work" / "mutation"
    work.mkdir(parents=True, exist_ok=True)
    config_path = work / "stryker.changed.config.mjs"
    mutate_json = json.dumps(changed)
    config_path.write_text(
        "import base from '../../../quality/tools/js/config/stryker.config.mjs';\n"
        f"export default {{ ...base, mutate: {mutate_json}, incremental: false }};\n",
        encoding="utf-8",
    )
    result = run_command(
        [stryker, "run", str(config_path)], cwd=root, timeout=7200, env={"CI": "1", "TZ": "UTC"}
    )
    report_path = root / ".aqg" / "work" / "mutation" / "stryker.json"
    payload = read_json(report_path, default={}) if report_path.exists() else {}
    statuses: list[str] = []
    _collect_mutant_statuses(payload, statuses)
    counts: dict[str, int] = {}
    for status in statuses:
        counts[status] = counts.get(status, 0) + 1
    killed = counts.get("Killed", 0) + counts.get("Timeout", 0)
    survived = counts.get("Survived", 0) + counts.get("NoCoverage", 0)
    denominator = killed + survived
    score = (
        100.0
        if denominator == 0 and statuses
        else (killed * 100 / denominator if denominator else 0.0)
    )
    threshold = float(_effective_thresholds(project)["mutation"].get("minimum_score", 70))
    maximum = int(_effective_thresholds(project)["mutation"].get("maximum_survivors", 0))
    failures: list[str] = []
    if not report_path.exists() or not statuses:
        code = INFRASTRUCTURE_ERROR
        failures.append("Stryker did not produce a readable non-empty mutation report")
    else:
        if survived > maximum:
            failures.append(f"{survived} survived/no-coverage mutants > allowed {maximum}")
        if score < threshold:
            failures.append(f"mutation score {score:.1f}% < {threshold:.1f}%")
        code = (
            QUALITY_FAILURE
            if failures or result.code == 1
            else PASS
            if result.code == 0
            else INFRASTRUCTURE_ERROR
        )
    return code, {
        "scope": "changed",
        "mutated_files": changed,
        "command": result.as_dict(),
        "report": payload,
        "status_counts": counts,
        "mutation_score": score,
        "minimum_score": threshold,
        "maximum_survivors": maximum,
        "failures": failures,
    }


def _mutation_changed(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    details: dict[str, Any] = {}
    final = PASS
    if project["stacks"].get("javascript"):
        code, report = _mutation_js(root, project)
        details["javascript"] = report
        final = max(final, code)
    if project["stacks"].get("python"):
        code, report = _mutation_python(root, project)
        details["python"] = report
        final = max(final, code)
    return _write_report(
        root, "mutation_changed", final, {"applicability": "applicable", **details}
    )


def _mutation_acceptance(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    code, report = run_acceptance_mutation(root)
    return _write_report(
        root, "mutation_acceptance", code, {"applicability": "applicable", "mutation": report}
    )


def _review(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    policy = load_policy(root)
    base = _base_ref(project)
    packet = analyze_review(root, policy, base=base, require_evidence=False)
    paths = write_review_packet(root, packet)
    code = review_exit_code(packet)
    return _write_report(
        root, "review", code, {"applicability": "applicable", "packet": packet, "artifacts": paths}
    )


def _secrets(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    report = scan_secrets(root, project, changed_only=False)
    code = QUALITY_FAILURE if report["errors"] else PASS
    return _write_report(root, "secrets", code, {"applicability": "applicable", "scan": report})


def _package_audit_command(root: Path, project: dict[str, Any]) -> list[str] | None:
    manager = project.get("javascript", {}).get("package_manager")
    if manager == "npm" and (root / "package-lock.json").exists():
        return ["npm", "audit", "--audit-level=high"]
    if manager == "pnpm" and (root / "pnpm-lock.yaml").exists():
        return ["pnpm", "audit", "--audit-level", "high"]
    if manager == "yarn" and (root / "yarn.lock").exists():
        return ["yarn", "npm", "audit", "--severity", "high"]
    if manager == "bun" and ((root / "bun.lock").exists() or (root / "bun.lockb").exists()):
        return ["bun", "audit"]
    return None


def _security_fast(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    commands: list[tuple[list[str], int, dict[str, str] | None]] = []
    package_audit = _package_audit_command(root, project)
    if package_audit:
        commands.append((package_audit, 1200, {"CI": "1"}))
    if project["stacks"].get("python"):
        pip_audit = _tool(root, "pip-audit", "python")
        bandit = _tool(root, "bandit", "python")
        audit_level = str(
            project.get("thresholds", {}).get("security", {}).get("audit_level", "high")
        )
        bandit_severity = {"low": "-l", "medium": "-ll", "high": "-lll"}.get(audit_level)
        if bandit_severity is None:
            raise ConfigurationError("thresholds.security.audit_level must be low, medium, or high")
        commands.append(([pip_audit, "--local", "--progress-spinner", "off"], 1200, None))
        commands.append(
            (
                [
                    bandit,
                    "-q",
                    bandit_severity,
                    "-r",
                    "-c",
                    "quality/config/python/bandit.yaml",
                    *_existing_paths(root, source_paths(project)),
                ],
                1200,
                None,
            )
        )
    code, results = _run_many(root, commands)

    # Audit the protected AQG JavaScript toolchain from its own package root. npm_config_prefix
    # changes global installation behavior; it does not select the package-lock being audited.
    tool_dir = root / "quality" / "tools" / "js"
    tool_lock = tool_dir / "package-lock.json"
    if tool_lock.exists():
        result = run_command(
            ["npm", "audit", "--audit-level=high"], cwd=tool_dir, timeout=1200, env={"CI": "1"}
        )
        results.append(result.as_dict())
        code = max(
            code,
            PASS
            if result.code == 0
            else QUALITY_FAILURE
            if result.code == 1
            else INFRASTRUCTURE_ERROR,
        )

    secret_report = scan_secrets(root, project, changed_only=True)
    code = max(code, QUALITY_FAILURE if secret_report["errors"] else PASS)
    return _write_report(
        root,
        "security_fast",
        code,
        {"applicability": "applicable", "commands": results, "changed_secret_scan": secret_report},
    )


def _dangerous_code_scan(root: Path, project: dict[str, Any]) -> dict[str, Any]:
    patterns = [
        ("dynamic-code", re.compile(r"\b(?:eval|exec)\s*\(")),
        (
            "shell-execution",
            re.compile(r"(?i)(shell\s*=\s*true|child_process\.(?:exec|execSync)\s*\()"),
        ),
        ("weak-randomness", re.compile(r"\bMath\.random\s*\(|\brandom\.random\s*\(")),
        ("unsafe-html", re.compile(r"(?i)(dangerouslySetInnerHTML|innerHTML\s*=|mark_safe\s*\()")),
        ("disabled-tls", re.compile(r"(?i)(verify\s*=\s*false|rejectUnauthorized\s*:\s*false)")),
    ]
    findings = []
    for path in iter_files(root, JS_SUFFIXES | PY_SUFFIXES, excludes(project)):
        rel = path.relative_to(root).as_posix()
        if _is_test_path(rel):
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(content.splitlines(), 1):
            for code, pattern in patterns:
                if pattern.search(line) and "AQG_REVIEWED_SECURITY" not in line:
                    findings.append(
                        {"code": code, "path": rel, "line": line_no, "message": line.strip()[:240]}
                    )
    return {"findings": findings, "errors": len(findings)}


def _security_deep(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    commands: list[tuple[list[str], int, dict[str, str] | None]] = []
    if project["stacks"].get("python"):
        bandit = _tool(root, "bandit", "python")
        commands.append(
            (
                [
                    bandit,
                    "-r",
                    "-lll",
                    "-iii",
                    "-c",
                    "quality/config/python/bandit.yaml",
                    *source_paths(project),
                ],
                1800,
                None,
            )
        )
        vulture = _tool(root, "vulture", "python")
        commands.append(([vulture, *source_paths(project), "--min-confidence", "90"], 1800, None))
    # Knip is useful only for package projects and remains deep-profile because framework conventions can need configuration.
    if project["stacks"].get("javascript") and (root / "package.json").exists():
        knip = _tool(root, "knip", "js")
        commands.append(([knip, "--production"], 1800, {"CI": "1"}))
    code, results = _run_many(root, commands)
    dangerous = _dangerous_code_scan(root, project)
    code = max(code, QUALITY_FAILURE if dangerous["errors"] else PASS)
    return _write_report(
        root,
        "security_deep",
        code,
        {"applicability": "applicable", "commands": results, "dangerous_patterns": dangerous},
    )


def _supply_chain(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    inventory = generate_sboms(root, project)
    code = CONFIGURATION_ERROR if inventory["errors"] else PASS
    return _write_report(
        root,
        "supply_chain",
        code,
        {
            "applicability": "applicable",
            "inventory": inventory,
            "findings": inventory["errors"],
            "note": "Vulnerability discovery remains part of security_fast; this gate proves a deterministic lock-derived inventory exists.",
        },
    )


def _url_ready(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    connection_type = (
        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_type(parsed.hostname, parsed.port, timeout=2)
    try:
        target = urllib.parse.urlunparse(
            ("", "", parsed.path or "/", parsed.params, parsed.query, "")
        )
        connection.request("GET", target)
        status = int(connection.getresponse().status)
        return 200 <= status < 400
    except (OSError, TimeoutError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def _start_web(
    root: Path, command: list[str], url: str
) -> tuple[subprocess.Popen[str] | None, Path]:
    log_path = root / ".aqg" / "work" / "performance" / "web-server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if _url_ready(url):
        return None, log_path
    handle = log_path.open("w", encoding="utf-8")
    kwargs: dict[str, Any] = {
        "cwd": root,
        "stdout": handle,
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    if os.name != "nt":
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if process.poll() is not None:
            handle.close()
            raise ConfigurationError(f"web server exited before becoming ready; inspect {log_path}")
        if _url_ready(url):
            handle.close()
            return process, log_path
        time.sleep(1)
    handle.close()
    _stop_process(process)
    raise ConfigurationError(f"web server did not become ready at {url}; inspect {log_path}")


def _stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=10)
    except Exception:
        process.kill()


def _performance(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    web = project.get("web", {})
    command = web.get("start_command")
    url = web.get("base_url")
    if not isinstance(command, list) or not command or not isinstance(url, str):
        raise ConfigurationError("performance gate needs web.start_command and web.base_url")
    process, log = _start_web(root, [str(value) for value in command], url)
    try:
        tool_dir = root / "quality" / "tools" / "js"
        browser_probe = run_command(
            [
                "node",
                "-e",
                "const {chromium}=require('playwright');process.stdout.write(chromium.executablePath())",
            ],
            cwd=tool_dir,
            timeout=60,
        )
        browser_path = Path(browser_probe.stdout.strip())
        if browser_probe.code != 0 or not browser_path.is_file():
            return _write_report(
                root,
                "performance",
                INFRASTRUCTURE_ERROR,
                {
                    "applicability": "applicable",
                    "base_url": url,
                    "server_log": str(log),
                    "command": browser_probe.as_dict(),
                    "failures": [
                        "Playwright Chromium is unavailable; install it explicitly with `qg tools install --browsers`."
                    ],
                },
            )
        report_path = root / ".aqg" / "work" / "performance" / "lighthouse.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        performance_thresholds = _effective_thresholds(project).get("performance", {})
        lighthouse = _tool(root, "lighthouse", "js")
        result = run_command(
            [
                lighthouse,
                url,
                "--quiet",
                "--output=json",
                f"--output-path={report_path}",
                "--chrome-flags=--headless --no-sandbox",
            ],
            cwd=root,
            timeout=3600,
            env={"CHROME_PATH": str(browser_path), "CI": "1", "TZ": "UTC"},
        )
        metrics: dict[str, float] = {}
        failures: list[str] = []
        if result.code == 0 and report_path.is_file():
            report = read_json(report_path)
            categories = report.get("categories", {})
            for name, threshold_name, default in (
                ("performance", "lighthouse_performance", 0.8),
                ("accessibility", "lighthouse_accessibility", 0.95),
            ):
                score = float(categories.get(name, {}).get("score", 0.0))
                minimum = float(performance_thresholds.get(threshold_name, default))
                metrics[name] = score
                if score < minimum:
                    failures.append(f"{name} score {score:.2f} < {minimum:.2f}")
            code = QUALITY_FAILURE if failures else PASS
        elif result.code == 0:
            code = INFRASTRUCTURE_ERROR
            failures.append("Lighthouse passed without producing its JSON report")
        else:
            code = QUALITY_FAILURE if result.code == 1 else INFRASTRUCTURE_ERROR
            failures.append("Lighthouse execution failed")
    finally:
        _stop_process(process)
    return _write_report(
        root,
        "performance",
        code,
        {
            "applicability": "applicable",
            "base_url": url,
            "server_log": str(log),
            "command": result.as_dict(),
            "report": str(report_path),
            "metrics": metrics,
            "failures": failures,
        },
    )


def _directory_manifest(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {
        file.relative_to(path).as_posix(): sha256_file(file)
        for file in sorted(path.rglob("*"))
        if file.is_file()
    }


def _reproducible_build(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    command = project.get("javascript", {}).get("build_command") or project.get("build_command")
    if not isinstance(command, list) or not command:
        raise ConfigurationError("reproducible build gate needs a build command")
    output_candidates = [
        Path(value) for value in project.get("build_outputs", ["dist", "build", ".next", "out"])
    ]
    manifests: list[dict[str, dict[str, str]]] = []
    commands: list[dict[str, Any]] = []
    final = PASS
    for _iteration in range(2):
        for output in output_candidates:
            target = root / output
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
        result = run_command(
            _expand_project_command(root, [str(value) for value in command]),
            cwd=root,
            timeout=3600,
            env={"CI": "1", "TZ": "UTC", "SOURCE_DATE_EPOCH": "0"},
        )
        commands.append(result.as_dict())
        if result.code != 0:
            final = QUALITY_FAILURE if result.code == 1 else INFRASTRUCTURE_ERROR
            break
        manifests.append(
            {
                str(output): _directory_manifest(root / output)
                for output in output_candidates
                if (root / output).exists()
            }
        )
    if final == PASS and not manifests[0]:
        final = CONFIGURATION_ERROR
    elif final == PASS and manifests[0] != manifests[1]:
        final = QUALITY_FAILURE
    return _write_report(
        root,
        "reproducible_build",
        final,
        {
            "applicability": "applicable",
            "commands": commands,
            "manifests_equal": len(manifests) == 2 and manifests[0] == manifests[1],
            "manifests": manifests,
        },
    )


def _release_readiness(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    policy = load_policy(root)
    errors, risk = risk_summary(root, policy, "quality/change-risk.json")
    findings: list[str] = list(errors)
    run_id = os.environ.get("AQG_RUN_ID")
    if run_id:
        gate_dir = root / ".aqg" / "runs" / run_id / "gates"
        for path in gate_dir.glob("*.json") if gate_dir.exists() else []:
            evidence = read_json(path)
            if evidence.get("exit_code") != PASS:
                findings.append(f"gate {evidence.get('gate')} is not green")
    packet = analyze_review(root, policy, base=_base_ref(project), require_evidence=False)
    if packet["summary"]["blockers"]:
        findings.append(f"automated review has {packet['summary']['blockers']} blocker(s)")
    selected = str(risk.get("selected_risk_profile") or "standard")
    approvals = validate_required_approvals(root, selected)
    findings.extend(f"approval {message}" for message in approvals["errors"])
    for required in (
        root / ".github" / "workflows" / "quality-gauntlet.yml",
        root / ".github" / "CODEOWNERS",
    ):
        if not required.exists():
            findings.append(f"missing release governance file {required.relative_to(root)}")
    code = QUALITY_FAILURE if findings else PASS
    return _write_report(
        root,
        "release_readiness",
        code,
        {
            "applicability": "applicable",
            "risk": risk,
            "review": packet["summary"],
            "approvals": approvals,
            "findings": findings,
        },
    )


HANDLERS: dict[str, Callable[[Path, dict[str, Any]], tuple[int, dict[str, Any]]]] = {
    "format": _format,
    "lint": _lint,
    "typecheck": _typecheck,
    "test_integrity": _test_integrity,
    "unit": _unit,
    "structure": _structure,
    "coverage": _coverage,
    "contracts": _contracts,
    "acceptance": _acceptance,
    "golden": _golden,
    "mutation_changed": _mutation_changed,
    "mutation_acceptance": _mutation_acceptance,
    "review": _review,
    "secrets": _secrets,
    "security_fast": _security_fast,
    "security_deep": _security_deep,
    "supply_chain": _supply_chain,
    "performance": _performance,
    "reproducible_build": _reproducible_build,
    "release_readiness": _release_readiness,
}


def run_adapter(root: Path, gate: str) -> tuple[int, dict[str, Any]]:
    project = load_project(root)
    applicable, reason = gate_applicable(project, gate)
    if not applicable:
        return _not_applicable(root, gate, reason)
    handler = HANDLERS.get(gate)
    if handler is None:
        raise ConfigurationError(f"no adapter implementation for gate {gate!r}")
    code, report = handler(root, project)
    summary_parts: list[str] = []
    for key in ("commands", "findings", "metrics"):
        value = report.get(key)
        if value:
            summary_parts.append(f"{key}={len(value) if hasattr(value, '__len__') else 'yes'}")
    print(
        f"{gate}: {report['status']}" + (" · " + ", ".join(summary_parts) if summary_parts else "")
    )
    if code != PASS:
        for source in (report.get("configuration_error"), *report.get("findings", [])):
            if source:
                print(str(source), file=sys.stderr)
    return code, report
