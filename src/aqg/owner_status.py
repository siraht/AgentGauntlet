"""Read-only, fail-closed owner readiness model shared by AQG surfaces."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .approvals import validate_required_approvals
from .council_service import report_council
from .errors import ConfigurationError
from .evidence_manifest import verify_run_manifest
from .policy import load_policy, risk_summary
from .project import load_project
from .promotion import enforcement_stage
from .runner import list_runs
from .scaffold import current_onboarding
from .util import change_fingerprint, control_fingerprint, git_revision, read_json, utc_now

SCHEMA_VERSION = 1
RETROSPECTIVE_COUNTS = (
    "inherited_debt",
    "regressions",
    "new_debt",
    "invalid_debt",
    "missing_evidence",
    "configuration_errors",
    "infrastructure_errors",
    "unknown_product_intent",
)
RETROSPECTIVE_BLOCKERS = (
    ("regressions", "new or worsened debt"),
    ("new_debt", "new debt"),
    ("invalid_debt", "invalid debt classification"),
    ("missing_evidence", "missing retrospective evidence"),
    ("configuration_errors", "retrospective configuration error"),
    ("infrastructure_errors", "retrospective infrastructure error"),
    ("unknown_product_intent", "unknown product intent"),
)


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _integer(value: Any) -> int:
    return value if isinstance(value, int) else 0


def _reason(code: str, message: str, action: str) -> dict[str, str]:
    return {"code": code, "message": message, "action": action}


def _decision(state: str, reasons: list[dict[str, str]]) -> dict[str, Any]:
    return {"state": state, "reasons": reasons, "next_action": reasons[0] if reasons else None}


def _scope(root: Path, project: Mapping[str, Any]) -> dict[str, str]:
    base_ref = os.environ.get("AQG_DIFF_BASE") or str(
        project.get("enforcement", {}).get("base_ref", "HEAD")
    )
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


def _evidence_record(
    profile: str, state: str, run: Mapping[str, Any] | None, verified: bool, reasons: list[str]
) -> dict[str, Any]:
    return {
        "profile": profile,
        "state": state,
        "run_id": run.get("run_id") if run else None,
        "manifest_verified": verified,
        "reasons": reasons,
    }


def _missing_profile_evidence(profile: str, profile_runs: list[dict[str, Any]]) -> dict[str, Any]:
    state = "missing" if not profile_runs else "stale"
    reason = (
        "no run for this profile"
        if not profile_runs
        else "no run matches the current revision and fingerprints"
    )
    return _evidence_record(profile, state, None, False, [reason])


def _current_profile_evidence(root: Path, profile: str, run: Mapping[str, Any]) -> dict[str, Any]:
    manifest = _run_manifest(run, root)
    if not manifest["verified"]:
        return _evidence_record(
            profile,
            "unverified",
            run,
            False,
            manifest["errors"] or ["run manifest could not be verified"],
        )
    if run.get("status") != "pass":
        return _evidence_record(
            profile,
            "current_failure",
            run,
            True,
            [f"current {profile} run is {run.get('status', 'unknown')}"],
        )
    return _evidence_record(profile, "current_pass", run, True, [])


def _profile_evidence(
    root: Path, runs: list[dict[str, Any]], profile: str, scope: Mapping[str, str]
) -> dict[str, Any]:
    profile_runs = [run for run in runs if run.get("profile") == profile]
    current = [run for run in profile_runs if not _scope_mismatches(run, scope, base="base_ref")]
    if not current:
        return _missing_profile_evidence(profile, profile_runs)
    return _current_profile_evidence(root, profile, current[0])


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
    return review, _review_freshness(review, scope)


def _review_freshness(review: Mapping[str, Any], scope: Mapping[str, str]) -> dict[str, Any]:
    mismatches = _scope_mismatches(review, scope, base="base")
    if mismatches:
        return {
            "state": "stale",
            "reasons": [
                f"review {name} does not match the current candidate" for name in mismatches
            ],
        }
    summary = _as_mapping(review.get("summary"))
    return {
        "state": "current",
        "reasons": [],
        "blockers": _integer(summary.get("blockers")),
        "human_review": _integer(summary.get("human_review")),
        "generated_at": review.get("generated_at"),
    }


def _current_run(runs: list[dict[str, Any]], scope: Mapping[str, str]) -> dict[str, Any] | None:
    return next((run for run in runs if not _scope_mismatches(run, scope, base="base_ref")), None)


def _retrospective_payload(run: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    retrospective = _as_mapping(run.get("retrospective"))
    return retrospective, _as_mapping(retrospective.get("counts"))


def _invalid_retrospective(
    run: Mapping[str, Any], retrospective: Mapping[str, Any], counts: Mapping[str, Any]
) -> dict[str, Any] | None:
    malformed = [name for name in RETROSPECTIVE_COUNTS if not isinstance(counts.get(name, 0), int)]
    if not malformed:
        return None
    return {
        "state": "invalid",
        "run_id": run.get("run_id"),
        "certification": retrospective.get("certification", "unknown"),
        "counts": counts,
        "reasons": [f"retrospective count {name} is not an integer" for name in malformed],
    }


def _valid_retrospective(
    run: Mapping[str, Any], retrospective: Mapping[str, Any], counts: Mapping[str, Any]
) -> dict[str, Any]:
    payload = {
        "state": "current",
        "run_id": run.get("run_id"),
        "certification": retrospective.get("certification", "unknown"),
        "counts": counts,
    }
    payload.update({name: counts.get(name, 0) for name in RETROSPECTIVE_COUNTS})
    return payload


def _retrospective(runs: list[dict[str, Any]], scope: Mapping[str, str]) -> dict[str, Any]:
    run = _current_run(runs, scope)
    if run is None:
        return {"state": "missing", "counts": {}, "certification": "unknown"}
    retrospective, counts = _retrospective_payload(run)
    return _invalid_retrospective(run, retrospective, counts) or _valid_retrospective(
        run, retrospective, counts
    )


def _retrospective_reasons(retrospective: Mapping[str, Any]) -> list[dict[str, str]]:
    if retrospective.get("state") == "invalid":
        return [_invalid_retrospective_reason(retrospective)]
    return [
        _retrospective_reason(key, label, retrospective[key])
        for key, label in RETROSPECTIVE_BLOCKERS
        if _integer(retrospective.get(key))
    ]


def _invalid_retrospective_reason(retrospective: Mapping[str, Any]) -> dict[str, str]:
    return _reason(
        "retrospective_invalid",
        "; ".join(str(item) for item in retrospective.get("reasons", [])),
        "Repair the malformed retrospective evidence and rerun the required profile.",
    )


def _retrospective_reason(key: str, label: str, count: int) -> dict[str, str]:
    return _reason(
        key,
        f"Retrospective evidence reports {count} {label} item(s).",
        "Resolve and rerun the required profile; do not treat unknown or unusable evidence as a pass.",
    )


def _base_context(root: Path) -> dict[str, Any]:
    project = load_project(root)
    policy = load_policy(root)
    risk_errors, risk = risk_summary(root, policy, "quality/change-risk.json")
    runs = list_runs(root, 100)
    return {
        "root": root,
        "project": project,
        "policy": policy,
        "risk": risk,
        "risk_errors": risk_errors,
        "scope": _scope(root, project),
        "runs": runs,
        "latest": runs[0] if runs else None,
        "onboarding": current_onboarding(root),
    }


def _owner_context(root: Path) -> dict[str, Any]:
    context = _base_context(root)
    risk = context["risk"]
    selected = str(risk.get("selected_risk_profile") or "standard")
    context["approvals"] = _approvals(root, selected, context["risk_errors"])
    review, freshness = _stored_review(root, context["scope"])
    context["review"] = review
    context["review_freshness"] = freshness
    profiles = [str(profile) for profile in risk.get("required_execution_profiles", [])]
    context["evidence"] = [
        _profile_evidence(root, context["runs"], name, context["scope"]) for name in profiles
    ]
    context["retrospective"] = _retrospective(context["runs"], context["scope"])
    context["council"] = _council_status(root, context["scope"])
    return context


def _council_status(root: Path, scope: Mapping[str, str]) -> dict[str, Any]:
    latest = root / ".aqg" / "council" / "latest.json"
    if not latest.exists():
        return {"state": "not_configured", "members": [], "quorum": None, "dissent": []}
    try:
        report = report_council(root)
    except (ConfigurationError, OSError) as exc:
        return {"state": "invalid", "members": [], "quorum": None, "dissent": [], "error": str(exc)}
    council_scope = _as_mapping(report.get("scope"))
    expected = {
        "revision": scope["revision"],
        "base_revision": scope["base_ref"],
        "change_fingerprint": scope["change_fingerprint"],
        "control_fingerprint": scope["control_fingerprint"],
    }
    mismatches = [name for name, value in expected.items() if council_scope.get(name) != value]
    if mismatches:
        return {
            **report,
            "state": "stale",
            "reasons": [
                f"council {name} does not match the current candidate" for name in mismatches
            ],
        }
    return {**report, "state": "current"}


def _approvals(root: Path, selected: str, risk_errors: list[str]) -> dict[str, Any]:
    if risk_errors:
        return {"required": [], "results": {}, "errors": risk_errors, "exit_code": 2}
    return validate_required_approvals(root, selected)


def _develop_reasons(context: Mapping[str, Any]) -> list[dict[str, str]]:
    reasons = _risk_reasons(context["risk_errors"])
    onboarding = _as_mapping(context["onboarding"].get("current"))
    summary = _as_mapping(onboarding.get("summary"))
    if _integer(summary.get("blockers")):
        reasons.append(_onboarding_reason(onboarding, summary["blockers"]))
    return reasons


def _risk_reasons(errors: list[str]) -> list[dict[str, str]]:
    if not errors:
        return []
    return [
        _reason(
            "risk_invalid",
            "; ".join(str(error) for error in errors),
            "Repair the change-risk card before guarded development.",
        )
    ]


def _onboarding_reason(onboarding: Mapping[str, Any], blockers: int) -> dict[str, str]:
    next_action = _as_mapping(onboarding.get("next_action"))
    return _reason(
        "onboarding_blocked",
        f"{blockers} onboarding blocker(s) remain.",
        str(next_action.get("next_step") or "Resolve the onboarding blocker."),
    )


def _evidence_reasons(evidence: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [_evidence_reason(item) for item in evidence if item["state"] != "current_pass"]


def _evidence_reason(item: Mapping[str, Any]) -> dict[str, str]:
    profile = str(item["profile"])
    state = str(item["state"])
    return _reason(
        f"evidence_{profile}_{state}",
        f"Required {profile} evidence is {state.replace('_', ' ')}: {'; '.join(item['reasons'])}",
        f"Run `python3 quality/qg.py check {profile} --keep-going` after the final change.",
    )


def _review_reasons(freshness: Mapping[str, Any]) -> list[dict[str, str]]:
    if freshness["state"] != "current":
        return [_stale_review_reason(freshness)]
    if _integer(freshness.get("blockers")):
        return [_review_blocker_reason(freshness["blockers"])]
    if _integer(freshness.get("human_review")):
        return [_human_review_reason(freshness["human_review"])]
    return []


def _stale_review_reason(freshness: Mapping[str, Any]) -> dict[str, str]:
    return _reason(
        f"review_{freshness['state']}",
        f"Review evidence is {freshness['state']}: {'; '.join(freshness['reasons'])}",
        "Generate a review packet after current deterministic evidence is available.",
    )


def _review_blocker_reason(blockers: int) -> dict[str, str]:
    return _reason(
        "review_blockers",
        f"Current review has {blockers} blocker(s).",
        "Resolve review blockers and regenerate the review packet.",
    )


def _human_review_reason(prompts: int) -> dict[str, str]:
    return _reason(
        "human_review_required",
        f"Current review has {prompts} human decision prompt(s).",
        "Obtain the required human product decision.",
    )


def _approval_reasons(approvals: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        _reason(
            "approval_missing_or_stale",
            str(error),
            "Complete the named human approval against the unchanged candidate.",
        )
        for error in approvals.get("errors", [])
    ]


def _shadow_reason(project: Mapping[str, Any]) -> list[dict[str, str]]:
    if enforcement_stage(dict(project)) != "shadow":
        return []
    return [
        _reason(
            "shadow_observations",
            "Shadow-stage evidence cannot certify a merge.",
            "Install a reviewed debt baseline and promote through the governed ratchet flow.",
        )
    ]


def _merge_reasons(context: Mapping[str, Any], develop: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        *develop["reasons"],
        *_evidence_reasons(context["evidence"]),
        *_review_reasons(context["review_freshness"]),
        *_approval_reasons(context["approvals"]),
        *_retrospective_reasons(context["retrospective"]),
        *_shadow_reason(context["project"]),
    ]


def _merge_decision(reasons: list[dict[str, str]]) -> dict[str, Any]:
    if reasons:
        return _decision("blocked", reasons)
    return _decision(
        "not_proven",
        [
            _reason(
                "authoritative_ci_not_reported",
                "Local AQG does not have current authoritative CI or branch-protection evidence.",
                "Obtain the repository-hosted authoritative merge decision.",
            )
        ],
    )


def _release_reasons(
    context: Mapping[str, Any], merge_reasons: list[dict[str, str]]
) -> list[dict[str, str]]:
    release = _profile_evidence(context["root"], context["runs"], "release", context["scope"])
    reasons = [*merge_reasons]
    if release["state"] != "current_pass":
        reasons.insert(0, _release_evidence_reason(release))
    if context["risk"].get("selected_risk_profile") != "critical":
        reasons.insert(0, _release_not_evaluated_reason())
    return reasons


def _release_evidence_reason(release: Mapping[str, Any]) -> dict[str, str]:
    state = str(release["state"])
    return _reason(
        f"release_evidence_{state}",
        f"Release evidence is {state.replace('_', ' ')}: {'; '.join(release['reasons'])}",
        "Run `python3 quality/qg.py check release --keep-going` for a release candidate.",
    )


def _release_not_evaluated_reason() -> dict[str, str]:
    return _reason(
        "release_not_evaluated",
        "The current risk profile does not request a release decision.",
        "Start a release evaluation when a release candidate is proposed.",
    )


def _release_decision(reasons: list[dict[str, str]]) -> dict[str, Any]:
    if reasons:
        return _decision("blocked", reasons)
    return _decision(
        "not_proven",
        [
            _reason(
                "release_authority_not_reported",
                "Local AQG does not have current release-authority evidence.",
                "Obtain the repository-hosted release decision.",
            )
        ],
    )


def _decisions(context: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    develop_reasons = _develop_reasons(context)
    develop = _decision("blocked" if develop_reasons else "allowed", develop_reasons)
    merge_reasons = _merge_reasons(context, develop)
    merge = _merge_decision(merge_reasons)
    release = _release_decision(_release_reasons(context, merge_reasons))
    return {"develop": develop, "merge": merge, "release": release}


def _next_action(decisions: Mapping[str, Mapping[str, Any]]) -> dict[str, str] | None:
    ordered = (decisions["develop"], decisions["merge"], decisions["release"])
    return next((decision["next_action"] for decision in ordered if decision["next_action"]), None)


def _owner_payload(
    context: Mapping[str, Any], decisions: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    policy = context["policy"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "root": str(context["root"]),
        "project": context["project"],
        "profiles": policy.get("profiles", {}),
        "risk_profiles": policy.get("risk_profiles", {}),
        "risk": context["risk"],
        "risk_errors": context["risk_errors"],
        "scope": context["scope"],
        "latest": context["latest"],
        "runs": context["runs"],
        "onboarding": context["onboarding"],
        "approvals": context["approvals"],
        "review": context["review"],
        "review_freshness": context["review_freshness"],
        "evidence": context["evidence"],
        "retrospective": context["retrospective"],
        "council": context["council"],
        "authority": {"authoritative_ci": "not_reported", "branch_protection": "not_reported"},
        "decisions": decisions,
        "next_action": _next_action(decisions),
    }


def build_owner_status(root: Path) -> dict[str, Any]:
    """Build a deterministic, read-only owner decision for the current candidate."""
    context = _owner_context(Path(root))
    return _owner_payload(context, _decisions(context))
