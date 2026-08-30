"""Adapter-facing integration for structural and built-resource budgets."""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .asset_budgets import measure_asset_budgets
from .constants import INFRASTRUCTURE_ERROR, PASS, QUALITY_FAILURE
from .errors import ConfigurationError
from .size_budgets import (
    SizeBudgetError,
    analyze_source_files,
    evaluate_measurement,
    measure_source_bytes,
)
from .util import run_command

JS_ABC_PREFIX = "AQG_ABC "
CSS_SUFFIXES = {".css", ".scss", ".sass", ".less"}


def collect_javascript_abc(
    path: str,
    message: Mapping[str, Any],
    changed: Mapping[str, set[int]],
    limits: Mapping[str, Any],
    *,
    adopt_mode: bool,
) -> tuple[dict[str, Any], str | None]:
    """Normalize one machine-readable ESLint ABC measurement."""
    measurement = _javascript_measurement(path, message)
    item = _javascript_item(path, measurement)
    lines = range(int(item["line"]), int(item["end_line"]) + 1)
    item["enforced"] = not adopt_mode or bool(changed.get(path, set()).intersection(lines))
    limit = float(limits["max_abc_score"])
    failure = None
    if item["enforced"] and float(item["abc_magnitude"]) > limit:
        failure = (
            f"{path}:{item['line']} {item['name']} ABC {item['abc_magnitude']:.6f} > {limit:g}"
        )
    return item, failure


