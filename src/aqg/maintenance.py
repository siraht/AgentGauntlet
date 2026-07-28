"""Authoritative policy-maintenance change and approval contracts."""

from __future__ import annotations

import getpass
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from .approvals import approval_path, validate_approval
from .constants import PASS, QUALITY_FAILURE
from .errors import ConfigurationError
from .evidence_manifest import validate_run_id, write_evidence_json
from .policy import load_policy, protected_patterns
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
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ConfigurationError(f"invalid maintenance request {request_id}")
    if payload.get("state") != "proposed" or payload.get("authority") != "none":
        raise ConfigurationError("maintenance request must be non-authorizing proposed state")
    if payload.get("source_revision") != git_revision(root):
        raise ConfigurationError("maintenance request source revision is stale")
    if not str(payload.get("reason") or "").strip():
        raise ConfigurationError("maintenance request reason must not be blank")
    raw = payload.get("authorized_changes")
    if not isinstance(raw, list):
        raise ConfigurationError("maintenance request authorized_changes must be an array")
    policy = load_policy(root)
    payload["authorized_changes"] = _validate_requested_changes(raw, policy)
    payload["request_id"] = request_id
    return payload


def _status_changes(root: Path, base: str) -> list[dict[str, str]]:
    code, stdout, stderr = git_output(root, ["diff", "--name-status", "--find-renames", base, "--"])
    if code != 0:
        raise ConfigurationError(
            f"cannot resolve policy-maintenance comparison ref {base!r}: {stderr.strip()}"
        )
    changes: list[dict[str, str]] = []
    tracked: set[str] = set()
    for line in stdout.splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        status = fields[0]
        kind = status[:1]
        if kind == "R" and len(fields) >= 3:
            old, new = _path(fields[1]), _path(fields[2])
            tracked.update((old, new))
            changes.extend((_change(old, "rename_from"), _change(new, "rename_to")))
            continue
        path = _path(fields[-1])
        tracked.add(path)
        changes.append(_change(path, _STATUS_OPERATION.get(kind, "modify")))
    for path in git_changed_files(root, base, include_worktree=True):
        normalized = _path(path)
        if normalized not in tracked and (root / normalized).is_file():
            changes.append(_change(normalized, "add"))
    return changes


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


def validate_policy_maintenance(root: Path, policy: dict[str, Any], base: str) -> dict[str, Any]:
    """Require an exact, current, independently approved protected change set."""
    actual = protected_changes(root, policy, base)
    if not actual:
        return {
            "required": False,
            "changes": [],
            "authorized_changes": [],
            "errors": [],
            "exit_code": PASS,
        }
    errors = validate_approval(root, "policy-maintenance")
    payload: Any = {}
    path = approval_path(root, "policy-maintenance")
    if path.is_file():
        payload = read_json(path)
    maintenance = payload.get("maintenance") if isinstance(payload, dict) else None
    authorized: list[dict[str, str]] = []
    if not isinstance(maintenance, dict):
        errors.append("policy-maintenance approval must contain a maintenance object")
    else:
        if not str(maintenance.get("reason") or "").strip():
            errors.append("maintenance.reason must explain why protected policy must change")
        raw_changes = maintenance.get("authorized_changes")
        if not isinstance(raw_changes, list):
            errors.append("maintenance.authorized_changes must be an array")
        else:
            try:
                authorized = sorted(
                    (_change(item.get("path"), item.get("operation")) for item in raw_changes),
                    key=lambda item: (item["path"], item["operation"]),
                )
            except (AttributeError, ConfigurationError) as exc:
                errors.append(str(exc))
    if authorized != actual:
        errors.append(
            "maintenance.authorized_changes must exactly match protected candidate changes"
        )
    return {
        "required": True,
        "changes": actual,
        "authorized_changes": authorized,
        "errors": errors,
        "exit_code": QUALITY_FAILURE if errors else PASS,
    }
