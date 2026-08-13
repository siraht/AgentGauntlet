"""Normalize baseline-eligible debt from detailed gate reports."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from .debt import DebtError, normalize_inventory

_STRUCTURE_METRICS = (
    ("complexity", "max_cyclomatic_complexity"),
    ("lines", "max_function_lines"),
    ("nesting", "max_nesting_depth"),
)
_COVERAGE_METRICS = ("lines", "branches", "functions", "statements")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        raise DebtError("retrospective metric must be finite")
    return value


def _location(value: Any) -> str | None:
    return f"line:{value}" if isinstance(value, int) and not isinstance(value, bool) else None


def _metric_item(
    *,
    fingerprint: str,
    category: str,
    path: str,
    value: int | float,
    direction: str,
    location: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "fingerprint": fingerprint,
        "category": category,
        "path": path,
        "severity": "medium",
        "value": value,
        "direction": direction,
    }
    if location:
        item["location"] = location
    return item


def _structure_reports(detail: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    reports = [
        report
        for report in (_mapping(detail.get("javascript")), _mapping(detail.get("python")))
        if report
    ]
    return reports or [detail]


def _function_structure_items(
    function: Mapping[str, Any], limits: Mapping[str, Any]
) -> list[dict[str, Any]]:
    path = _text(function.get("path"))
    name = _text(function.get("name")) or "<anonymous>"
    if not path:
        return []
    items: list[dict[str, Any]] = []
    for metric, limit_name in _STRUCTURE_METRICS:
        value = _number(function.get(metric))
        limit = _number(limits.get(limit_name))
        if value is None or limit is None or value <= limit:
            continue
        items.append(
            _metric_item(
                fingerprint=f"structure:{metric}:{path}:{name}",
                category="structure",
                path=path,
                value=value,
                direction="higher_is_worse",
                location=_location(function.get("line")),
            )
        )
    return items


def _structure_inventory(
    detail: Mapping[str, Any], thresholds: Mapping[str, Any]
) -> list[dict[str, Any]]:
    limits = _mapping(thresholds.get("structure"))
    items: list[dict[str, Any]] = []
    for report in _structure_reports(detail):
        for function in _sequence(report.get("functions")):
            if not isinstance(function, Mapping):
                continue
            if report.get("scope") == "changed-functions" and function.get("enforced") is False:
                continue
            items.extend(_function_structure_items(function, limits))
    return items


def _crap_function_item(function: Mapping[str, Any], limit: int | float) -> dict[str, Any] | None:
    path = _text(function.get("path"))
    name = _text(function.get("name")) or "<anonymous>"
    value = _number(function.get("crap"))
    if not path or value is None or value <= limit:
        return None
    return _metric_item(
        fingerprint=f"crap:{path}:{name}",
        category="crap",
        path=path,
        value=value,
        direction="higher_is_worse",
        location=_location(function.get("line")),
    )


def _crap_inventory(
    report: Mapping[str, Any], thresholds: Mapping[str, Any]
) -> list[dict[str, Any]]:
    limit = _number(_mapping(thresholds.get("structure")).get("max_crap"))
    if limit is None:
        limit = _number(report.get("maximum_allowed"))
    if limit is None:
        return []
    items: list[dict[str, Any]] = []
    for function in _sequence(report.get("functions")):
        if not isinstance(function, Mapping):
            continue
        if report.get("scope") == "changed-functions" and function.get("enforced") is False:
            continue
        item = _crap_function_item(function, limit)
        if item:
            items.append(item)
    return items


def _coverage_inventory(
    detail: Mapping[str, Any], thresholds: Mapping[str, Any]
) -> list[dict[str, Any]]:
    limits = _mapping(thresholds.get("coverage"))
    items: list[dict[str, Any]] = []
    for stack, raw_metrics in _mapping(detail.get("metrics")).items():
        if not isinstance(raw_metrics, Mapping):
            continue
        stack_name = str(stack)
        for metric in _COVERAGE_METRICS:
            value = _number(raw_metrics.get(metric))
            limit = _number(limits.get(metric))
            if value is None or limit is None or value >= limit:
                continue
            items.append(
                _metric_item(
                    fingerprint=f"coverage:{stack_name}:{metric}",
                    category="coverage",
                    path=stack_name,
                    value=value,
                    direction="lower_is_worse",
                )
            )
        crap = raw_metrics.get("crap")
        if isinstance(crap, Mapping):
            items.extend(_crap_inventory(crap, thresholds))
    return items


def _integrity_fingerprint(finding: Mapping[str, Any], code: str, path: str) -> str:
    raw = _text(finding.get("fingerprint"))
    prefix = f"{code}:{path}:"
    marker = raw[len(prefix) :] if raw.startswith(prefix) else raw
    if marker and marker.split(":", 1)[0].isdigit():
        pieces = marker.split(":", 1)
        marker = pieces[1] if len(pieces) == 2 else marker
    return f"test_integrity:{code}:{path}" + (f":{marker}" if marker else "")


def _integrity_inventory(detail: Mapping[str, Any]) -> list[dict[str, Any]]:
    report = _mapping(detail.get("integrity")) or detail
    items: list[dict[str, Any]] = []
    for finding in _sequence(report.get("findings")):
        if not isinstance(finding, Mapping):
            continue
        severity = _text(finding.get("severity")).lower()
        if severity not in {"warning", "baseline"}:
            continue
        code = _text(finding.get("code")) or "finding"
        path = _text(finding.get("path")) or "tests"
        item: dict[str, Any] = {
            "fingerprint": _integrity_fingerprint(finding, code, path),
            "category": "test_integrity",
            "path": path,
            "severity": "warning" if severity == "warning" else "low",
        }
        location = _location(finding.get("line"))
        if location:
            item["location"] = location
        items.append(item)
    return items


def _unique(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    by_fingerprint: dict[str, dict[str, Any]] = {}
    for item in items:
        fingerprint = str(item["fingerprint"])
        prior = by_fingerprint.get(fingerprint)
        if prior is not None and prior != item:
            raise DebtError(f"ambiguous retrospective debt fingerprint: {fingerprint}")
        by_fingerprint[fingerprint] = item
    return list(by_fingerprint.values())


def debt_inventory(
    gate_details: Mapping[str, Any], thresholds: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Return deterministic baseline-eligible whole-tree debt.

    Security, secrets, mutation, review, missing evidence, and changed-line
    failures are intentionally not baseline eligible.
    """
    if not isinstance(gate_details, Mapping) or not isinstance(thresholds, Mapping):
        raise DebtError("gate details and thresholds must be mappings")
    items: list[dict[str, Any]] = []
    for gate_name, detail in gate_details.items():
        if not isinstance(detail, Mapping):
            continue
        identified = _text(detail.get("gate"))
        if gate_name == "structure" or identified == "structure":
            items.extend(_structure_inventory(detail, thresholds))
        elif gate_name == "coverage" or identified == "coverage":
            items.extend(_coverage_inventory(detail, thresholds))
        elif gate_name == "test_integrity" or identified == "test_integrity":
            items.extend(_integrity_inventory(detail))
    return normalize_inventory(_unique(items))
