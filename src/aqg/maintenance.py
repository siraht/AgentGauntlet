"""Authoritative policy-maintenance change and approval contracts."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from .approvals import approval_path, validate_approval
from .constants import PASS, QUALITY_FAILURE
from .errors import ConfigurationError
from .policy import protected_patterns
from .util import git_changed_files, git_output, matches_any, read_json

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


def _change(path: str, operation: str) -> dict[str, str]:
    if operation not in OPERATIONS:
        raise ConfigurationError(f"unsupported policy-maintenance operation {operation!r}")
    return {"path": _path(path), "operation": operation}


def _status_changes(root: Path, base: str) -> list[dict[str, str]]:
    code, stdout, stderr = git_output(
        root, ["diff", "--name-status", "--find-renames", base, "--"]
    )
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


def validate_policy_maintenance(
    root: Path, policy: dict[str, Any], base: str
) -> dict[str, Any]:
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
        errors.append("maintenance.authorized_changes must exactly match protected candidate changes")
    return {
        "required": True,
        "changes": actual,
        "authorized_changes": authorized,
        "errors": errors,
        "exit_code": QUALITY_FAILURE if errors else PASS,
    }