def _javascript_measurement(path: str, message: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = str(message.get("message", ""))
    if not path or not raw.startswith(JS_ABC_PREFIX):
        raise ConfigurationError("JavaScript ABC reporter returned malformed evidence")
    try:
        value = json.loads(raw[len(JS_ABC_PREFIX) :])
    except json.JSONDecodeError as error:
        raise ConfigurationError("JavaScript ABC reporter returned invalid JSON") from error
    if not isinstance(value, Mapping):
        raise ConfigurationError("JavaScript ABC reporter returned a non-object measurement")
    return value


def _javascript_item(path: str, value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        vector = value["vector"]
        location = value["location"]
        return {
            "path": path,
            "name": str(value["function"]),
            "line": int(location["line"]),
            "end_line": int(location["end_line"]),
            "assignments": int(vector["assignments"]),
            "branches": int(vector["branches"]),
            "conditions": int(vector["conditions"]),
            "abc_magnitude": float(value["magnitude"]),
            "abc_magnitude_squared": int(value["magnitude_squared"]),
            "abc_definition": str(value["definition"]),
        }
    except (KeyError, TypeError, ValueError) as error:
        raise ConfigurationError(
            f"JavaScript ABC reporter returned invalid fields: {error}"
        ) from error


def source_budget_evidence(
    root: Path,
    project: Mapping[str, Any],
    files: Sequence[str],
    *,
    thresholds: Mapping[str, Any],
    base_ref: str,
    adopt_mode: bool,
    is_test_path: Callable[[str], bool],
) -> dict[str, Any]:
    """Measure governed files and enforce new or worsened hard failures."""
    budgets = _source_thresholds(thresholds)
    inventory = [
        {
            "path": path,
            "classifications": _source_classifications(path, is_test_path(path)),
        }
        for path in files
    ]
    try:
        evidence = analyze_source_files(root, inventory, budgets)
        for item in evidence["files"]:
            _classify_file(root, item, budgets, base_ref, adopt_mode)
    except SizeBudgetError as error:
        raise ConfigurationError(f"source-file budget measurement failed: {error}") from error
    evidence.update(
        {
            "scope": "changed-files" if adopt_mode else "full",
            "thresholds": budgets,
            "failures": _source_failures(evidence["files"]),
        }
    )
    return evidence


def _source_thresholds(limits: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    byte_limits = {
        "warning_raw_bytes": int(limits["warn_source_file_bytes"]),
        "hard_raw_bytes": int(limits["max_source_file_bytes"]),
    }
    result: dict[str, dict[str, int]] = {}
    for kind, prefix in (("production", "source"), ("css", "css"), ("test", "test")):
        result[kind] = {
            "warning_physical_lines": int(limits[f"warn_{prefix}_file_lines"]),
            "hard_physical_lines": int(limits[f"max_{prefix}_file_lines"]),
            **byte_limits,
        }
    return result


def _source_classifications(path: str, is_test: bool) -> list[str]:
    suffix = Path(path).suffix.lower()
    primary = "test" if is_test else "css" if suffix in CSS_SUFFIXES else "production"
    lowered = path.lower()
    parts = {part.lower() for part in Path(path).parts}
    classifications = [primary]
    if parts.intersection({"generated", "gen"}):
        classifications.append("generated")
    if parts.intersection({"vendor", "vendors", "third_party", "third-party"}):
        classifications.append("vendor")
    if lowered.endswith((".min.js", ".min.css")):
        classifications.append("minified")
    return classifications


def _base_source_bytes(root: Path, base_ref: str, path: str) -> bytes | None:
    revision = subprocess.run(
        ["git", "rev-parse", "--verify", f"{base_ref}^{{commit}}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if revision.returncode != 0:
        raise ConfigurationError(f"source budget comparison base does not resolve: {base_ref}")
    result = subprocess.run(
        ["git", "show", f"{base_ref}:{path}"], cwd=root, capture_output=True, check=False
    )
    return result.stdout if result.returncode == 0 else None


def _classify_file(
    root: Path,
    item: dict[str, Any],
    thresholds: Mapping[str, Mapping[str, Any]],
    base_ref: str,
    adopt_mode: bool,
) -> None:
    item["enforced"] = item["status"] == "hard_failure"
    item["debt_origin"] = "current" if item["enforced"] else None
    if not item["enforced"] or not adopt_mode:
        return
    _classify_inherited_file(root, item, thresholds, base_ref)


def _classify_inherited_file(
    root: Path,
    item: dict[str, Any],
    thresholds: Mapping[str, Mapping[str, Any]],
    base_ref: str,
) -> None:
    base_bytes = _base_source_bytes(root, base_ref, str(item["path"]))
    if base_bytes is None:
        item["debt_origin"] = "new_file"
        return
    base = measure_source_bytes(base_bytes)
    evaluated = evaluate_measurement(base, item["classifications"], thresholds)
    item["base"] = {**base, **evaluated}
    if evaluated["status"] != "hard_failure":
        item["debt_origin"] = "new_violation"
        return
    regressions = _regressed_metrics(item, item["base"])
    item["regressed_metrics"] = regressions
    item["enforced"] = bool(regressions)
    item["debt_origin"] = "regression" if regressions else "inherited_git_base"


def _regressed_metrics(current: Mapping[str, Any], base: Mapping[str, Any]) -> list[str]:
    hard = {str(item["metric"]) for item in current["breaches"] if item["level"] == "hard"}
    return [
        metric
        for metric in ("physical_lines", "raw_bytes")
        if metric in hard and int(current[metric]) > int(base[metric])
    ]


def _source_failures(files: Sequence[Mapping[str, Any]]) -> list[str]:
    failures: list[str] = []
    for item in files:
        if not item.get("enforced"):
            continue
        breaches = [
            f"{entry['metric']} {entry['value']} >= {entry['limit']}"
            for entry in item["breaches"]
            if entry["level"] == "hard"
        ]
        failures.append(f"{item['path']} exceeds source-file budget: {', '.join(breaches)}")
    return failures


def measure_resource_budget(
    root: Path, config: Mapping[str, Any], thresholds: Mapping[str, Any]
) -> tuple[int, dict[str, Any]]:
    """Build when configured, then measure explicit web artifact roots."""
    mode = str(config.get("mode", "disabled"))
    roots = config.get("roots")
    if mode == "disabled" or not isinstance(roots, list) or not roots:
        raise ConfigurationError("resource budget gate requires enabled explicit artifact roots")
    commands, fresh_after = _resource_build(root, mode, config.get("build_command"))
    if commands and commands[-1]["code"] != 0:
        return INFRASTRUCTURE_ERROR, {
            "applicability": "applicable",
            "mode": mode,
            "commands": commands,
            "failures": [f"resource build exited {commands[-1]['code']}"],
        }
    evidence = _resource_measurement(root, roots, thresholds, fresh_after)
    failures = _resource_failures(evidence["findings"])
    return (QUALITY_FAILURE if failures else PASS), _resource_payload(
        mode, commands, evidence, failures
    )


def _resource_measurement(
    root: Path,
    roots: Sequence[Any],
    thresholds: Mapping[str, Any],
    fresh_after: int | None,
) -> dict[str, Any]:
    return measure_asset_budgets(
        root,
        build_roots=[str(item) for item in roots],
        limits={key: int(value) for key, value in thresholds.items() if key != "warning_ratio"},
        warning_ratio=float(thresholds["warning_ratio"]),
        fresh_after_ns=fresh_after,
    )


def _resource_failures(findings: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        f"{item['scope']} {item['metric']} {item['observed']} > {item['limit']}"
        for item in findings
        if item["status"] == "failure"
    ]


def _resource_payload(
    mode: str,
    commands: list[dict[str, Any]],
    evidence: dict[str, Any],
    failures: list[str],
) -> dict[str, Any]:
    return {
        "applicability": "applicable",
        "mode": mode,
        "commands": commands,
        "metrics": evidence,
        "findings": evidence["findings"],
        "failures": failures,
    }


def _resource_build(
    root: Path, mode: str, configured: Any
) -> tuple[list[dict[str, Any]], int | None]:
    if mode != "build":
        return [], None
    if not isinstance(configured, list) or not configured:
        raise ConfigurationError("build-mode resource budgets require a build command")
    started = time.time_ns()
    result = run_command([str(item) for item in configured], cwd=root, timeout=1800)
    return [result.as_dict()], started
