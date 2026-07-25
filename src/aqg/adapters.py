"""JavaScript, TypeScript, HTML, CSS, and Python gate adapters."""

from __future__ import annotations

import ast
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
        is_test = _is_test_path(rel, project)
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
        and not _is_test_path(path, project)
        and (root / path).is_file()
    ]


def _is_test_path(path: str, project: dict[str, Any] | None = None) -> bool:
    normalized = Path(path).as_posix().strip("/")
    configured: list[str] = []
    if project:
        configured.extend(str(value) for value in project.get("paths", {}).get("tests", []))
        configured.extend(str(value) for value in project.get("python", {}).get("test_paths", []))
    for root in configured:
        test_root = Path(root).as_posix().strip("/")
        if test_root and (normalized == test_root or normalized.startswith(f"{test_root}/")):
            return True
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


def _expand_project_command(root: Path, command: list[str]) -> list[str]:
    js_bin = str(root / "quality" / "tools" / "js" / "node_modules" / ".bin")
    py_bin = str(_bin(root, "python", "python").parent)
    return [part.replace("$AQG_JS_BIN", js_bin).replace("$AQG_PY_BIN", py_bin) for part in command]


def _python_test_env(root: Path, *, timezone: bool = False) -> dict[str, str]:
    entries = [str(root), str(root / "src")]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        entries.append(existing)
    environment = {"PYTHONHASHSEED": "0", "PYTHONPATH": os.pathsep.join(entries)}
    if timezone:
        environment["TZ"] = "UTC"
    return environment


def _python_collection_spec(root: Path, project: dict[str, Any]) -> CommandSpec | None:
    python = project.get("python", {})
    custom = python.get("collect_command")
    if isinstance(custom, list) and custom:
        return (
            _expand_project_command(root, [str(value) for value in custom]),
            600,
            _python_test_env(root),
        )
    existing = [
        path for path in python.get("test_paths", ["tests", "test"]) if (root / path).exists()
    ]
    if not existing:
        return None
    return (
        [
            _tool(root, "pytest", "python"),
            "--collect-only",
            "-q",
            "--strict-config",
            "--strict-markers",
            *existing,
        ],
        600,
        _python_test_env(root),
    )


def _javascript_collection_spec(root: Path, project: dict[str, Any]) -> CommandSpec | None:
    javascript = project.get("javascript", {})
    custom = javascript.get("collect_command")
    if isinstance(custom, list) and custom:
        command = _expand_project_command(root, [str(value) for value in custom])
    elif javascript.get("test_runner") == "vitest":
        command = [
            _tool(root, "vitest", "js"),
            "list",
            "--config",
            "quality/tools/js/config/vitest.config.mjs",
        ]
    else:
        return None
    return command, 600, {"CI": "1", "TZ": "UTC"}


def _collection_specs(root: Path, project: dict[str, Any]) -> list[CommandSpec]:
    candidates: list[CommandSpec | None] = []
    if project["stacks"].get("python"):
        candidates.append(_python_collection_spec(root, project))
    if project["stacks"].get("javascript"):
        candidates.append(_javascript_collection_spec(root, project))
    return [spec for spec in candidates if spec is not None]


