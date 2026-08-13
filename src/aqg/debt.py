"""Dependency-free reviewed debt-baseline core.

Pure inventory normalization, document validation/fingerprinting, and
no-regression comparison. No CLI, filesystem, policy, or adapter wiring.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

SCHEMA_VERSION = 1
STATES = frozenset({"proposed", "reviewed"})
DIRECTIONS = frozenset({"higher_is_worse", "lower_is_worse"})
_SEVERITY_RANK = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "warning": 2,
    "high": 3,
    "error": 4,
    "critical": 5,
    "blocker": 6,
}


class DebtError(ValueError):
    """Debt baseline or inventory contract violation."""


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DebtError(f"{field} must be a non-empty string")
    return value.strip()


def _normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise DebtError("path must be repository-relative and cannot traverse parents")
    parts = tuple(part for part in candidate.parts if part not in {"", "."})
    if not parts:
        raise DebtError("path must identify a repository-relative file")
    return PurePosixPath(*parts).as_posix()


def _parse_value(value: Any) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise DebtError("value must be a finite number when present")
    return value


def _parse_item(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise DebtError("debt item must be an object")
    fingerprint = _require_text(raw.get("fingerprint"), "fingerprint")
    category = _require_text(raw.get("category"), "category")
    path = _normalize_path(_require_text(raw.get("path"), "path"))
    severity = _require_text(raw.get("severity"), "severity").lower()
    if severity not in _SEVERITY_RANK:
        raise DebtError(f"unknown severity {severity!r}")
    location = raw.get("location")
    if location is not None:
        location = _require_text(location, "location")
    value = _parse_value(raw.get("value"))
    direction = raw.get("direction")
    if value is not None:
        if direction not in DIRECTIONS:
            raise DebtError("numeric debt must declare a comparison direction")
    elif direction is not None:
        raise DebtError("direction is only valid for numeric debt")
    item: dict[str, Any] = {
        "fingerprint": fingerprint,
        "category": category,
        "path": path,
        "severity": severity,
    }
    if location is not None:
        item["location"] = location
    if value is not None:
        item["value"] = value
        item["direction"] = direction
    return item


def _item_sort_key(item: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(item["fingerprint"]),
        str(item["category"]),
        str(item["path"]),
        str(item.get("location") or ""),
        str(item["severity"]),
    )


def normalize_inventory(items: Sequence[Any]) -> list[dict[str, Any]]:
    """Return a sorted, de-duplicated inventory or raise on malformed input."""
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise DebtError("inventory must be a list of debt items")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in items:
        item = _parse_item(raw)
        fingerprint = item["fingerprint"]
        if fingerprint in seen:
            raise DebtError(f"duplicate debt fingerprint: {fingerprint}")
        seen.add(fingerprint)
        normalized.append(item)
    normalized.sort(key=_item_sort_key)
    return normalized


def _partition_inventory(items: Sequence[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize valid items and collect raw invalid entries without raising."""
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise DebtError("inventory must be a list of debt items")
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in items:
        try:
            item = _parse_item(raw)
        except DebtError as exc:
            invalid.append({"index": len(valid) + len(invalid), "error": str(exc)})
            continue
        fingerprint = item["fingerprint"]
        if fingerprint in seen:
            invalid.append(
                {"index": len(valid) + len(invalid), "error": "duplicate debt fingerprint"}
            )
            continue
        seen.add(fingerprint)
        valid.append(item)
    valid.sort(key=_item_sort_key)
    return valid, invalid


def _timestamp(value: Any, field: str) -> str:
    text = _require_text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DebtError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise DebtError(f"{field} must include a timezone")
    return text


