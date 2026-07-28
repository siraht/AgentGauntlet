"""Monotonic shadow-to-ratchet-to-strict promotion proposals."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .debt_store import load_current_debt_baseline
from .errors import ConfigurationError
from .evidence_manifest import verify_run_manifest, write_evidence_json
from .project import load_project
from .util import (
    change_fingerprint,
    control_fingerprint,
    git_revision,
    read_json,
    utc_now,
)

STAGES = ("shadow", "ratchet", "strict")


def enforcement_stage(project: dict[str, Any]) -> str:
    enforcement = project.get("enforcement", {})
    stage = enforcement.get("stage")
    if stage in STAGES:
        return str(stage)
    return "strict" if enforcement.get("mode") == "greenfield" else "shadow"


def _latest_deep(root: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    candidates: list[tuple[int, Path]] = []
    for path in (root / ".aqg" / "runs").glob("*/summary.json"):
        try:
            summary = read_json(path)
            if isinstance(summary, dict) and summary.get("profile") == "deep":
                candidates.append((path.stat().st_mtime_ns, path.parent))
        except (OSError, ValueError):
            continue
    if not candidates:
        return None, None
    run_dir = max(candidates)[1]
    if not verify_run_manifest(run_dir)["ok"]:
        return None, None
    summary = read_json(run_dir / "summary.json")
    retrospective = read_json(run_dir / "retrospective.json")
    if not isinstance(summary, dict) or not isinstance(retrospective, dict):
        return None, None
    return summary, retrospective


def promotion_status(root: Path) -> dict[str, Any]:
    project = load_project(root)
    stage = enforcement_stage(project)
    enforcement = project.get("enforcement", {})
    base = str(enforcement.get("base_ref", "HEAD"))
    current_control = control_fingerprint(root)
    current_change = change_fingerprint(root, base)
    baseline_path = root / str(
        enforcement.get(
            "debt_baseline",
            "quality/baselines/debt.json",
        )
    )
    baseline_errors: list[str] = []
    baseline: dict[str, Any] | None = None
    if baseline_path.is_file():
        try:
            baseline = load_current_debt_baseline(root, baseline_path)
        except ConfigurationError as exc:
            baseline_errors.append(str(exc))
    else:
        baseline_errors.append("reviewed debt baseline is missing")
    deep, retrospective = _latest_deep(root)
    strict_errors: list[str] = []
    if stage != "ratchet":
        strict_errors.append("strict promotion requires the ratchet stage")
    if baseline_errors:
        strict_errors.extend(baseline_errors)
    if deep is None or retrospective is None:
        strict_errors.append("a manifested deep run is missing")
    else:
        if deep.get("status") != "pass" or deep.get("mode") != "enforce":
            strict_errors.append("latest manifested deep run is not an enforcing pass")
        if deep.get("enforcement_stage") != "ratchet":
            strict_errors.append("latest manifested deep run did not enforce the ratchet stage")
        if deep.get("control_fingerprint") != current_control:
            strict_errors.append("latest manifested deep run used different controls")
        if deep.get("change_fingerprint") != current_change:
            strict_errors.append("latest manifested deep run measured a different change surface")
        counts = retrospective.get("counts", {})
        debt_names = (
            "inherited_debt",
            "regressions",
            "new_debt",
            "invalid_debt",
            "missing_evidence",
            "configuration_errors",
            "infrastructure_errors",
            "unknown_product_intent",
            "unreviewed_debt",
        )
        if not isinstance(counts, dict) or any(counts.get(name, 0) for name in debt_names):
            strict_errors.append("latest deep run is not debt- and unknown-intent-free")
    return {
        "schema_version": 1,
        "stage": stage,
        "baseline": {
            "path": str(baseline_path),
            "current": baseline is not None,
            "errors": baseline_errors,
        },
        "ratchet_ready": stage == "shadow" and not baseline_errors,
        "strict_ready": not strict_errors,
        "strict_errors": strict_errors,
        "latest_deep_run": deep,
        "current_control_fingerprint": current_control,
        "current_change_fingerprint": current_change,
    }


def propose_promotion(root: Path, target: str) -> dict[str, Any]:
    if target not in STAGES:
        raise ConfigurationError(f"promotion target must be one of: {', '.join(STAGES)}")
    status = promotion_status(root)
    current = status["stage"]
    expected_index = STAGES.index(current) + 1
    if expected_index >= len(STAGES) or STAGES[expected_index] != target:
        raise ConfigurationError(
            f"promotion must be monotonic and adjacent; {current!r} can only advance to "
            f"{STAGES[expected_index]!r}"
            if expected_index < len(STAGES)
            else f"enforcement is already at terminal stage {current!r}"
        )
    if target == "ratchet" and not status["ratchet_ready"]:
        raise ConfigurationError("ratchet promotion requires a current reviewed debt baseline")
    if target == "strict" and not status["strict_ready"]:
        raise ConfigurationError(
            "strict promotion is not ready: " + "; ".join(status["strict_errors"])
        )
    project = load_project(root)
    base = str(project.get("enforcement", {}).get("base_ref", "HEAD"))
    payload = {
        "schema_version": 1,
        "state": "proposed",
        "authority": "none",
        "from_stage": current,
        "to_stage": target,
        "created_at": utc_now(),
        "revision": git_revision(root),
        "change_fingerprint": change_fingerprint(root, base),
        "control_fingerprint": control_fingerprint(root),
        "required_project_changes": {
            "enforcement.stage": target,
            **({"enforcement.scope": "full"} if target == "strict" else {}),
        },
        "readiness": status,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    proposal_id = f"promotion-{current}-to-{target}-{digest}"
    path = root / ".aqg" / "proposals" / "promotion" / f"{proposal_id}.json"
    write_evidence_json(path, payload)
    return {"proposal_id": proposal_id, "path": str(path), "proposal": payload}
