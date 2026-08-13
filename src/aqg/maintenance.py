"""Exact-scope policy maintenance with deterministic no-weakening checks."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

from .approvals import approval_path, validate_approval
from .constants import CONFIGURATION_ERROR, PASS, QUALITY_FAILURE, RISK_ORDER
from .errors import ConfigurationError
from .evidence_manifest import validate_run_id, write_evidence_json
from .policy import load_policy, policy_override_enabled, protected_patterns
from .project import load_project
from .util import (
    change_fingerprint,
    control_fingerprint,
    git_changed_files,
    git_output,
    git_revision,
    matches_any,
    read_json,
    utc_now,
)

OPERATIONS = frozenset({"add", "modify", "delete", "rename_from", "rename_to", "type_change"})
_STATUS_OPERATION = {
    "A": "add",
    "M": "modify",
    "D": "delete",
    "T": "type_change",
}


def _path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError("maintenance change path must be a non-empty string")
    candidate = PurePosixPath(value.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ConfigurationError("maintenance change path must be repository-relative")
    normalized = PurePosixPath(*(part for part in candidate.parts if part not in {"", "."}))
    if not normalized.parts:
        raise ConfigurationError("maintenance change path must identify a file")
    return normalized.as_posix()


def _change(path: Any, operation: Any) -> dict[str, str]:
    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise ConfigurationError(f"unsupported policy-maintenance operation {operation!r}")
    return {"path": _path(path), "operation": operation}


def parse_change_spec(value: str) -> dict[str, str]:
    """Parse one OPERATION:PATH command-line declaration."""
    operation, separator, path = value.partition(":")
    if not separator:
        raise ConfigurationError(
            "maintenance change must use OPERATION:PATH, for example modify:quality/policy.toml"
        )
    return _change(path, operation)


def _validate_requested_changes(
    changes: list[dict[str, str]], policy: dict[str, Any]
) -> list[dict[str, str]]:
    if not changes:
        raise ConfigurationError("maintenance request needs at least one declared change")
    normalized = sorted(
        (_change(item.get("path"), item.get("operation")) for item in changes),
        key=lambda item: (item["path"], item["operation"]),
    )
    if len({(item["path"], item["operation"]) for item in normalized}) != len(normalized):
        raise ConfigurationError("maintenance request contains a duplicate change")
    patterns = protected_patterns(policy)
    for item in normalized:
        if not matches_any(item["path"], patterns):
            raise ConfigurationError(f"{item['path']} is not a protected policy path")
        if matches_any(item["path"], ["quality/approvals/**"]):
            raise ConfigurationError("approval evidence cannot self-authorize local maintenance")
    return normalized


def create_maintenance_request(
    root: Path,
    changes: list[dict[str, str]],
    *,
    reason: str,
    requester: str | None = None,
) -> dict[str, Any]:
    """Write a non-authorizing, path-and-operation-scoped local edit request."""
    if not reason.strip():
        raise ConfigurationError("maintenance request reason must not be blank")
    policy = load_policy(root)
    normalized = _validate_requested_changes(changes, policy)
    base = str(load_project(root).get("enforcement", {}).get("base_ref", "HEAD"))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "state": "proposed",
        "created_at": utc_now(),
        "requester": requester or getpass.getuser(),
        "reason": reason.strip(),
        "source_revision": git_revision(root),
        "base_ref": base,
        "change_fingerprint": change_fingerprint(root, base),
        "control_fingerprint": control_fingerprint(root),
        "authorized_changes": normalized,
        "authority": "none",
    }
    identity = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    request_id = f"maintenance-{identity}"
    path = root / ".aqg" / "proposals" / "maintenance" / f"{request_id}.json"
    write_evidence_json(path, payload)
    return {"request_id": request_id, "path": str(path), "request": payload}


def load_maintenance_request(root: Path, request_id: str) -> dict[str, Any]:
    """Load and validate a local edit request without treating it as approval."""
    request_id = validate_run_id(request_id)
    path = root / ".aqg" / "proposals" / "maintenance" / f"{request_id}.json"
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"cannot read maintenance request {request_id}: {exc}") from exc
    _validate_request_identity(payload, request_id)
    _validate_request_ancestry(root, payload)
    raw = payload.get("authorized_changes")
    if not isinstance(raw, list):
        raise ConfigurationError("maintenance request authorized_changes must be an array")
    policy = load_policy(root)
    payload["authorized_changes"] = _validate_requested_changes(raw, policy)
    payload["request_id"] = request_id
    return dict(payload)


def _validate_request_identity(payload: Any, request_id: str) -> None:
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ConfigurationError(f"invalid maintenance request {request_id}")
    if payload.get("state") != "proposed" or payload.get("authority") != "none":
        raise ConfigurationError("maintenance request must be non-authorizing proposed state")
    if not str(payload.get("reason") or "").strip():
        raise ConfigurationError("maintenance request reason must not be blank")


def _validate_request_ancestry(root: Path, payload: dict[str, Any]) -> None:
    source_revision = payload.get("source_revision")
    if not isinstance(source_revision, str) or not source_revision:
        raise ConfigurationError("maintenance request source_revision must be a commit")
    code, _, _ = git_output(root, ["merge-base", "--is-ancestor", source_revision, "HEAD"])
    if code != 0:
        raise ConfigurationError(
            "maintenance request source revision is not an ancestor of the candidate"
        )


def require_local_maintenance_change(root: Path, path: str, operation: str) -> dict[str, Any]:
    """Require the advisory local override and an exact scoped request."""
    policy = load_policy(root)
    if not policy_override_enabled(policy):
        raise ConfigurationError(
            "protected write requires AQG_POLICY_MAINTENANCE=1 and a scoped request"
        )
    request_env = str(
        policy.get("policy", {}).get(
            "maintenance_request_env",
            "AQG_MAINTENANCE_REQUEST",
        )
    )
    request_id = os.environ.get(request_env, "")
    if not request_id:
        raise ConfigurationError(f"protected write requires {request_env}")
    request = load_maintenance_request(root, request_id)
    expected = _change(path, operation)
    if expected not in request["authorized_changes"]:
        raise ConfigurationError(f"{operation}:{path} is outside maintenance request {request_id}")
    return request


def _status_changes(root: Path, base: str) -> list[dict[str, str]]:
    code, stdout, stderr = git_output(root, ["diff", "--name-status", "--find-renames", base, "--"])
    if code != 0:
        raise ConfigurationError(
            f"cannot resolve policy-maintenance comparison ref {base!r}: {stderr.strip()}"
        )
    changes: list[dict[str, str]] = []
    tracked: set[str] = set()
    for line in stdout.splitlines():
        line_changes = _parse_status_line(line)
        changes.extend(line_changes)
        tracked.update(item["path"] for item in line_changes)
    for path in git_changed_files(root, base, include_worktree=True):
        normalized = _path(path)
        if normalized not in tracked and (root / normalized).is_file():
            changes.append(_change(normalized, "add"))
    return changes


def _parse_status_line(line: str) -> list[dict[str, str]]:
    fields = line.split("\t")
    if len(fields) < 2:
        return []
    kind = fields[0][:1]
    if kind == "R" and len(fields) >= 3:
        return [
            _change(fields[1], "rename_from"),
            _change(fields[2], "rename_to"),
        ]
    return [_change(fields[-1], _STATUS_OPERATION.get(kind, "modify"))]


def protected_changes(root: Path, policy: dict[str, Any], base: str) -> list[dict[str, str]]:
    """Return exact policy-plane changes, excluding approval evidence itself."""
    patterns = protected_patterns(policy)
    by_identity = {
        (item["path"], item["operation"]): item
        for item in _status_changes(root, base)
        if matches_any(item["path"], patterns)
        and not matches_any(item["path"], ["quality/approvals/**"])
    }
    return [by_identity[key] for key in sorted(by_identity)]


def _base_bytes(root: Path, base: str, path: str) -> bytes | None:
    code, stdout, _ = git_output(root, ["show", f"{base}:{path}"])
    return stdout.encode() if code == 0 else None


def _candidate_bytes(root: Path, path: str) -> bytes | None:
    candidate = root / path
    return candidate.read_bytes() if candidate.is_file() else None


def _changed_keys(before: Any, after: Any, prefix: str = "") -> list[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        keys = sorted(set(before) | set(after))
        changed: list[str] = []
        for key in keys:
            name = f"{prefix}.{key}" if prefix else str(key)
            if key not in before or key not in after:
                changed.append(name)
            else:
                changed.extend(_changed_keys(before[key], after[key], name))
        return changed
    return [] if before == after else [prefix]


def _set_direction(before: Any, after: Any) -> str:
    if not isinstance(before, list) or not isinstance(after, list):
        return "unknown"
    old, new = {str(item) for item in before}, {str(item) for item in after}
    if old == new:
        return "neutral"
    if old <= new:
        return "strengthening"
    return "weakening"


def _profile_direction(before: Any, after: Any, order: list[str]) -> str:
    if before not in order or after not in order:
        return "unknown"
    if order.index(str(after)) < order.index(str(before)):
        return "weakening"
    return "neutral" if before == after else "strengthening"


def _three_part_key(parts: list[str], first: str, third: str) -> bool:
    return len(parts) == 3 and parts[0] == first and parts[2] == third


def _risk_profile_direction(parts: list[str], before: Any, after: Any) -> str:
    if len(parts) != 3 or parts[0] != "risk_profiles":
        return "unknown"
    if parts[2] == "required_execution_profiles":
        return _set_direction(before, after)
    return _boolean_control_direction(parts[2], before, after)


def _boolean_control_direction(name: str, before: Any, after: Any) -> str:
    if not name.startswith("requires_"):
        return "unknown"
    if not isinstance(before, bool) or not isinstance(after, bool):
        return "unknown"
    if before == after:
        return "neutral"
    return "weakening" if before and not after else "strengthening"


def _policy_key_direction(key: str, before: Any, after: Any) -> str:
    parts = key.split(".")
    set_rule = key in {"policy.protected_paths", "policy.blocked_command_regex"}
    profile_rule = _three_part_key(parts, "profiles", "gates")
    exit_rule = _three_part_key(parts, "gates", "quality_failure_exit_codes")
    if any((set_rule, profile_rule, exit_rule)):
        return _set_direction(before, after)
    if key.startswith("risk_rules.minimum_profile_by_factor."):
        return _profile_direction(before, after, RISK_ORDER)
    return _risk_profile_direction(parts, before, after)


def _numeric(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _numeric_strength_rule(name: str) -> str | None:
    if name.startswith(("max_", "maximum_")):
        return "lower"
    higher_names = {
        "branches",
        "changed_lines",
        "functions",
        "lines",
        "statements",
        "lighthouse_accessibility",
        "lighthouse_performance",
    }
    return "higher" if name.startswith(("min_", "minimum_")) or name in higher_names else None


def _numeric_direction(key: str, before: Any, after: Any) -> str:
    if not all((_numeric(before), _numeric(after))):
        return "unknown"
    name = key.rsplit(".", 1)[-1]
    if before == after:
        return "neutral"
    rule = _numeric_strength_rule(name)
    if rule is None:
        return "unknown"
    stronger = after < before if rule == "lower" else after > before
    return "strengthening" if stronger else "weakening"


def _project_key_direction(key: str, before: Any, after: Any) -> str:
    if key.startswith("thresholds.") or key.startswith("profile_thresholds."):
        return _threshold_direction(key, before, after)
    if key in {"paths.tests", "python.test_paths"}:
        return _set_direction(before, after)
    if key == "enforcement.stage":
        return _profile_direction(before, after, ["shadow", "ratchet", "strict"])
    return "unknown"


def _threshold_direction(key: str, before: Any, after: Any) -> str:
    allow_key = key.endswith(("allow_missing", "allow_unreviewed_ignores"))
    if allow_key and isinstance(before, bool) and isinstance(after, bool):
        if before == after:
            return "neutral"
        return "weakening" if not before and after else "strengthening"
    return _numeric_direction(key, before, after)


def _decoded_documents(
    path: str, before_raw: bytes, after_raw: bytes
) -> tuple[dict[str, Any], dict[str, Any], Any]:
    if path.endswith(".toml"):
        return (
            tomllib.loads(before_raw.decode()),
            tomllib.loads(after_raw.decode()),
            _policy_key_direction,
        )
    if path.endswith(".json"):
        return json.loads(before_raw), json.loads(after_raw), _project_key_direction
    raise ValueError("not a structured policy document")


def _document_classification(path: str, before_raw: bytes, after_raw: bytes) -> dict[str, Any]:
    try:
        before, after, direction = _decoded_documents(path, before_raw, after_raw)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, json.JSONDecodeError, ValueError) as exc:
        return {"classification": "unknown", "reasons": [str(exc)]}
    keys = _changed_keys(before, after)
    if not keys:
        return {"classification": "neutral", "reasons": ["semantic content is unchanged"]}
    directions = [direction(key, _lookup(before, key), _lookup(after, key)) for key in keys]
    if "weakening" in directions:
        result = "weakening"
    elif "unknown" in directions:
        result = "unknown"
    else:
        result = "strengthening"
    reasons = [f"{key}: {value}" for key, value in zip(keys, directions, strict=True)]
    return {"classification": result, "reasons": reasons}


def _lookup(document: dict[str, Any], key: str) -> Any:
    value: Any = document
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def classify_policy_changes(
    root: Path, base: str, changes: list[dict[str, str]]
) -> list[dict[str, Any]]:
    """Classify exact protected changes without granting authority to unknown edits."""
    reports: list[dict[str, Any]] = []
    for change in changes:
        path, operation = change["path"], change["operation"]
        before, after = _base_bytes(root, base, path), _candidate_bytes(root, path)
        if operation in {"delete", "rename_from"}:
            result = {"classification": "weakening", "reasons": ["protected file removed"]}
        elif before is None or after is None:
            result = {"classification": "unknown", "reasons": ["no comparable document pair"]}
        else:
            result = _document_classification(path, before, after)
        reports.append({**change, **result})
    return reports


def _selected_request(
    root: Path, policy: dict[str, Any], actual: list[dict[str, str]]
) -> tuple[list[dict[str, str]], list[str]]:
    request_env = str(
        policy.get("policy", {}).get("maintenance_request_env", "AQG_MAINTENANCE_REQUEST")
    )
    request_id = os.environ.get(request_env, "")
    if not request_id:
        return [], [f"protected candidate requires a scoped request selected by {request_env}"]
    try:
        request = load_maintenance_request(root, request_id)
    except ConfigurationError as exc:
        return [], [str(exc)]
    authorized = request["authorized_changes"]
    errors = (
        []
        if authorized == actual
        else [
            "maintenance request authorized_changes must exactly match protected candidate changes"
        ]
    )
    return authorized, errors


def _human_override_errors(root: Path, actual: list[dict[str, str]]) -> list[str]:
    errors = validate_approval(root, "policy-maintenance")
    path = approval_path(root, "policy-maintenance")
    payload: Any = read_json(path) if path.is_file() else {}
    maintenance = payload.get("maintenance") if isinstance(payload, dict) else None
    raw = maintenance.get("authorized_changes") if isinstance(maintenance, dict) else None
    try:
        authorized = (
            sorted(
                (_change(item.get("path"), item.get("operation")) for item in raw),
                key=lambda item: (item["path"], item["operation"]),
            )
            if isinstance(raw, list)
            else []
        )
    except (AttributeError, ConfigurationError) as exc:
        errors.append(str(exc))
        authorized = []
    if authorized != actual:
        errors.append("human maintenance authorization must exactly match protected changes")
    return errors


def _authority_trigger_state(root: Path) -> tuple[list[str], list[str]]:
    try:
        card = read_json(root / "quality" / "change-risk.json")
    except (ConfigurationError, OSError, json.JSONDecodeError) as exc:
        return [], [f"authority trigger state is unusable: {exc}"]
    triggers = card.get("authority_triggers") if isinstance(card, dict) else None
    if not isinstance(triggers, dict):
        return [], ["authority trigger state is unusable: authority_triggers is required"]
    return _validated_authority_triggers(triggers)


def _validated_authority_triggers(triggers: dict[str, Any]) -> tuple[list[str], list[str]]:
    expected = {
        "guardrail_weakening",
        "paid_external_action",
        "private_data_exposure",
        "irreversible_execution",
    }
    errors = [
        f"authority trigger state is unusable: unknown trigger {name!r}"
        for name in sorted(set(triggers) - expected)
    ]
    errors.extend(
        f"authority trigger state is unusable: missing trigger {name!r}"
        for name in sorted(expected - set(triggers))
    )
    errors.extend(
        f"authority trigger state is unusable: trigger {name!r} must be boolean"
        for name, value in sorted(triggers.items())
        if name in expected and not isinstance(value, bool)
    )
    active = sorted(name for name, value in triggers.items() if name in expected and value is True)
    return active, errors


def _expected_council_scope(root: Path, base: str) -> dict[str, str]:
    return {
        "revision": git_revision(root),
        "base_revision": base,
        "change_fingerprint": change_fingerprint(root, base),
        "control_fingerprint": control_fingerprint(root),
    }


def _council_scope_errors(report: dict[str, Any], expected: dict[str, str]) -> list[str]:
    scope = report.get("scope")
    if scope == expected:
        return []
    return ["policy-maintenance council scope is stale or belongs to another candidate"]


def _council_quality_errors(report: dict[str, Any]) -> list[str]:
    from .council import ROLES

    verification = report.get("verification")
    manifest = verification.get("manifest") if isinstance(verification, dict) else None
    groups = report.get("provider_groups")
    roles = report.get("covered_roles")
    dissent = report.get("dissent")
    checks = (
        (
            report.get("purpose") == "policy_maintenance",
            "council purpose must be policy_maintenance",
        ),
        (report.get("tier") == "high", "council tier must be high"),
        (report.get("status") == "advisory_clear", "council status must be advisory_clear"),
        (report.get("complete") is True, "council must be complete"),
        (not report.get("blockers"), "council must contain no blockers"),
        (
            isinstance(dissent, dict) and dissent.get("present") is False,
            "council must contain no dissent",
        ),
        (
            not report.get("incomplete_reasons"),
            "council must contain no incomplete reasons",
        ),
        (
            isinstance(groups, list) and len(set(groups)) >= 3,
            "council must include at least three independent provider groups",
        ),
        (
            isinstance(roles, list) and set(roles) == set(ROLES),
            "council must cover every required review role",
        ),
        (
            isinstance(verification, dict) and verification.get("ok") is True,
            "council evidence verification must pass",
        ),
        (
            isinstance(manifest, dict) and manifest.get("ok") is True,
            "council evidence manifest must be verified",
        ),
    )
    return [message for valid, message in checks if not valid]


def _council_authority(root: Path, base: str) -> tuple[dict[str, Any] | None, list[str]]:
    # Imported lazily because council_service reaches maintenance through review adapters.
    from .council import fingerprint
    from .council_service import report_council

    try:
        report = report_council(root)
    except (ConfigurationError, OSError) as exc:
        return None, [f"exact-candidate policy-maintenance council is unavailable: {exc}"]
    errors = _council_scope_errors(report, _expected_council_scope(root, base))
    errors.extend(_council_quality_errors(report))
    if errors:
        return None, errors
    return (
        {
            "kind": "agent_council",
            "purpose": "policy_maintenance_unknown_change_review",
            "run_id": str(report["run_id"]),
            "tier": "high",
            "status": "advisory_clear",
            "manifest_verified": True,
            "report_sha256": fingerprint(report),
            "provider_groups": sorted(str(value) for value in report["provider_groups"]),
            "covered_roles": sorted(str(value) for value in report["covered_roles"]),
            "scope": dict(report["scope"]),
        },
        [],
    )


def validate_policy_maintenance(root: Path, policy: dict[str, Any], base: str) -> dict[str, Any]:
    """Accept exact neutral/stronger maintenance and independently reviewed ambiguity."""
    actual = protected_changes(root, policy, base)
    if not actual:
        return {
            "required": False,
            "changes": [],
            "authorized_changes": [],
            "errors": [],
            "exit_code": PASS,
        }
    authorized, errors = _selected_request(root, policy, actual)
    classifications = classify_policy_changes(root, base, actual)
    authority_triggers, authority_trigger_errors = _authority_trigger_state(root)
    errors.extend(authority_trigger_errors)
    human_required = bool(authority_triggers) or any(
        item["classification"] == "weakening" for item in classifications
    )
    council_required = not human_required and any(
        item["classification"] == "unknown" for item in classifications
    )
    human_errors = _human_override_errors(root, actual) if human_required else []
    council_authority, council_errors = (
        _council_authority(root, base) if council_required else (None, [])
    )
    errors.extend(human_errors)
    errors.extend(council_errors)
    return {
        "required": True,
        "changes": actual,
        "authorized_changes": authorized,
        "classifications": classifications,
        "authority_triggers": authority_triggers,
        "authority_trigger_errors": authority_trigger_errors,
        "human_authority_required": human_required,
        "human_authority_errors": human_errors,
        "agent_council_authority_required": council_required,
        "agent_council_authority": council_authority,
        "agent_council_authority_errors": council_errors,
        "errors": errors,
        "exit_code": CONFIGURATION_ERROR
        if authority_trigger_errors
        else (QUALITY_FAILURE if errors else PASS),
    }
