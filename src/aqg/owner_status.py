"""Read-only, fail-closed owner readiness model shared by AQG surfaces."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .approvals import validate_required_approvals
from .evidence_manifest import verify_run_manifest
from .policy import load_policy, risk_summary
from .project import load_project
from .promotion import enforcement_stage
from .runner import list_runs
from .scaffold import current_onboarding
from .util import change_fingerprint, control_fingerprint, git_revision, read_json, utc_now

SCHEMA_VERSION = 1


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _scope(root: Path, project: dict[str, Any]) -> dict[str, str]:
    base_ref = str(project.get("enforcement", {}).get("base_ref", "HEAD"))
    return {
        "revision": git_revision(root),
        "base_ref": base_ref,
        "change_fingerprint": change_fingerprint(root, base_ref),
        "control_fingerprint": control_fingerprint(root),
    }


def _scope_mismatches(
    payload: Mapping[str, Any], scope: Mapping[str, str], *, base: str
) -> list[str]:
    expected = {
        "revision": scope["revision"],
        base: scope["base_ref"],
        "change_fingerprint": scope["change_fingerprint"],
        "control_fingerprint": scope["control_fingerprint"],
    }
    return [name for name, value in expected.items() if payload.get(name) != value]


def _run_manifest(run: Mapping[str, Any], root: Path) -> dict[str, Any]:
    run_id = run.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        return {"verified": False, "errors": ["run has no valid run_id"]}
    result = verify_run_manifest(root / ".aqg" / "runs" / run_id)
    return {"verified": bool(result.get("ok")), "errors": list(result.get("errors", []))}


def _profile_evidence(
    root: Path, runs: list[dict[str, Any]], profile: str, scope: Mapping[str, str]
) -> dict[str, Any]:
    profile_runs = [run for run in runs if run.get("profile") == profile]
    current_runs = [
        run for run in profile_runs if not _scope_mismatches(run, scope, base="base_ref")
    ]
    if not current_runs:
        return {
            "profile": profile,
            "state": "missing" if not profile_runs else "stale",
            "run_id": None,
            "manifest_verified": False,
            "reasons": [
                "no run for this profile"
                if not profile_runs
                else "no run matches the current revision and fingerprints"
            ],
        }
    run = current_runs[0]
    manifest = _run_manifest(run, root)
    if not manifest["verified"]:
        return {
            "profile": profile,
            "state": "unverified",
            "run_id": run.get("run_id"),
            "manifest_verified": False,
            "reasons": manifest["errors"] or ["run manifest could not be verified"],
        }
    if run.get("status") != "pass":
        return {
            "profile": profile,
            "state": "current_failure",
            "run_id": run.get("run_id"),
            "manifest_verified": True,
            "reasons": [f"current {profile} run is {run.get('status', 'unknown')}"],
        }
    return {
        "profile": profile,
        "state": "current_pass",
        "run_id": run.get("run_id"),
        "manifest_verified": True,
        "reasons": [],
    }


def _stored_review(
    root: Path, scope: Mapping[str, str]
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    path = root / ".aqg" / "review" / "review.json"
    if not path.exists():
        return None, {"state": "missing", "reasons": ["no stored review packet"]}
    try:
        review = _as_mapping(read_json(path))
    except Exception as exc:
        return None, {"state": "invalid", "reasons": [str(exc)]}
    if not review:
        return None, {"state": "invalid", "reasons": ["review packet must be a JSON object"]}
    mismatches = _scope_mismatches(review, scope, base="base")
    if mismatches:
        return review, {
            "state": "stale",
            "reasons": [
                f"review {name} does not match the current candidate" for name in mismatches
            ],
        }
    summary = _as_mapping(review.get("summary"))
    blockers = int(summary.get("blockers", 0)) if str(summary.get("blockers", "")).isdigit() else 0
    prompts = (
        int(summary.get("human_review", 0)) if str(summary.get("human_review", "")).isdigit() else 0
    )
    return review, {
        "state": "current",
        "reasons": [],
        "blockers": blockers,
        "human_review": prompts,
        "generated_at": review.get("generated_at"),
    }


def _retrospective(runs: list[dict[str, Any]], scope: Mapping[str, str]) -> dict[str, Any]:
    current = [run for run in runs if not _scope_mismatches(run, scope, base="base_ref")]
    if not current:
        return {"state": "missing", "counts": {}, "certification": "unknown"}
    run = current[0]
    retrospective = _as_mapping(run.get("retrospective"))
    counts = _as_mapping(retrospective.get("counts"))
    required_counts = (
        "inherited_debt",
        "regressions",
        "new_debt",
        "invalid_debt",
        "missing_evidence",
        "configuration_errors",
        "infrastructure_errors",
        "unknown_product_intent",
    )
    malformed = [name for name in required_counts if not isinstance(counts.get(name, 0), int)]
    if malformed:
        return {
            "state": "invalid",
            "run_id": run.get("run_id"),
            "certification": retrospective.get("certification", "unknown"),
            "counts": counts,
            "reasons": [f"retrospective count {name} is not an integer" for name in malformed],
        }
    return {
        "state": "current",
        "run_id": run.get("run_id"),
        "certification": retrospective.get("certification", "unknown"),
        "counts": counts,
        "inherited_debt": int(counts.get("inherited_debt", 0) or 0),
        "regressions": int(counts.get("regressions", 0) or 0),
        "new_debt": int(counts.get("new_debt", 0) or 0),
        "invalid_debt": int(counts.get("invalid_debt", 0) or 0),
        "missing_evidence": int(counts.get("missing_evidence", 0) or 0),
        "configuration_errors": int(counts.get("configuration_errors", 0) or 0),
        "infrastructure_errors": int(counts.get("infrastructure_errors", 0) or 0),
        "unknown_product_intent": int(counts.get("unknown_product_intent", 0) or 0),
    }


def _reason(code: str, message: str, action: str) -> dict[str, str]:
    return {"code": code, "message": message, "action": action}


def _decision(state: str, reasons: list[dict[str, str]]) -> dict[str, Any]:
    return {"state": state, "reasons": reasons, "next_action": reasons[0] if reasons else None}


def _retrospective_reasons(retrospective: Mapping[str, Any]) -> list[dict[str, str]]:
    reasons: list[dict[str, str]] = []
    if retrospective.get("state") == "invalid":
        reasons.append(
            _reason(
                "retrospective_invalid",
                "; ".join(str(item) for item in retrospective.get("reasons", [])),
                "Repair the malformed retrospective evidence and rerun the required profile.",
            )
        )
        return reasons
    for key, label in (
        ("regressions", "new or worsened debt"),
        ("new_debt", "new debt"),
        ("invalid_debt", "invalid debt classification"),
        ("missing_evidence", "missing retrospective evidence"),
        ("configuration_errors", "retrospective configuration error"),
        ("infrastructure_errors", "retrospective infrastructure error"),
        ("unknown_product_intent", "unknown product intent"),
    ):
        if int(retrospective.get(key, 0) or 0):
            reasons.append(
                _reason(
                    key,
                    f"Retrospective evidence reports {retrospective[key]} {label} item(s).",
                    "Resolve and rerun the required profile; do not treat unknown or unusable evidence as a pass.",
                )
            )
    return reasons


def build_owner_status(root: Path) -> dict[str, Any]:
    """Build a deterministic, read-only owner decision for the current candidate."""
    root = Path(root)
    project = load_project(root)
    policy = load_policy(root)
    risk_errors, risk = risk_summary(root, policy, "quality/change-risk.json")
    scope = _scope(root, project)
    runs = list_runs(root, 100)
    latest = runs[0] if runs else None
    onboarding = current_onboarding(root)
    selected = str(risk.get("selected_risk_profile") or "standard")
    approvals = (
        validate_required_approvals(root, selected)
        if not risk_errors
        else {"required": [], "results": {}, "errors": risk_errors, "exit_code": 2}
    )
    review, review_freshness = _stored_review(root, scope)
    required_profiles = [str(profile) for profile in risk.get("required_execution_profiles", [])]
    evidence = [_profile_evidence(root, runs, profile, scope) for profile in required_profiles]
    retrospective = _retrospective(runs, scope)
    setup = _as_mapping(onboarding.get("current"))
    setup_summary = _as_mapping(setup.get("summary"))

    develop_reasons: list[dict[str, str]] = []
    if risk_errors:
        develop_reasons.append(
            _reason(
                "risk_invalid",
                "; ".join(str(error) for error in risk_errors),
                "Repair the change-risk card before guarded development.",
            )
        )
    if int(setup_summary.get("blockers", 0) or 0):
        next_action = _as_mapping(setup.get("next_action"))
        develop_reasons.append(
            _reason(
                "onboarding_blocked",
                f"{setup_summary.get('blockers')} onboarding blocker(s) remain.",
                str(next_action.get("next_step") or "Resolve the onboarding blocker."),
            )
        )
    develop = _decision("blocked" if develop_reasons else "allowed", develop_reasons)

    merge_reasons = [*develop_reasons]
    for item in evidence:
        if item["state"] != "current_pass":
            merge_reasons.append(
                _reason(
                    f"evidence_{item['profile']}_{item['state']}",
                    f"Required {item['profile']} evidence is {item['state'].replace('_', ' ')}: {'; '.join(item['reasons'])}",
                    f"Run `python3 quality/qg.py check {item['profile']} --keep-going` after the final change.",
                )
            )
    if review_freshness["state"] != "current":
        merge_reasons.append(
            _reason(
                f"review_{review_freshness['state']}",
                f"Review evidence is {review_freshness['state']}: {'; '.join(review_freshness['reasons'])}",
                "Generate a review packet after current deterministic evidence is available.",
            )
        )
    elif int(review_freshness.get("blockers", 0) or 0):
        merge_reasons.append(
            _reason(
                "review_blockers",
                f"Current review has {review_freshness['blockers']} blocker(s).",
                "Resolve review blockers and regenerate the review packet.",
            )
        )
    elif int(review_freshness.get("human_review", 0) or 0):
        merge_reasons.append(
            _reason(
                "human_review_required",
                f"Current review has {review_freshness['human_review']} human decision prompt(s).",
                "Obtain the required human product decision.",
            )
        )
    for error in approvals.get("errors", []):
        merge_reasons.append(
            _reason(
                "approval_missing_or_stale",
                str(error),
                "Complete the named human approval against the unchanged candidate.",
            )
        )
    merge_reasons.extend(_retrospective_reasons(retrospective))
    stage = enforcement_stage(project)
    if stage == "shadow":
        merge_reasons.append(
            _reason(
                "shadow_observations",
                "Shadow-stage evidence cannot certify a merge.",
                "Install a reviewed debt baseline and promote through the governed ratchet flow.",
            )
        )
    if merge_reasons:
        merge = _decision("blocked", merge_reasons)
    else:
        merge = _decision(
            "not_proven",
            [
                _reason(
                    "authoritative_ci_not_reported",
                    "Local AQG does not have current authoritative CI or branch-protection evidence.",
                    "Obtain the repository-hosted authoritative merge decision.",
                )
            ],
        )

    release_profile = _profile_evidence(root, runs, "release", scope)
    release_reasons = [*merge_reasons]
    if release_profile["state"] != "current_pass":
        release_reasons.insert(
            0,
            _reason(
                f"release_evidence_{release_profile['state']}",
                f"Release evidence is {release_profile['state'].replace('_', ' ')}: {'; '.join(release_profile['reasons'])}",
                "Run `python3 quality/qg.py check release --keep-going` for a release candidate.",
            ),
        )
    if selected != "critical":
        release_reasons.insert(
            0,
            _reason(
                "release_not_evaluated",
                "The current risk profile does not request a release decision.",
                "Start a release evaluation when a release candidate is proposed.",
            ),
        )
    if release_reasons:
        release = _decision("blocked", release_reasons)
    else:
        release = _decision(
            "not_proven",
            [
                _reason(
                    "release_authority_not_reported",
                    "Local AQG does not have current release-authority evidence.",
                    "Obtain the repository-hosted release decision.",
                )
            ],
        )

    all_decisions = (develop, merge, release)
    next_action = next(
        (decision["next_action"] for decision in all_decisions if decision["next_action"]),
        None,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "root": str(root),
        "project": project,
        "profiles": policy.get("profiles", {}),
        "risk_profiles": policy.get("risk_profiles", {}),
        "risk": risk,
        "risk_errors": risk_errors,
        "scope": scope,
        "latest": latest,
        "runs": runs,
        "onboarding": onboarding,
        "approvals": approvals,
        "review": review,
        "review_freshness": review_freshness,
        "evidence": evidence,
        "retrospective": retrospective,
        "council": {"state": "not_configured", "members": [], "quorum": None, "dissent": []},
        "authority": {"authoritative_ci": "not_reported", "branch_protection": "not_reported"},
        "decisions": {"develop": develop, "merge": merge, "release": release},
        "next_action": next_action,
    }
