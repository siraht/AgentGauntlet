# Feature-Spec: AgentQualityGauntlet AQG-CORE-025 AQG-CORE-028
"""Contracts for artifact-backed assurance and narrow human authority."""

from __future__ import annotations

from pathlib import Path

from aqg.assurance import (
    _authority_control,
    _council_errors,
    _validate_rehearsal_payload,
    evaluate_assurance,
)
from aqg.constants import INFRASTRUCTURE_ERROR, PASS, QUALITY_FAILURE


def _rehearsal() -> dict[str, object]:
    return {
        "schema_version": 2,
        "status": "pass",
        "functional_qa": {"status": "pass", "checks": ["CLI", "dashboard"]},
        "rollback": {"status": "pass", "restored_matches_before": True},
        "cleanup_verified": True,
    }


def test_functional_rehearsal_requires_executed_qa_rollback_and_cleanup() -> None:
    assert _validate_rehearsal_payload(_rehearsal()) == []
    payload = _rehearsal()
    payload["functional_qa"] = {"status": "pass", "checks": []}
    payload["rollback"] = {"status": "pass", "restored_matches_before": False}
    payload["cleanup_verified"] = False
    errors = _validate_rehearsal_payload(payload)
    assert any("checks" in error for error in errors)
    assert any("restored_matches_before" in error for error in errors)
    assert any("cleanup_verified" in error for error in errors)


def test_reserved_authority_is_distinct_from_broken_functionality() -> None:
    clear = _authority_control({"authority_triggers": {}})
    assert clear["status"] == "works"
    guarded = _authority_control({"authority_triggers": {"private_data_exposure": True}})
    assert guarded["status"] == "human_decision_needed"
    assert guarded["active"] == ["private_data_exposure"]


def test_high_council_must_be_exact_complete_clear_and_diverse() -> None:
    scope = {
        "revision": "abc",
        "base_ref": "base",
        "change_fingerprint": "sha256:change",
        "control_fingerprint": "sha256:control",
    }
    report = {
        "scope": {
            "revision": "abc",
            "base_revision": "base",
            "change_fingerprint": "sha256:change",
            "control_fingerprint": "sha256:control",
        },
        "tier": "high",
        "status": "advisory_clear",
        "complete": True,
        "covered_roles": [
            "requirements_behavior",
            "test_evidence",
            "security_trust",
            "operability_rollback",
        ],
        "provider_groups": ["one", "two", "three"],
        "dissent": {"present": False},
        "blockers": [],
        "incomplete_reasons": [],
        "verification": {"ok": True},
    }
    assert _council_errors(report, scope) == []
    report["dissent"] = {"present": True}
    report["provider_groups"] = ["one"]
    errors = _council_errors(report, scope)
    assert any("dissent" in error for error in errors)
    assert any("provider groups" in error for error in errors)


def test_assurance_fails_closed_without_profile_owned_behavior_evidence(
    tmp_path: Path,
) -> None:
    (tmp_path / "quality").mkdir()
    project = {
        "enforcement": {"base_ref": "HEAD"},
        "gates": {
            "acceptance": {"applicable": True},
            "review": {"applicable": True},
            "mutation_acceptance": {"applicable": True},
        },
    }
    risk = {
        "selected_risk_profile": "standard",
        "card": {"authority_triggers": {}},
    }
    code, report = evaluate_assurance(tmp_path, project, risk, run_id=None)
    assert code == INFRASTRUCTURE_ERROR
    assert report["controls"]["behavior"]["status"] == "unusable"


def test_exit_semantics_remain_pass_quality_and_infrastructure() -> None:
    from aqg.assurance import _exit_code

    assert _exit_code({"proof": {"status": "works"}}) == PASS
    assert _exit_code({"proof": {"status": "broken"}}) == QUALITY_FAILURE
    assert _exit_code({"proof": {"status": "human_decision_needed"}}) == QUALITY_FAILURE
    assert _exit_code({"proof": {"status": "not_tested"}}) == INFRASTRUCTURE_ERROR
    assert _exit_code({"proof": {"status": "unusable"}}) == INFRASTRUCTURE_ERROR
