"""Filesystem lifecycle for retrospective debt-baseline proposals."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from .council import ROLES, fingerprint
from .debt import DebtError, document_fingerprint, validate_baseline
from .errors import ConfigurationError, InfrastructureError
from .evidence_manifest import (
    validate_run_id,
    verify_run_manifest,
    write_evidence_json,
)
from .maintenance import require_local_maintenance_change
from .project import load_project
from .util import (
    change_fingerprint,
    control_fingerprint,
    git_output,
    read_json,
    sha256_file,
    utc_now,
)


def debt_control_fingerprint(root: Path) -> str:
    """Bind debt to substantive controls, excluding separately governed promotion state."""
    project_path = root / "quality" / "project.json"
    project = copy.deepcopy(load_project(root)) if project_path.is_file() else {}
    enforcement = project.get("enforcement")
    if isinstance(enforcement, dict):
        enforcement.pop("stage", None)
        enforcement.pop("scope", None)
    payload = {
        "other_controls": control_fingerprint(
            root,
            exclude_patterns=["quality/baselines/debt.json", "quality/project.json"],
        ),
        "project_without_promotion_state": project,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


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


def _verified_shadow_documents(
    run_dir: Path, resolved: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    verification = verify_run_manifest(run_dir)
    if not verification["ok"]:
        detail = "; ".join(str(error) for error in verification["errors"])
        raise InfrastructureError(f"shadow run {resolved} failed manifest verification: {detail}")
    return (
        verification,
        _object(run_dir / "summary.json", "run summary"),
        _object(run_dir / "retrospective.json", "retrospective evidence"),
        _object(run_dir / "manifest.json", "run manifest"),
    )


def _validate_shadow_scope(root: Path, resolved: str, summary: dict[str, Any]) -> tuple[str, Any]:
    if summary.get("run_id") != resolved or summary.get("mode") != "shadow":
        raise ConfigurationError(f"run {resolved} is not a shadow audit")
    if summary.get("control_fingerprint") != control_fingerprint(root):
        raise ConfigurationError(
            f"controls changed after shadow run {resolved}; run a new shadow audit"
        )
    baseline_controls = debt_control_fingerprint(root)
    measured_change = summary.get("change_fingerprint")
    base_ref = summary.get("base_ref")
    if not isinstance(base_ref, str) or measured_change != change_fingerprint(root, base_ref):
        raise ConfigurationError(
            f"the review surface changed after shadow run {resolved}; run a new shadow audit"
        )
    return baseline_controls, measured_change


def _measurement_values(
    resolved: str,
    summary: dict[str, Any],
    retrospective: dict[str, Any],
    manifest: dict[str, Any],
) -> tuple[list[Any], str, str, str]:
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
    return inventory, revision, profile, measured_at


def _proposed_baseline(
    *,
    revision: str,
    baseline_controls: str,
    source_manifest_fingerprint: str,
    resolved: str,
    profile: str,
    measured_at: str,
    measured_change: Any,
    inventory: list[Any],
    policy_fingerprint: str,
) -> dict[str, Any]:
    return validate_baseline(
        {
            "schema_version": 1,
            "state": "proposed",
            "source_revision": revision,
            "policy_fingerprint": policy_fingerprint,
            "control_fingerprint": baseline_controls,
            "created_at": utc_now(),
            "measurement": {
                "run_id": resolved,
                "profile": profile,
                "measured_at": measured_at,
                "change_fingerprint": str(measured_change),
                "manifest_fingerprint": source_manifest_fingerprint,
            },
            "inventory": inventory,
        }
    )


def propose_debt_baseline(root: Path, run_id: str = "latest") -> dict[str, Any]:
    """Create a write-once proposal from manifested shadow evidence.

    A proposal is deliberately not a reviewed baseline and cannot authorize
    ratchet enforcement.
    """
    resolved, run_dir = resolve_shadow_run(root, run_id)
    verification, summary, retrospective, manifest = _verified_shadow_documents(run_dir, resolved)
    baseline_controls, measured_change = _validate_shadow_scope(root, resolved, summary)
    inventory, revision, profile, measured_at = _measurement_values(
        resolved, summary, retrospective, manifest
    )
    source_manifest_fingerprint = f"sha256:{sha256_file(run_dir / 'manifest.json')}"
    proposed = _proposed_baseline(
        revision=revision,
        baseline_controls=baseline_controls,
        source_manifest_fingerprint=source_manifest_fingerprint,
        resolved=resolved,
        profile=profile,
        measured_at=measured_at,
        measured_change=measured_change,
        inventory=inventory,
        policy_fingerprint=f"sha256:{sha256_file(root / 'quality' / 'policy.toml')}",
    )
    fingerprint = document_fingerprint(proposed)
    proposal_id = f"debt-{resolved}-{source_manifest_fingerprint.removeprefix('sha256:')[:12]}"
    path = root / ".aqg" / "proposals" / "debt" / f"{proposal_id}.json"
    write_evidence_json(path, proposed)
    return {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "path": str(path),
        "document_fingerprint": fingerprint,
        "source_manifest_fingerprint": source_manifest_fingerprint,
        "baseline": proposed,
        "manifest_verification": verification,
    }


def _council_scope_errors(
    report: dict[str, Any], proposal: dict[str, Any], summary: dict[str, Any]
) -> list[str]:
    scope = report.get("scope")
    expected = {
        "revision": proposal["source_revision"],
        "base_revision": summary.get("base_ref"),
        "change_fingerprint": proposal["measurement"]["change_fingerprint"],
        "control_fingerprint": proposal["control_fingerprint"],
    }
    if not isinstance(scope, dict):
        return ["council candidate scope is missing"]
    return [
        f"council {name} does not match the immutable shadow candidate"
        for name, expected_value in expected.items()
        if scope.get(name) != expected_value
    ]


def _council_quality_errors(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    checks = (
        (report.get("tier") == "high", "council tier must be high"),
        (report.get("status") == "advisory_clear", "council status must be advisory_clear"),
        (report.get("complete") is True, "council must be complete"),
        (not report.get("blockers"), "council must contain no blockers"),
        (
            isinstance(report.get("dissent"), dict) and report["dissent"].get("present") is False,
            "council must contain no dissent",
        ),
        (not report.get("incomplete_reasons"), "council must contain no incomplete reasons"),
    )
    errors.extend(message for passed, message in checks if not passed)
    groups = report.get("provider_groups")
    roles = report.get("covered_roles")
    if not isinstance(groups, list) or len(set(groups)) < 3:
        errors.append("council must include at least three independent provider groups")
    if not isinstance(roles, list) or set(roles) != set(ROLES):
        errors.append("council must cover every required review role")
    return errors


def _council_authority(
    root: Path,
    proposal: dict[str, Any],
    summary: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    # Imported lazily because council_service uses review -> runner -> debt_store.
    from .council_service import report_council

    report = report_council(root, validate_run_id(run_id))
    errors = _council_scope_errors(report, proposal, summary) + _council_quality_errors(report)
    if errors:
        raise ConfigurationError("debt review council is not authoritative: " + "; ".join(errors))
    resolved = str(report["run_id"])
    manifest_path = root / ".aqg" / "council" / resolved / "manifest.json"
    return {
        "kind": "agent_council",
        "run_id": resolved,
        "tier": "high",
        "manifest_sha256": f"sha256:{sha256_file(manifest_path)}",
        "report_sha256": fingerprint(report),
        "provider_groups": sorted(str(value) for value in report["provider_groups"]),
        "covered_roles": sorted(str(value) for value in report["covered_roles"]),
        "scope": dict(report["scope"]),
    }


def _review_identity(
    root: Path,
    proposal: dict[str, Any],
    summary: dict[str, Any],
    *,
    authority: str,
    reviewer: str | None,
    review_run_id: str | None,
) -> dict[str, Any]:
    if authority == "council":
        if reviewer:
            raise ConfigurationError("--reviewer is only valid with --authority human")
        if not review_run_id:
            raise ConfigurationError("council debt review requires --review-run-id")
        return {"review_authority": _council_authority(root, proposal, summary, review_run_id)}
    if authority != "human":
        raise ConfigurationError("debt review authority must be 'council' or 'human'")
    if review_run_id:
        raise ConfigurationError("--review-run-id is only valid with --authority council")
    if not reviewer or not reviewer.strip():
        raise ConfigurationError("human debt review requires --reviewer")
    return {"reviewer": reviewer.strip()}


def _proposal_source_documents(
    root: Path, proposal: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    run_id = proposal["measurement"]["run_id"]
    run_dir = root / ".aqg" / "runs" / run_id
    verification = verify_run_manifest(run_dir)
    if not verification["ok"]:
        raise InfrastructureError(
            f"proposal source run {run_id} failed manifest verification: "
            + "; ".join(verification["errors"])
        )
    return (
        _object(run_dir / "summary.json", "run summary"),
        _object(run_dir / "retrospective.json", "retrospective evidence"),
        run_dir,
    )


def _require_current_proposal_source(
    root: Path,
    proposal: dict[str, Any],
    summary: dict[str, Any],
    retrospective: dict[str, Any],
    run_dir: Path,
) -> None:
    expected = (
        summary.get("mode") == "shadow",
        summary.get("revision") == proposal["source_revision"],
        summary.get("change_fingerprint") == proposal["measurement"]["change_fingerprint"],
        f"sha256:{sha256_file(run_dir / 'manifest.json')}"
        == proposal["measurement"]["manifest_fingerprint"],
        retrospective.get("inventory") == proposal["inventory"],
        f"sha256:{sha256_file(root / 'quality' / 'policy.toml')}" == proposal["policy_fingerprint"],
        debt_control_fingerprint(root) == proposal["control_fingerprint"],
    )
    if not all(expected):
        raise ConfigurationError(
            "debt proposal no longer matches its immutable shadow evidence and current controls"
        )


def review_debt_proposal(
    root: Path,
    proposal_id: str,
    *,
    authority: str = "council",
    reviewer: str | None = None,
    review_run_id: str | None = None,
) -> dict[str, Any]:
    """Install a proposal after exact-candidate council or reserved human review."""
    proposal_id = validate_run_id(proposal_id)
    proposal_path = root / ".aqg" / "proposals" / "debt" / f"{proposal_id}.json"
    proposal = validate_baseline(_object(proposal_path, "debt proposal"))
    if proposal["state"] != "proposed":
        raise ConfigurationError("only a proposed debt baseline can be reviewed")
    summary, retrospective, run_dir = _proposal_source_documents(root, proposal)
    _require_current_proposal_source(root, proposal, summary, retrospective, run_dir)
    target = root / "quality" / "baselines" / "debt.json"
    if target.exists():
        raise ConfigurationError(
            "reviewed debt baseline already exists; replacement is not implicit"
        )
    request = require_local_maintenance_change(
        root,
        "quality/baselines/debt.json",
        "add",
    )
    identity = _review_identity(
        root,
        proposal,
        summary,
        authority=authority,
        reviewer=reviewer,
        review_run_id=review_run_id,
    )
    return _install_reviewed_baseline(root, proposal, identity, request)


def _install_reviewed_baseline(
    root: Path,
    proposal: dict[str, Any],
    identity: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    target = root / "quality" / "baselines" / "debt.json"
    reviewed = copy.deepcopy(proposal)
    reviewed.update(
        {
            "state": "reviewed",
            "reviewed_at": utc_now(),
            **identity,
        }
    )
    reviewed = validate_baseline(reviewed)
    write_evidence_json(target, reviewed)
    return {
        "schema_version": 1,
        "path": str(target),
        "document_fingerprint": document_fingerprint(reviewed),
        "maintenance_request": request["request_id"],
        "baseline": reviewed,
    }


def load_current_debt_baseline(root: Path, path: Path) -> dict[str, Any]:
    """Load reviewed baseline authority and reject stale policy or controls."""
    try:
        baseline = validate_baseline(_object(path, "reviewed debt baseline"))
    except (DebtError, InfrastructureError) as exc:
        raise ConfigurationError(f"invalid reviewed debt baseline: {exc}") from exc
    if baseline["state"] != "reviewed":
        raise ConfigurationError("debt baseline is not reviewed and cannot authorize a ratchet")
    expected_policy = f"sha256:{sha256_file(root / 'quality' / 'policy.toml')}"
    if baseline["policy_fingerprint"] != expected_policy:
        raise ConfigurationError("debt baseline policy fingerprint is stale")
    expected_controls = debt_control_fingerprint(root)
    if baseline["control_fingerprint"] != expected_controls:
        raise ConfigurationError("debt baseline control fingerprint is stale")
    code, _, stderr = git_output(
        root,
        [
            "merge-base",
            "--is-ancestor",
            baseline["source_revision"],
            "HEAD",
        ],
    )
    if code != 0:
        raise ConfigurationError(
            "debt baseline source revision is not an ancestor of the candidate"
            + (f": {stderr.strip()}" if stderr.strip() else "")
        )
    return baseline
