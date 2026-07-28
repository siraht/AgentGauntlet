"""Human approval record templates and validation."""

from __future__ import annotations

import getpass
import hashlib
import os
from pathlib import Path
from typing import Any

from .constants import PASS, QUALITY_FAILURE
from .errors import ConfigurationError
from .evidence_manifest import validate_run_id, verify_run_manifest
from .project import load_project
from .util import (
    change_fingerprint,
    control_fingerprint,
    git_revision,
    read_json,
    utc_now,
    write_json,
)

KINDS = {
    "behavior-review": {
        "purpose": "Confirms observable behavior, preserved behavior, and acceptance examples were reviewed.",
        "required_for": ["standard", "high_assurance", "critical"],
    },
    "manual-qa": {
        "purpose": "Records execution of the reviewed manual QA procedure in an isolated environment.",
        "required_for": ["high_assurance", "critical"],
    },
    "rollback-rehearsal": {
        "purpose": "Records that rollback or recovery was exercised rather than merely described.",
        "required_for": ["high_assurance", "critical"],
    },
    "independent-verification": {
        "purpose": "Records read-only verification by a reviewer independent of the builder and evidence producer.",
        "required_for": ["high_assurance", "critical"],
    },
    "human-code-review": {
        "purpose": "Records independent human inspection of critical implementation code and tests.",
        "required_for": ["critical"],
    },
    "release-approval": {
        "purpose": "Records the final human decision to promote a specific revision.",
        "required_for": ["critical"],
    },
    "policy-maintenance": {
        "purpose": "Authorizes a scoped protected-policy maintenance request for independent code-owner review.",
        "required_for": [],
    },
}
RUN_BOUND_KINDS = frozenset(
    {"manual-qa", "rollback-rehearsal", "independent-verification", "human-code-review"}
)


def _approval_provenance(root: Path) -> dict[str, str]:
    try:
        base = os.environ.get("AQG_DIFF_BASE") or str(
            load_project(root).get("enforcement", {}).get("base_ref", "HEAD")
        )
    except Exception:
        base = os.environ.get("AQG_DIFF_BASE") or "HEAD"
    return {
        "revision": git_revision(root),
        "base_ref": base,
        "change_fingerprint": change_fingerprint(
            root, base, exclude_patterns=["quality/approvals/**"]
        ),
        "control_fingerprint": control_fingerprint(root),
    }


def approval_path(root: Path, kind: str) -> Path:
    if kind not in KINDS:
        raise ConfigurationError(f"unknown approval kind {kind!r}; choose: {', '.join(KINDS)}")
    return root / "quality" / "approvals" / f"{kind}.json"


def template(root: Path, kind: str, *, reviewer: str | None = None) -> dict[str, Any]:
    info = KINDS.get(kind)
    if info is None:
        raise ConfigurationError(f"unknown approval kind {kind!r}; choose: {', '.join(KINDS)}")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": kind,
        "purpose": info["purpose"],
        **_approval_provenance(root),
        "actor_type": "human",
        "reviewer": reviewer or getpass.getuser(),
        "reviewed_at": utc_now(),
        "result": "pending",
        "scope": [],
        "procedure": [],
        "evidence": [],
        "evidence_run": None,
        "findings": [],
        "notes": "",
        "independence": {
            "reviewer_did_not_author_change": None,
            "reviewer_did_not_modify_evidence": None,
        },
    }
    if kind == "policy-maintenance":
        payload["maintenance"] = {
            "reason": "",
            "authorized_changes": [],
        }
    return payload


def write_template(
    root: Path, kind: str, *, reviewer: str | None = None, force: bool = False
) -> Path:
    path = approval_path(root, kind)
    if path.exists() and not force:
        raise ConfigurationError(
            f"approval record already exists: {path}; use --force only for an explicit human review task"
        )
    write_json(path, template(root, kind, reviewer=reviewer))
    return path


def validate_approval(
    root: Path, kind: str, *, require_pass: bool = True, require_current_revision: bool = True
) -> list[str]:
    path = approval_path(root, kind)
    if not path.exists():
        return [f"missing {path.relative_to(root)}"]
    payload = read_json(path)
    errors: list[str] = []
    if not isinstance(payload, dict):
        return [f"{path.relative_to(root)} must contain a JSON object"]
    errors.extend(_validate_record_identity(payload, kind, require_pass))
    if require_current_revision:
        errors.extend(_validate_current_provenance(root, payload))
    errors.extend(_validate_record_arrays(payload))
    if require_pass and payload.get("result") == "pass":
        errors.extend(_validate_pass_evidence(root, kind, payload))
    errors.extend(_validate_independence(kind, payload))
    return errors


