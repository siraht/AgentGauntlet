"""Normalize deterministic JavaScript and TypeScript structure evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .budget_integration import collect_javascript_abc

_COMPLEXITY = re.compile(
    r"^(?:Arrow function|Function '(?P<name>[^']+)') has a complexity of (?P<value>\d+)\."
)


def javascript_structure_evidence(
    root: Path,
    results: list[dict[str, Any]],
    limits: dict[str, Any],
    changed: dict[str, set[int]],
    *,
    adopt_mode: bool,
) -> tuple[dict[str, Any], list[str]]:
    """Normalize ESLint reports while retaining content-addressed provenance."""
    functions: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    failures: list[str] = []
    parse_errors: list[str] = []
    for result in results:
        reports = _parse_result(result, parse_errors)
        if reports is not None:
            _collect_reports(
                root, reports, changed, limits, adopt_mode, functions, findings, failures
            )
    return _evidence(functions, findings, failures, limits, adopt_mode), parse_errors


def _parse_result(result: dict[str, Any], parse_errors: list[str]) -> list[Any] | None:
    raw = str(result.get("stdout", ""))
    result["stdout_bytes"] = len(raw.encode())
    result["stdout_sha256"] = "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
    result["stdout"] = ""
    try:
        reports = json.loads(raw)
    except json.JSONDecodeError:
        parse_errors.append("ESLint structure output was not valid JSON")
        return None
    if not isinstance(reports, list):
        parse_errors.append("ESLint structure output was not an array")
        return None
    return reports


def _collect_reports(
    root: Path,
    reports: list[Any],
    changed: dict[str, set[int]],
    limits: dict[str, Any],
    adopt_mode: bool,
    functions: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    failures: list[str],
) -> None:
    for report in reports:
        if not isinstance(report, Mapping):
            continue
        path = _relative_path(root, report.get("filePath"))
        for message in report.get("messages", []):
            if isinstance(message, Mapping):
                _collect_message(
                    path,
                    dict(message),
                    changed,
                    limits,
                    adopt_mode,
                    functions,
                    findings,
                    failures,
                )


def _collect_message(
    path: str,
    message: dict[str, Any],
    changed: dict[str, set[int]],
    limits: dict[str, Any],
    adopt_mode: bool,
    functions: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    failures: list[str],
) -> None:
    findings.append(_finding(path, message))
    item: dict[str, Any] | None
    if message.get("ruleId") == "aqg-abc/report":
        item, failure = collect_javascript_abc(
            path, message, changed, limits, adopt_mode=adopt_mode
        )
    else:
        item = _complexity_item(path, message, changed, adopt_mode)
        failure = _complexity_failure(item, limits)
    if item is not None:
        functions.append(item)
    if failure:
        failures.append(failure)


def _finding(path: str, message: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("ruleId", "severity", "message", "line", "column", "endLine", "endColumn")
    return {**{key: message.get(key) for key in keys}, "path": path}


def _complexity_item(
    path: str, message: Mapping[str, Any], changed: dict[str, set[int]], adopt_mode: bool
) -> dict[str, Any] | None:
    match = _complexity_match(message)
    if match is None or not path:
        return None
    line, end_line, column = _message_location(message)
    return {
        "path": path,
        "name": match.group("name") or f"<arrow@{line}:{column}>",
        "line": line,
        "complexity": int(match.group("value")),
        "enforced": _function_enforced(path, changed, adopt_mode, line, end_line),
    }


def _complexity_match(message: Mapping[str, Any]) -> re.Match[str] | None:
    if message.get("ruleId") != "complexity":
        return None
    return _COMPLEXITY.match(str(message.get("message", "")))


def _message_location(message: Mapping[str, Any]) -> tuple[int, int, int]:
    line = int(message.get("line", 0))
    return line, int(message.get("endLine") or line), int(message.get("column", 0))


def _function_enforced(
    path: str,
    changed: dict[str, set[int]],
    adopt_mode: bool,
    line: int,
    end_line: int,
) -> bool:
    return not adopt_mode or bool(changed.get(path, set()).intersection(range(line, end_line + 1)))


def _complexity_failure(item: Mapping[str, Any] | None, limits: Mapping[str, Any]) -> str | None:
    if item is None or not item["enforced"]:
        return None
    limit = int(limits["max_cyclomatic_complexity"])
    if int(item["complexity"]) <= limit:
        return None
    return f"{item['path']}:{item['line']} {item['name']} complexity {item['complexity']} > {limit}"


def _relative_path(root: Path, value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    try:
        return Path(value).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return ""


def _evidence(
    functions: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    failures: list[str],
    limits: Mapping[str, Any],
    adopt_mode: bool,
) -> dict[str, Any]:
    return {
        "functions": sorted(functions, key=lambda item: (item["path"], item["line"])),
        "findings": sorted(findings, key=lambda item: (item["path"], item["line"])),
        "failures": failures,
        "limits": dict(limits),
        "scope": "changed-functions" if adopt_mode else "full",
    }
