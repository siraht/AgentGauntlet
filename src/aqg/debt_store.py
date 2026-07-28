"""Filesystem lifecycle for retrospective debt-baseline proposals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .debt import document_fingerprint, validate_baseline
from .errors import ConfigurationError, InfrastructureError
from .evidence_manifest import (
    validate_run_id,
    verify_run_manifest,
    write_evidence_json,
)
from .util import change_fingerprint, control_fingerprint, read_json, sha256_file, utc_now


def _object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise InfrastructureError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise InfrastructureError(f"{label} {path} must contain a JSON object")
    return payload


def _latest_shadow_run(root: Path) -> str:
    candidates: list[tuple[int, str]] = []
    for summary_path in (root / ".aqg" / "runs").glob("*/summary.json"):
        try:
            summary = _object(summary_path, "run summary")
            if summary.get("mode") == "shadow":
                candidates.append((summary_path.stat().st_mtime_ns, summary_path.parent.name))
        except (InfrastructureError, OSError):
            continue
    if not candidates:
        raise ConfigurationError("no completed shadow run exists; run `qg audit shadow` first")
    return max(candidates)[1]


def resolve_shadow_run(root: Path, run_id: str) -> tuple[str, Path]:
    """Resolve an explicit run or the newest completed shadow run."""
    resolved = _latest_shadow_run(root) if run_id == "latest" else validate_run_id(run_id)
    return resolved, root / ".aqg" / "runs" / resolved


def propose_debt_baseline(root: Path, run_id: str = "latest") -> dict[str, Any]:
    """Create a write-once proposal from manifested shadow evidence.

    A proposal is deliberately not a reviewed baseline and cannot authorize
    ratchet enforcement.
    """
    resolved, run_dir = resolve_shadow_run(root, run_id)
    verification = verify_run_manifest(run_dir)
    if not verification["ok"]:
        detail = "; ".join(str(error) for error in verification["errors"])
        raise InfrastructureError(f"shadow run {resolved} failed manifest verification: {detail}")

    summary = _object(run_dir / "summary.json", "run summary")
    retrospective = _object(run_dir / "retrospective.json", "retrospective evidence")
    manifest = _object(run_dir / "manifest.json", "run manifest")
    if summary.get("run_id") != resolved or summary.get("mode") != "shadow":
        raise ConfigurationError(f"run {resolved} is not a shadow audit")
    measured_controls = summary.get("control_fingerprint")
    if measured_controls != control_fingerprint(root):
        raise ConfigurationError(
            f"controls changed after shadow run {resolved}; run a new shadow audit"
        )
    measured_change = summary.get("change_fingerprint")
    base_ref = summary.get("base_ref")
    if not isinstance(base_ref, str) or measured_change != change_fingerprint(root, base_ref):
        raise ConfigurationError(
            f"the review surface changed after shadow run {resolved}; run a new shadow audit"
        )
    if retrospective.get("schema_version") != 1:
        raise InfrastructureError(f"run {resolved} has unsupported retrospective evidence")
    inventory = retrospective.get("inventory")
    if not isinstance(inventory, list):
        raise InfrastructureError(f"run {resolved} retrospective inventory is missing")
    revision = summary.get("revision")
    if not isinstance(revision, str) or revision in {"", "uncommitted"}:
        raise ConfigurationError("a debt proposal requires a committed source revision")
    profile = summary.get("profile")
    measured_at = manifest.get("completed_at")
    if not isinstance(profile, str) or not isinstance(measured_at, str):
        raise InfrastructureError(f"run {resolved} has incomplete measurement provenance")

    proposed = validate_baseline(
        {
            "schema_version": 1,
            "state": "proposed",
            "source_revision": revision,
            "policy_fingerprint": f"sha256:{sha256_file(root / 'quality' / 'policy.toml')}",
            "control_fingerprint": str(measured_controls),
            "created_at": utc_now(),
            "measurement": {
                "run_id": resolved,
                "profile": profile,
                "measured_at": measured_at,
            },
            "inventory": inventory,
        }
    )
    fingerprint = document_fingerprint(proposed)
    proposal_id = f"debt-{resolved}-{fingerprint.removeprefix('sha256:')[:12]}"
    path = root / ".aqg" / "proposals" / "debt" / f"{proposal_id}.json"
    write_evidence_json(path, proposed)
    return {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "path": str(path),
        "document_fingerprint": fingerprint,
        "source_manifest_fingerprint": f"sha256:{sha256_file(run_dir / 'manifest.json')}",
        "baseline": proposed,
        "manifest_verification": verification,
    }