def _validate_record_identity(payload: dict[str, Any], kind: str, require_pass: bool) -> list[str]:
    checks = (
        (payload.get("schema_version") == 1, "schema_version must be 1"),
        (payload.get("kind") == kind, f"kind must be {kind!r}"),
        (
            payload.get("actor_type") == "human",
            "actor_type must be 'human'; agent evidence belongs in the review council",
        ),
        (
            isinstance(payload.get("reviewer"), str) and bool(str(payload.get("reviewer")).strip()),
            "reviewer must be a non-empty human identity",
        ),
        (
            isinstance(payload.get("reviewed_at"), str)
            and bool(str(payload.get("reviewed_at")).strip()),
            "reviewed_at must be an ISO timestamp",
        ),
        (not require_pass or payload.get("result") == "pass", "result must be 'pass'"),
    )
    return [message for valid, message in checks if not valid]


def _validate_current_provenance(root: Path, payload: dict[str, Any]) -> list[str]:
    current = _approval_provenance(root)
    errors: list[str] = []
    if payload.get("revision") != current["revision"]:
        errors.append(f"revision must match current HEAD {current['revision']}")
    if payload.get("base_ref") != current["base_ref"]:
        errors.append(f"base_ref must match current comparison base {current['base_ref']!r}")
    if payload.get("change_fingerprint") != current["change_fingerprint"]:
        errors.append(
            "change_fingerprint is stale; the reviewed source/test/spec surface changed after approval"
        )
    if payload.get("control_fingerprint") != current["control_fingerprint"]:
        errors.append(
            "control_fingerprint is stale; policy, commands, or toolchain inputs changed after approval"
        )
    return errors


def _validate_record_arrays(payload: dict[str, Any]) -> list[str]:
    keys = ("scope", "procedure", "evidence", "findings")
    return [f"{key} must be an array" for key in keys if not isinstance(payload.get(key), list)]


def _validate_pass_evidence(root: Path, kind: str, payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in ("scope", "procedure", "evidence"):
        value = payload.get(key)
        if isinstance(value, list) and not any(str(item).strip() for item in value):
            errors.append(f"{key} must contain concrete reviewed items before result can be 'pass'")
    if kind == "rollback-rehearsal" and not str(payload.get("notes", "")).strip():
        errors.append(
            "rollback-rehearsal notes must record the observed recovery result and timing"
        )
    if kind in RUN_BOUND_KINDS:
        errors.extend(_validate_evidence_run(root, payload))
    return errors


def _validate_independence(kind: str, payload: dict[str, Any]) -> list[str]:
    independence = payload.get("independence")
    if kind in {
        "independent-verification",
        "human-code-review",
        "release-approval",
        "policy-maintenance",
    }:
        if not isinstance(independence, dict):
            return ["independence declaration is required"]
        keys = ("reviewer_did_not_author_change", "reviewer_did_not_modify_evidence")
        return [
            f"independence.{key} must be true" for key in keys if independence.get(key) is not True
        ]
    return []


def _validate_evidence_run(root: Path, approval: dict[str, Any]) -> list[str]:
    record = approval.get("evidence_run")
    if not isinstance(record, dict):
        return ["evidence_run must bind this approval to manifested AQG evidence"]
    required = {"run_id", "manifest_sha256", "candidate_fingerprint"}
    if set(record) != required:
        return ["evidence_run must contain only run_id, manifest_sha256, candidate_fingerprint"]
    raw_run_id = record.get("run_id")
    if not isinstance(raw_run_id, str):
        return ["evidence_run.run_id must be a string"]
    try:
        run_id = validate_run_id(raw_run_id)
    except ConfigurationError as exc:
        return [f"evidence_run.run_id is invalid: {exc}"]
    run_dir = root / ".aqg" / "runs" / run_id
    verification = verify_run_manifest(run_dir)
    errors = [f"evidence_run manifest is invalid: {item}" for item in verification["errors"]]
    manifest = run_dir / "manifest.json"
    actual_digest = (
        "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()
        if manifest.is_file()
        else None
    )
    if record.get("manifest_sha256") != actual_digest:
        errors.append("evidence_run.manifest_sha256 does not match the immutable run manifest")
    if record.get("candidate_fingerprint") != approval.get("change_fingerprint"):
        errors.append("evidence_run.candidate_fingerprint does not match the approved candidate")
    return errors


def validate_required_approvals(root: Path, risk_profile: str) -> dict[str, Any]:
    required = [kind for kind, info in KINDS.items() if risk_profile in info["required_for"]]
    results: dict[str, list[str]] = {kind: validate_approval(root, kind) for kind in required}
    errors = [f"{kind}: {message}" for kind, messages in results.items() for message in messages]
    return {
        "required": required,
        "results": results,
        "errors": errors,
        "exit_code": QUALITY_FAILURE if errors else PASS,
    }