def _measurement(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise DebtError("measurement must be an object")
    return {
        "run_id": _require_text(value.get("run_id"), "measurement.run_id"),
        "profile": _require_text(value.get("profile"), "measurement.profile"),
        "measured_at": _timestamp(value.get("measured_at"), "measurement.measured_at"),
        "change_fingerprint": _require_text(
            value.get("change_fingerprint"), "measurement.change_fingerprint"
        ),
        "manifest_fingerprint": _require_text(
            value.get("manifest_fingerprint"), "measurement.manifest_fingerprint"
        ),
    }


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise DebtError(f"{field} must be a non-empty array")
    items = [_require_text(item, f"{field} item") for item in value]
    if len(items) != len(set(items)) or items != sorted(items):
        raise DebtError(f"{field} must be sorted and unique")
    return items


def _sha256(value: Any, field: str) -> str:
    text = _require_text(value, field)
    if len(text) != 71 or not text.startswith("sha256:"):
        raise DebtError(f"{field} must be a sha256 fingerprint")
    try:
        int(text[7:], 16)
    except ValueError as exc:
        raise DebtError(f"{field} must be a sha256 fingerprint") from exc
    return text


def _authority_scope(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise DebtError("review_authority.scope must be an object")
    expected = {"revision", "base_revision", "change_fingerprint", "control_fingerprint"}
    if set(value) != expected:
        raise DebtError("review_authority.scope must contain exact candidate identity fields")
    return {
        "revision": _require_text(value.get("revision"), "review_authority.scope.revision"),
        "base_revision": _require_text(
            value.get("base_revision"), "review_authority.scope.base_revision"
        ),
        "change_fingerprint": _sha256(
            value.get("change_fingerprint"), "review_authority.scope.change_fingerprint"
        ),
        "control_fingerprint": _sha256(
            value.get("control_fingerprint"), "review_authority.scope.control_fingerprint"
        ),
    }


def _review_authority(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DebtError("review_authority must be an object")
    expected = {
        "kind",
        "run_id",
        "tier",
        "manifest_sha256",
        "report_sha256",
        "provider_groups",
        "covered_roles",
        "scope",
    }
    if set(value) != expected:
        raise DebtError("review_authority fields are incomplete or unknown")
    if value.get("kind") != "agent_council" or value.get("tier") != "high":
        raise DebtError("review_authority must identify a high-tier agent council")
    return {
        "kind": "agent_council",
        "run_id": _require_text(value.get("run_id"), "review_authority.run_id"),
        "tier": "high",
        "manifest_sha256": _sha256(
            value.get("manifest_sha256"), "review_authority.manifest_sha256"
        ),
        "report_sha256": _sha256(value.get("report_sha256"), "review_authority.report_sha256"),
        "provider_groups": _string_list(
            value.get("provider_groups"), "review_authority.provider_groups"
        ),
        "covered_roles": _string_list(value.get("covered_roles"), "review_authority.covered_roles"),
        "scope": _authority_scope(value.get("scope")),
    }


def _review_fields(document: Mapping[str, Any], state: str) -> dict[str, Any]:
    reviewer = document.get("reviewer")
    reviewed_at = document.get("reviewed_at")
    authority = document.get("review_authority")
    if state == "proposed":
        if reviewer is not None or reviewed_at is not None or authority is not None:
            raise DebtError("proposed baseline cannot contain review authority fields")
        return {}
    result: dict[str, Any] = {"reviewed_at": _timestamp(reviewed_at, "reviewed_at")}
    if authority is None:
        result["reviewer"] = _require_text(reviewer, "reviewer")
    else:
        if reviewer is not None:
            raise DebtError("council-reviewed baseline must not claim a human reviewer")
        result["review_authority"] = _review_authority(authority)
    return result


def validate_baseline(document: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize a proposed or reviewed baseline document."""
    if not isinstance(document, Mapping):
        raise DebtError("baseline must be an object")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise DebtError("schema_version must be 1")
    state = document.get("state")
    if state not in STATES:
        raise DebtError("state must be 'proposed' or 'reviewed'")
    inventory = normalize_inventory(document.get("inventory", []))
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "state": state,
        "source_revision": _require_text(document.get("source_revision"), "source_revision"),
        "policy_fingerprint": _require_text(
            document.get("policy_fingerprint"), "policy_fingerprint"
        ),
        "control_fingerprint": _require_text(
            document.get("control_fingerprint"), "control_fingerprint"
        ),
        "created_at": _timestamp(document.get("created_at"), "created_at"),
        "measurement": _measurement(document.get("measurement")),
        "inventory": inventory,
    }
    result.update(_review_fields(document, state))
    return result


def document_fingerprint(document: Mapping[str, Any]) -> str:
    """Return a deterministic content fingerprint for a valid baseline document."""
    digest = hashlib.sha256(_canonical(validate_baseline(document)).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _worsened(current: Mapping[str, Any], prior: Mapping[str, Any]) -> bool:
    if _SEVERITY_RANK[str(current["severity"])] > _SEVERITY_RANK[str(prior["severity"])]:
        return True
    current_value = current.get("value")
    prior_value = prior.get("value")
    if current_value is None or prior_value is None:
        return False
    if current["direction"] == "higher_is_worse":
        return float(current_value) > float(prior_value)
    return float(current_value) < float(prior_value)


def _same_identity(current: Mapping[str, Any], prior: Mapping[str, Any]) -> bool:
    fields = ("category", "path", "location", "direction")
    return all(current.get(field) == prior.get(field) for field in fields)


def compare(
    current_inventory: Sequence[Any],
    reviewed_baseline: Mapping[str, Any],
) -> dict[str, list[Any]]:
    """Compare current debt against an explicitly reviewed baseline.

    Rejects non-reviewed or invalid baselines. Classifies each valid current item
    as inherited, regressed, or new; baseline-only items as resolved; and
    malformed current entries as invalid.
    """
    baseline = validate_baseline(reviewed_baseline)
    if baseline["state"] != "reviewed":
        raise DebtError("only a reviewed baseline may authorize comparison")
    current, invalid = _partition_inventory(current_inventory)
    prior_by_fp = {item["fingerprint"]: item for item in baseline["inventory"]}
    inherited: list[dict[str, Any]] = []
    regressed: list[dict[str, Any]] = []
    new: list[dict[str, Any]] = []
    for item in current:
        prior = prior_by_fp.get(item["fingerprint"])
        if prior is None:
            new.append(item)
        elif not _same_identity(item, prior):
            invalid.append(
                {
                    "fingerprint": item["fingerprint"],
                    "error": "fingerprint identity fields changed",
                }
            )
        elif _worsened(item, prior):
            regressed.append(item)
        else:
            inherited.append(item)
    current_fps = {item["fingerprint"] for item in current}
    resolved = [item for item in baseline["inventory"] if item["fingerprint"] not in current_fps]
    inherited.sort(key=_item_sort_key)
    regressed.sort(key=_item_sort_key)
    new.sort(key=_item_sort_key)
    resolved.sort(key=_item_sort_key)
    return {
        "inherited": inherited,
        "resolved": resolved,
        "regressed": regressed,
        "new": new,
        "invalid": invalid,
    }