def _test_integrity(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    scan = scan_test_integrity(root, project)
    command_code, results = _run_many(root, _collection_specs(root, project))
    code = max(command_code, QUALITY_FAILURE if scan["errors"] else PASS)
    return _write_report(
        root,
        "test_integrity",
        code,
        {"applicability": "applicable", "integrity": scan, "commands": results},
    )


def _javascript_unit_spec(root: Path, project: dict[str, Any]) -> CommandSpec:
    command = project.get("javascript", {}).get("unit_command")
    argv = (
        _expand_project_command(root, [str(value) for value in command])
        if isinstance(command, list) and command
        else [
            _tool(root, "vitest", "js"),
            "run",
            "--config",
            "quality/tools/js/config/vitest.config.mjs",
        ]
    )
    return argv, 1800, {"CI": "1", "TZ": "UTC", "FORCE_COLOR": "0"}


def _python_unit_spec(root: Path, project: dict[str, Any]) -> CommandSpec:
    custom = project.get("python", {}).get("unit_command")
    if isinstance(custom, list) and custom:
        argv = _expand_project_command(root, [str(value) for value in custom])
    else:
        existing = [
            path
            for path in project.get("python", {}).get("test_paths", ["tests", "test"])
            if (root / path).exists()
        ]
        argv = [
            _tool(root, "pytest", "python"),
            "--strict-config",
            "--strict-markers",
            "-ra",
            "--timeout=120",
            *existing,
        ]
    return argv, 1800, _python_test_env(root, timezone=True)


def _unit(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    commands: list[CommandSpec] = []
    if project["stacks"].get("javascript"):
        commands.append(_javascript_unit_spec(root, project))
    if project["stacks"].get("python"):
        commands.append(_python_unit_spec(root, project))
    code, results = _run_many(root, commands)
    return _write_report(root, "unit", code, {"applicability": "applicable", "commands": results})


def _radon_blocks(payload: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    for filename, blocks in payload.items():
        for block in blocks:
            if block.get("type") == "class":
                for method in block.get("methods", []):
                    yield filename, method
            elif block.get("type") in {"function", "method"}:
                yield filename, block


def _function_nesting(node: ast.AST, depth: int = 0) -> int:
    nesting_nodes = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Try,
        ast.With,
        ast.AsyncWith,
        ast.Match,
    )
    maximum = depth
    for child in ast.iter_child_nodes(node):
        if (
            isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
            and child is not node
        ):
            continue
        child_depth = depth + 1 if isinstance(child, nesting_nodes) else depth
        maximum = max(maximum, _function_nesting(child, child_depth))
    return maximum


def _python_ast_metrics(root: Path, files: list[str]) -> dict[tuple[str, int], dict[str, int]]:
    metrics: dict[tuple[str, int], dict[str, int]] = {}
    for filename in files:
        try:
            tree = ast.parse((root / filename).read_text(encoding="utf-8"), filename=filename)
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            end = int(getattr(node, "end_lineno", node.lineno))
            metrics[(filename, int(node.lineno))] = {
                "lines": end - int(node.lineno) + 1,
                "nesting": _function_nesting(node),
            }
    return metrics


def _python_structure_evidence(
    root: Path, project: dict[str, Any], files: list[str], payload: dict[str, Any]
) -> dict[str, Any]:
    limits = _effective_thresholds(project)["structure"]
    changed = _changed_lines(root, project) if _adopt_mode(project) else {}
    ast_metrics = _python_ast_metrics(root, files)
    functions: list[dict[str, Any]] = []
    failures: list[str] = []
    for filename, block in _radon_blocks(payload):
        start = int(block.get("lineno", 0))
        end = int(block.get("endline", start))
        enforced = not _adopt_mode(project) or bool(
            changed.get(filename, set()) & set(range(start, end + 1))
        )
        structural = ast_metrics.get((filename, start), {"lines": end - start + 1, "nesting": 0})
        item = {
            "path": filename,
            "name": block.get("name"),
            "line": start,
            "end_line": end,
            "complexity": int(block.get("complexity", 1)),
            "lines": structural["lines"],
            "nesting": structural["nesting"],
            "enforced": enforced,
        }
        functions.append(item)
        if not enforced:
            continue
        for metric, threshold in (
            ("complexity", "max_cyclomatic_complexity"),
            ("lines", "max_function_lines"),
            ("nesting", "max_nesting_depth"),
        ):
            if item[metric] > limits[threshold]:
                failures.append(
                    f"{filename}:{start} {block.get('name')} {metric} "
                    f"{item[metric]} > {limits[threshold]}"
                )
    return {
        "functions": sorted(
            functions, key=lambda item: (item["complexity"], item["lines"]), reverse=True
        ),
        "failures": failures,
        "limits": limits,
        "scope": "changed-functions" if _adopt_mode(project) else "full",
    }


def _javascript_structure_commands(root: Path, files: list[str]) -> list[CommandSpec]:
    if not files:
        return []
    eslint = _tool(root, "eslint", "js")
    return [
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
        for group in _chunks(files)
    ]


def _python_structure_analysis(
    root: Path, project: dict[str, Any], files: list[str]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not files:
        return None, None
    result = run_command(
        [_tool(root, "radon", "python"), "cc", "-j", "-s", *files], cwd=root, timeout=900
    )
    if result.code != 0:
        return result.as_dict(), None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.as_dict(), None
    return result.as_dict(), _python_structure_evidence(root, project, files, payload)


def _structure(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    js_files = (
        _scoped_files(root, project, _relative_files(root, JS_SUFFIXES, project, tests=False))
        if project["stacks"].get("javascript")
        else []
    )
    py_files = (
        _scoped_files(root, project, _relative_files(root, PY_SUFFIXES, project, tests=False))
        if project["stacks"].get("python")
        else []
    )
    code, results = _run_many(root, _javascript_structure_commands(root, js_files))
    radon, python_evidence = _python_structure_analysis(root, project, py_files)
    if radon:
        results.append(radon)
        code = max(code, PASS if radon["code"] == 0 else INFRASTRUCTURE_ERROR)
    if python_evidence and python_evidence["failures"]:
        code = max(code, QUALITY_FAILURE)
    return _write_report(
        root,
        "structure",
        code,
        {
            "applicability": "applicable",
            "scope": "changed" if _adopt_mode(project) else "full",
            "scoped_files": {"javascript": js_files, "python": py_files},
            "commands": results,
            "python": python_evidence,
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
        if not filename.endswith(".py") or _is_test_path(filename, project):
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
        path for path in changed if path.endswith(".py") and not _is_test_path(path, project)
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
            if rel not in changed or _is_test_path(rel, project):
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
        if Path(path).suffix.lower() in JS_SUFFIXES and not _is_test_path(path, project)
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
    targets = files if files is not None else _existing_paths(root, source_paths(project))
    if not targets:
        return {"functions": [], "failures": [], "scope": "none"}
    radon = _tool(root, "radon", "python")
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
    changed = _changed_lines(root, project) if _adopt_mode(project) else {}
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
            enforced = not _adopt_mode(project) or bool(
                changed.get(filename, set()) & set(range(start, end + 1))
            )
            item = {
                "path": filename,
                "name": block.get("name"),
                "line": start,
                "end_line": end,
                "complexity": complexity_value,
                "coverage": coverage_fraction * 100,
                "crap": score,
                "enforced": enforced,
            }
            functions.append(item)
            if enforced and score > maximum:
                failures.append(
                    f"{filename}:{start} {block.get('name')} CRAP {score:.1f} > {maximum:.1f}"
                )
    functions.sort(key=lambda item: item["crap"], reverse=True)
    return {
        "functions": functions,
        "failures": failures,
        "maximum_allowed": maximum,
        "scope": "changed-functions" if _adopt_mode(project) else "full",
    }


def _command_exit_code(result: Any) -> int:
    if result.code == 0:
        return PASS
    return QUALITY_FAILURE if result.code == 1 else INFRASTRUCTURE_ERROR


def _javascript_coverage_command(root: Path, project: dict[str, Any]) -> list[str]:
    javascript = project.get("javascript", {})
    custom = javascript.get("coverage_command")
    if isinstance(custom, list) and custom:
        return _expand_project_command(root, [str(value) for value in custom])
    if javascript.get("test_runner") == "vitest":
        return [
            _tool(root, "vitest", "js"),
            "run",
            "--coverage",
            "--config",
            "quality/tools/js/config/vitest.config.mjs",
        ]
    raise ConfigurationError(
        "JavaScript coverage needs javascript.coverage_command or a Vitest test runner"
    )


def _javascript_coverage(
    root: Path, project: dict[str, Any]
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    result = run_command(
        _javascript_coverage_command(root, project),
        cwd=root,
        timeout=2400,
        env={"CI": "1", "TZ": "UTC"},
    )
    code = _command_exit_code(result)
    summary = root / ".aqg" / "work" / "coverage" / "js" / "coverage-summary.json"
    final_json = root / ".aqg" / "work" / "coverage" / "js" / "coverage-final.json"
    if result.code == 0 and summary.exists():
        metrics = _js_coverage_metrics(root, summary, final_json, project)
        if metrics["failures"]:
            code = max(code, QUALITY_FAILURE)
    else:
        metrics = {
            "failures": ["coverage command passed but coverage-summary.json was not produced"]
        }
        if result.code == 0:
            code = max(code, INFRASTRUCTURE_ERROR)
    return code, result.as_dict(), metrics


def _python_coverage_command(root: Path, project: dict[str, Any], coverage_path: Path) -> list[str]:
    tests = [
        path
        for path in project.get("python", {}).get("test_paths", ["tests", "test"])
        if (root / path).exists()
    ]
    sources = project.get("python", {}).get("source_paths", source_paths(project))
    cov_args = [argument for source in sources for argument in ("--cov", source)]
    return [
        _tool(root, "pytest", "python"),
        "--strict-config",
        "--strict-markers",
        "--cov-branch",
        *cov_args,
        f"--cov-report=json:{coverage_path}",
        "--cov-report=term-missing",
        *tests,
    ]


def _python_coverage(
    root: Path, project: dict[str, Any]
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    coverage_path = root / ".aqg" / "work" / "coverage" / "python-coverage.json"
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    environment = {
        **_python_test_env(root, timezone=True),
        "COVERAGE_FILE": str(coverage_path.parent / ".coverage"),
    }
    result = run_command(
        _python_coverage_command(root, project, coverage_path),
        cwd=root,
        timeout=2400,
        env=environment,
    )
    code = _command_exit_code(result)
    if result.code != 0 or not coverage_path.exists():
        missing_metrics: dict[str, Any] = {
            "failures": ["pytest passed but coverage JSON was not produced"]
        }
        return (
            max(code, INFRASTRUCTURE_ERROR if result.code == 0 else code),
            result.as_dict(),
            missing_metrics,
        )
    metrics: dict[str, Any] = _python_coverage_metrics(root, coverage_path, project)
    targets = _scoped_files(root, project, _relative_files(root, PY_SUFFIXES, project, tests=False))
    crap = _python_crap(root, project, coverage_path, targets)
    metrics["crap"] = crap
    if metrics["failures"] or crap["failures"]:
        code = max(code, QUALITY_FAILURE)
    return code, result.as_dict(), metrics


def _coverage(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    final = PASS
    for stack, executor in (
        ("javascript", _javascript_coverage),
        ("python", _python_coverage),
    ):
        if not project["stacks"].get(stack):
            continue
        code, command, stack_metrics = executor(root, project)
        final = max(final, code)
        commands.append(command)
        metrics[stack] = stack_metrics
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
                _python_test_env(root),
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


def _custom_acceptance_spec(root: Path, project: dict[str, Any]) -> CommandSpec | None:
    custom = project.get("acceptance_command")
    if not isinstance(custom, list) or not custom:
        return None
    return (
        _expand_project_command(root, [str(value) for value in custom]),
        2400,
        {"CI": "1", "TZ": "UTC"},
    )


def _browser_acceptance_spec(root: Path, project: dict[str, Any]) -> CommandSpec | None:
    browser_files = [
        path
        for path in _relative_files(root, {".js", ".mjs", ".ts"}, project, tests=True)
        if any(token in path.lower() for token in ("e2e", "acceptance", "aqg-browser"))
    ]
    has_web = project["stacks"].get("html") or project.get("web", {}).get("start_command")
    if not has_web or not browser_files:
        return None
    return (
        [
            _tool(root, "playwright", "js"),
            "test",
            "--config",
            "quality/tools/js/config/playwright.config.mjs",
        ],
        2400,
        {"CI": "1", "TZ": "UTC"},
    )


def _python_acceptance_spec(root: Path, project: dict[str, Any]) -> CommandSpec | None:
    if not project["stacks"].get("python"):
        return None
    tests = [
        path
        for path in _relative_files(root, {".py"}, project, tests=True)
        if "acceptance" in Path(path).name.lower() or "e2e" in path.lower()
    ]
    if not tests:
        return None
    return (
        [
            _tool(root, "pytest", "python"),
            "--strict-config",
            "--strict-markers",
            "-ra",
            *tests,
        ],
        2400,
        _python_test_env(root, timezone=True),
    )


def _acceptance(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    lint = lint_features(root)
    final = QUALITY_FAILURE if lint["errors"] else PASS
    candidates = (
        _custom_acceptance_spec(root, project),
        _browser_acceptance_spec(root, project),
        _python_acceptance_spec(root, project),
    )
    specs = [spec for spec in candidates if spec is not None]
    command_code, commands = _run_many(root, specs)
    final = max(final, command_code)
    executed = bool(specs)
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
        selected_tests = [path for path in tests if (project_copy / path).exists()]
        extra_test_roots = [
            path for path in selected_tests if Path(path).parts[0].lower() not in {"test", "tests"}
        ]
        additional_copy = [
            str(path)
            for path in project.get("python", {}).get("mutation_copy_paths", [])
            if (project_copy / str(path)).exists()
        ]
        also_copy = list(dict.fromkeys([*extra_test_roots, *additional_copy]))
        original = original.rstrip() + "\n\n[tool.mutmut]\n"
        original += "source_paths = " + json.dumps(sources) + "\n"
        original += (
            "pytest_add_cli_args_test_selection = "
            + json.dumps(["-m", "not mutation_incompatible", *selected_tests])
            + "\n"
        )
        if also_copy:
            original += "also_copy = " + json.dumps(also_copy) + "\n"
        original += "mutate_only_covered_lines = true\nmax_stack_depth = 8\non_dependency_change = 'rerun'\n"
    original = _upsert_toml_array(original, "tool.mutmut", "only_mutate", only_mutate)
    pyproject.write_text(original, encoding="utf-8")


_MUTMUT_STATUSES = (
    "caught by type check",
    "check was interrupted by user",
    "not checked",
    "no tests",
    "suspicious",
    "survived",
    "segfault",
    "skipped",
    "timeout",
    "killed",
)


def _parse_mutmut_results(text: str) -> tuple[dict[str, int], dict[str, list[str]]]:
    counts: dict[str, int] = {}
    lines: dict[str, list[str]] = {}
    statuses = "|".join(re.escape(status) for status in _MUTMUT_STATUSES)
    pattern = re.compile(rf"^\s*(?P<mutant>.+?):\s*(?P<status>{statuses})\s*$")
    for line in text.splitlines():
        match = pattern.match(line)
        if match is None:
            continue
        status = match.group("status")
        counts[status] = counts.get(status, 0) + 1
        lines.setdefault(status, []).append(line.strip())
    return counts, lines


def _classify_mutmut_results(
    status_counts: dict[str, int],
    *,
    run_code: int,
    results_code: int,
    minimum_score: float,
    maximum_survivors: int,
) -> tuple[int, dict[str, Any]]:
    killed = sum(
        status_counts.get(status, 0)
        for status in ("killed", "caught by type check", "segfault", "timeout")
    )
    survivors = status_counts.get("survived", 0) + status_counts.get("no tests", 0)
    denominator = killed + survivors
    score = round(killed * 100 / denominator, 2) if denominator else 0.0
    incomplete_statuses = (
        "check was interrupted by user",
        "not checked",
        "skipped",
        "suspicious",
    )
    incomplete = sum(status_counts.get(status, 0) for status in incomplete_statuses)
    if run_code not in {0, 1} or results_code not in {0, 1} or not status_counts or incomplete:
        code = INFRASTRUCTURE_ERROR
    elif survivors > maximum_survivors or score < minimum_score:
        code = QUALITY_FAILURE
    elif run_code == 1:
        code = INFRASTRUCTURE_ERROR
    else:
        code = PASS
    return code, {
        "killed": killed,
        "survivors": survivors,
        "mutation_score": score,
        "incomplete_mutants": incomplete,
    }


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
        [mutmut, "results", "--all"],
        cwd=work,
        timeout=300,
        env={"PYTHONPATH": python_path},
    )
    status_counts, status_lines = _parse_mutmut_results(results.stdout)
    thresholds = _effective_thresholds(project)["mutation"]
    maximum = int(thresholds.get("maximum_survivors", 0))
    minimum = float(thresholds.get("minimum_score", 0))
    code, metrics = _classify_mutmut_results(
        status_counts,
        run_code=run.code,
        results_code=results.code,
        minimum_score=minimum,
        maximum_survivors=maximum,
    )
    survivors = metrics["survivors"]
    incomplete_statuses = (
        "check was interrupted by user",
        "not checked",
        "skipped",
        "suspicious",
    )
    return code, {
        "scope": "changed",
        "mutated_files": changed,
        "run": run.as_dict(),
        "results": results.as_dict(),
        "status_counts": status_counts,
        "mutation_score": metrics["mutation_score"],
        "minimum_score": minimum,
        "survivors": survivors,
        "maximum_survivors": maximum,
        "survivor_lines": [
            *status_lines.get("survived", []),
            *status_lines.get("no tests", []),
        ][:200],
        "incomplete_mutants": metrics["incomplete_mutants"],
        "incomplete_lines": [
            line for status in incomplete_statuses for line in status_lines.get(status, [])
        ][:200],
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


def _js_mutation_scope(paths: list[str]) -> tuple[list[str], list[str]]:
    candidates: list[str] = []
    configuration: list[str] = []
    for path in paths:
        name = Path(path).name
        if (
            ".config." in name
            or path.startswith("quality/tools/")
            or path.startswith("src/aqg/templates/")
        ):
            configuration.append(path)
        else:
            candidates.append(path)
    return candidates, configuration


def _mutation_js(root: Path, project: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    changed = (
        _changed_production_files(root, project, JS_SUFFIXES)
        if _effective_thresholds(project)["mutation"].get("changed_only", True)
        else _relative_files(root, JS_SUFFIXES, project, tests=False)
    )
    changed, configuration = _js_mutation_scope(changed)
    if not changed:
        return PASS, {
            "scope": "changed",
            "mutated_files": [],
            "excluded_configuration_files": configuration,
            "reason": (
                "changed JavaScript/TypeScript files are checker or installation configuration "
                "covered by structural and disposable-project conformance"
                if configuration
                else "no changed JavaScript/TypeScript production files"
            ),
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
        (
            "unsafe-html",
            re.compile(
                r"(?i)(dangerouslySetInnerHTML|innerHTML\s*=|mark_safe\s*\()"  # AQG_REVIEWED_SECURITY
            ),
        ),
        ("disabled-tls", re.compile(r"(?i)(verify\s*=\s*false|rejectUnauthorized\s*:\s*false)")),
    ]
    findings = []
    for path in iter_files(root, JS_SUFFIXES | PY_SUFFIXES, excludes(project)):
        rel = path.relative_to(root).as_posix()
        if _is_test_path(rel, project):
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
