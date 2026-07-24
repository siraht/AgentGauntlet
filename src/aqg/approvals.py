"""Human approval record templates and validation."""

from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import Any

from .constants import PASS, QUALITY_FAILURE
from .errors import ConfigurationError
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
    "human-code-review": {
        "purpose": "Records independent human inspection of critical implementation code and tests.",
        "required_for": ["critical"],
    },
    "release-approval": {
        "purpose": "Records the final human decision to promote a specific revision.",
        "required_for": ["critical"],
    },
}


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
    return {
        "schema_version": 1,
        "kind": kind,
        "purpose": info["purpose"],
        **_approval_provenance(root),
        "reviewer": reviewer or getpass.getuser(),
        "reviewed_at": utc_now(),
        "result": "pending",
        "scope": [],
        "procedure": [],
        "evidence": [],
        "findings": [],
        "notes": "",
        "independence": {
            "reviewer_did_not_author_change": None,
            "reviewer_did_not_modify_evidence": None,
        },
    }


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
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if payload.get("kind") != kind:
        errors.append(f"kind must be {kind!r}")
    reviewer = payload.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        errors.append("reviewer must be a non-empty human identity")
    if (
        not isinstance(payload.get("reviewed_at"), str)
        or not payload.get("reviewed_at", "").strip()
    ):
        errors.append("reviewed_at must be an ISO timestamp")
    if require_pass and payload.get("result") != "pass":
        errors.append("result must be 'pass'")
    if require_current_revision:
        current = _approval_provenance(root)
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
    for key in ("scope", "procedure", "evidence", "findings"):
        if not isinstance(payload.get(key), list):
            errors.append(f"{key} must be an array")
    if require_pass and payload.get("result") == "pass":
        for key in ("scope", "procedure", "evidence"):
            value = payload.get(key)
            if isinstance(value, list) and not any(str(item).strip() for item in value):
                errors.append(
                    f"{key} must contain concrete reviewed items before result can be 'pass'"
                )
        if kind == "rollback-rehearsal" and not str(payload.get("notes", "")).strip():
            errors.append(
                "rollback-rehearsal notes must record the observed recovery result and timing"
            )
    independence = payload.get("independence")
    if kind in {"human-code-review", "release-approval"}:
        if not isinstance(independence, dict):
            errors.append("independence declaration is required")
        else:
            for key in ("reviewer_did_not_author_change", "reviewer_did_not_modify_evidence"):
                if independence.get(key) is not True:
                    errors.append(f"independence.{key} must be true")
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
