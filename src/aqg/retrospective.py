"""Pure retrospective taxonomy and reviewed-baseline comparison."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .debt import DebtError, compare
from .retrospective_inventory import debt_inventory

SCHEMA_VERSION = 1
TAXONOMY = (
    "measured_failures",
    "blocking_failures",
    "inherited_debt",
    "regressions",
    "missing_evidence",
    "configuration_errors",
    "infrastructure_errors",
    "unknown_product_intent",
    "new_debt",
    "resolved_debt",
    "invalid_debt",
)
_MISSING = re.compile(r"\b(?:missing|absent|unavailable)\b", re.IGNORECASE)
_EXIT_BUCKET = {1: "measured_failures", 2: "configuration_errors", 3: "infrastructure_errors"}
_BASELINABLE_GATES = {"structure", "coverage", "test_integrity"}
_GATE_DEBT_CATEGORIES = {
    "structure": {"structure"},
    "coverage": {"coverage", "crap"},
    "test_integrity": {"test_integrity"},
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def _item(gate: str, category: str, code: int, message: str) -> dict[str, Any]:
    return {
        "fingerprint": f"gate:{gate}:{category}:{code}",
        "category": category,
        "exit_code": code,
        "path": gate,
        "severity": "error",
        "gate": gate,
        "message": message,
    }


def _detail_text(detail: Any) -> list[str]:
    if not isinstance(detail, Mapping):
        return []
    values = [_text(detail.get(key)) for key in ("detail_error", "error", "stderr", "reason")]
    for failure in _sequence(detail.get("failures")):
        values.append(_text(failure))
    for nested in ("python", "integrity", "crap"):
        values.extend(_detail_text(detail.get(nested)))
    for metrics in (detail.get("metrics"),):
        if isinstance(metrics, Mapping):
            for value in metrics.values():
                values.extend(_detail_text(value))
    return [value for value in values if value]


def _dedupe(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    by_fingerprint = {str(item["fingerprint"]): item for item in items}
    return [by_fingerprint[key] for key in sorted(by_fingerprint)]


def _gate_taxonomy(
    results: Sequence[Any], details: Mapping[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {
        name: []
        for name in (
            "measured_failures",
            "missing_evidence",
            "configuration_errors",
            "infrastructure_errors",
        )
    }
    for raw in results:
        if not isinstance(raw, Mapping):
            continue
        code = raw.get("exit_code")
        if isinstance(code, bool) or not isinstance(code, int) or code == 0:
            continue
        gate = _text(raw.get("gate") or raw.get("name")) or "unknown"
        evidence = [_text(raw.get(key)) for key in ("detail_error", "stderr", "stdout")]
        evidence.extend(_detail_text(details.get(gate)))
        category = (
            "missing_evidence"
            if any(_MISSING.search(value) for value in evidence if value)
            else _EXIT_BUCKET.get(code)
        )
        if category is None:
            continue
        message = next((value for value in evidence if value), _text(raw.get("status")))
        buckets[category].append(_item(gate, category, code, message or f"gate exit {code}"))
    return {name: _dedupe(items) for name, items in buckets.items()}


def _unknown_intent(traceability: Any) -> list[dict[str, Any]]:
    if not isinstance(traceability, Mapping):
        return []
    items: list[dict[str, Any]] = []
    for finding in _sequence(traceability.get("findings")):
        if not isinstance(finding, Mapping):
            continue
        path = _text(finding.get("path")) or "feature-spec"
        fingerprint = _text(finding.get("fingerprint")) or f"unmapped:{path}"
        items.append(
            {
                "fingerprint": f"unknown_product_intent:{fingerprint}",
                "category": "unknown_product_intent",
                "path": path,
                "severity": "warning",
                "message": _text(finding.get("message")) or "active intent is not mapped",
            }
        )
    return _dedupe(items)


def _detail_has_changed_coverage_failure(detail: Any) -> bool:
    if not isinstance(detail, Mapping):
        return False
    for stack in _mapping_values(detail.get("metrics")):
        for failure in _sequence(stack.get("failures")):
            if "changed" in _text(failure).lower():
                return True
    return False


def _mapping_values(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        return []
    return [item for item in value.values() if isinstance(item, Mapping)]


def _blocking_failures(
    measured: Sequence[dict[str, Any]], details: Mapping[str, Any]
) -> list[dict[str, Any]]:
    blocking: list[dict[str, Any]] = []
    for item in measured:
        gate = str(item["gate"])
        detail = details.get(gate)
        if gate not in _BASELINABLE_GATES or (
            gate == "coverage" and _detail_has_changed_coverage_failure(detail)
        ):
            blocking.append(item)
        elif gate == "test_integrity":
            integrity = detail.get("integrity") if isinstance(detail, Mapping) else None
            errors = integrity.get("errors", 0) if isinstance(integrity, Mapping) else 0
            if errors != 0:
                blocking.append(item)
    return _dedupe(blocking)


def _comparison(
    inventory: list[dict[str, Any]],
    baseline: Mapping[str, Any] | None,
    measured_categories: set[str],
) -> tuple[dict[str, list[Any]], bool]:
    empty: dict[str, list[Any]] = {
        "inherited": [],
        "resolved": [],
        "regressed": [],
        "new": [],
        "invalid": [],
    }
    if baseline is None:
        return empty, False
    result = compare(inventory, baseline)
    deferred = [
        item for item in result["resolved"] if item.get("category") not in measured_categories
    ]
    result["resolved"] = [
        item for item in result["resolved"] if item.get("category") in measured_categories
    ]
    result["inherited"] = sorted(
        [*result["inherited"], *deferred], key=lambda item: str(item.get("fingerprint", ""))
    )
    return result, True


def _record_baseline_error(gates: dict[str, list[dict[str, Any]]], error: str | None) -> None:
    if not error:
        return
    gates["configuration_errors"] = _dedupe(
        [
            *gates["configuration_errors"],
            _item("debt_baseline", "configuration_errors", 2, error),
        ]
    )


def _measured_categories(details: Mapping[str, Any]) -> set[str]:
    return {
        category
        for gate in set(details).intersection(_BASELINABLE_GATES)
        for category in _GATE_DEBT_CATEGORIES[gate]
    }


def _is_unsafe(
    gates: Mapping[str, list[dict[str, Any]]],
    comparison: Mapping[str, list[Any]],
    blocking: Sequence[dict[str, Any]],
    unknown: Sequence[dict[str, Any]],
) -> bool:
    return any(
        (
            blocking,
            comparison["regressed"],
            comparison["new"],
            comparison["invalid"],
            gates["missing_evidence"],
            gates["configuration_errors"],
            gates["infrastructure_errors"],
            unknown,
        )
    )


def _certification(reviewed: bool, unsafe: bool) -> str:
    if not reviewed:
        return "observations_only"
    return "not_regression_free" if unsafe else "regression_free"


def _report(
    inventory: list[dict[str, Any]],
    gates: Mapping[str, list[dict[str, Any]]],
    comparison: Mapping[str, list[Any]],
    blocking: list[dict[str, Any]],
    unknown: list[dict[str, Any]],
    reviewed: bool,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "certification": _certification(reviewed, _is_unsafe(gates, comparison, blocking, unknown)),
        "inventory": inventory,
        "unreviewed_debt": inventory if not reviewed else [],
        "measured_failures": gates["measured_failures"],
        "blocking_failures": blocking,
        "inherited_debt": comparison["inherited"],
        "regressions": comparison["regressed"],
        "missing_evidence": gates["missing_evidence"],
        "configuration_errors": gates["configuration_errors"],
        "infrastructure_errors": gates["infrastructure_errors"],
        "unknown_product_intent": unknown,
        "new_debt": comparison["new"],
        "resolved_debt": comparison["resolved"],
        "invalid_debt": comparison["invalid"],
    }
    report["counts"] = {name: len(report[name]) for name in (*TAXONOMY, "unreviewed_debt")}
    return report


def build_retrospective(
    gate_results: Sequence[Any],
    gate_details: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    traceability: Mapping[str, Any] | None = None,
    baseline: Mapping[str, Any] | None = None,
    baseline_error: str | None = None,
) -> dict[str, Any]:
    """Build deterministic observations and, with review, a ratchet decision."""
    if not isinstance(gate_results, Sequence) or isinstance(gate_results, (str, bytes)):
        raise DebtError("gate_results must be a sequence")
    if not isinstance(gate_details, Mapping) or not isinstance(thresholds, Mapping):
        raise DebtError("gate details and thresholds must be mappings")
    results = copy.deepcopy(list(gate_results))
    details = copy.deepcopy(dict(gate_details))
    inventory = debt_inventory(details, copy.deepcopy(dict(thresholds)))
    gates = _gate_taxonomy(results, details)
    _record_baseline_error(gates, baseline_error)
    unknown = _unknown_intent(copy.deepcopy(traceability))
    comparison, reviewed = _comparison(
        inventory, copy.deepcopy(baseline), _measured_categories(details)
    )
    blocking = _blocking_failures(gates["measured_failures"], details)
    return _report(inventory, gates, comparison, blocking, unknown, reviewed)


def ratchet_exit_code(report: Mapping[str, Any]) -> int:
    """Return the enforcing result for a report backed by reviewed authority."""
    if report.get("certification") == "observations_only":
        raise DebtError("ratchet exit requires a reviewed baseline")
    infrastructure = _sequence(report.get("infrastructure_errors"))
    if infrastructure:
        return 3
    configuration = _sequence(report.get("configuration_errors"))
    if configuration:
        return 2
    missing = _sequence(report.get("missing_evidence"))
    if missing:
        return max(
            1,
            max(
                (int(item.get("exit_code", 1)) for item in missing if isinstance(item, Mapping)),
                default=1,
            ),
        )
    if any(
        _sequence(report.get(name))
        for name in (
            "blocking_failures",
            "regressions",
            "new_debt",
            "invalid_debt",
            "unknown_product_intent",
        )
    ):
        return 1
    return 0
