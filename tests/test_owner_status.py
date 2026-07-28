# Feature-Spec: AgentQualityGauntlet.OwnerStatus AQG-OWNER-001 AQG-OWNER-002
# Feature-Spec: AgentQualityGauntlet.OwnerStatus AQG-OWNER-003 AQG-OWNER-004
# Feature-Spec: AgentQualityGauntlet.OwnerStatus AQG-OWNER-005 AQG-OWNER-006 AQG-OWNER-007
"""Owner readiness projection contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aqg import owner_status
from aqg.util import write_json


def _run(*, profile: str = "deep", retrospective: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "run_id": f"{profile}-run",
        "profile": profile,
        "status": "pass",
        "revision": "revision",
        "base_ref": "main",
        "change_fingerprint": "change",
        "control_fingerprint": "control",
        "retrospective": retrospective or {"certification": "regression_free", "counts": {}},
    }


def _review() -> dict[str, Any]:
    return {
        "schema_version": 3,
        "revision": "revision",
        "base": "main",
        "change_fingerprint": "change",
        "control_fingerprint": "control",
        "generated_at": "2026-07-28T00:00:00+00:00",
        "summary": {"blockers": 0, "human_review": 0},
    }


@pytest.fixture
def status_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> dict[str, list[dict[str, Any]]]:
    runs = [_run()]
    monkeypatch.setattr(
        owner_status,
        "load_project",
        lambda root: {
            "name": "owner-status",
            "enforcement": {"base_ref": "main", "stage": "ratchet"},
        },
    )
    monkeypatch.setattr(owner_status, "load_policy", lambda root: {"profiles": {}})
    monkeypatch.setattr(
        owner_status,
        "risk_summary",
        lambda root, policy, card: (
            [],
            {"selected_risk_profile": "high_assurance", "required_execution_profiles": ["deep"]},
        ),
    )
    monkeypatch.setattr(owner_status, "git_revision", lambda root: "revision")
    monkeypatch.setattr(owner_status, "change_fingerprint", lambda root, base: "change")
    monkeypatch.setattr(owner_status, "control_fingerprint", lambda root: "control")
    monkeypatch.setattr(owner_status, "list_runs", lambda root, limit: runs)
    monkeypatch.setattr(
        owner_status,
        "current_onboarding",
        lambda root: {
            "current": {"summary": {"blockers": 0, "ready_for_guarded_use": True}},
            "stale": False,
        },
    )
    monkeypatch.setattr(
        owner_status,
        "validate_required_approvals",
        lambda root, risk: {"required": [], "results": {}, "errors": [], "exit_code": 0},
    )
    monkeypatch.setattr(
        owner_status, "verify_run_manifest", lambda path: {"ok": True, "errors": []}
    )
    return {"runs": runs}


def _write_review(root: Path, payload: dict[str, Any] | None = None) -> None:
    write_json(root / ".aqg" / "review" / "review.json", payload or _review())


def _codes(decision: dict[str, Any]) -> set[str]:
    return {str(item["code"]) for item in decision["reasons"]}


def test_current_verified_evidence_is_shared_but_merge_never_invents_authority(
    status_inputs: dict[str, list[dict[str, Any]]], tmp_path: Path
) -> None:
    """AQG-OWNER-001/002/003: local evidence cannot fabricate a merge approval."""
    _write_review(tmp_path)

    payload = owner_status.build_owner_status(tmp_path)

    assert payload["schema_version"] == 1
    assert payload["evidence"] == [
        {
            "profile": "deep",
            "state": "current_pass",
            "run_id": "deep-run",
            "manifest_verified": True,
            "reasons": [],
        }
    ]
    assert payload["decisions"]["develop"]["state"] == "allowed"
    assert payload["decisions"]["merge"]["state"] == "not_proven"
    assert _codes(payload["decisions"]["merge"]) == {"authoritative_ci_not_reported"}
    assert payload["decisions"]["release"]["state"] == "blocked"


def test_unverified_current_manifest_blocks_merge(
    status_inputs: dict[str, list[dict[str, Any]]], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AQG-OWNER-003: a current run without a valid manifest is never fresh evidence."""
    _write_review(tmp_path)
    monkeypatch.setattr(
        owner_status,
        "verify_run_manifest",
        lambda path: {"ok": False, "errors": ["modified evidence: summary.json"]},
    )

    payload = owner_status.build_owner_status(tmp_path)

    assert payload["evidence"][0]["state"] == "unverified"
    assert payload["evidence"][0]["manifest_verified"] is False
    assert payload["decisions"]["merge"]["state"] == "blocked"
    assert "evidence_deep_unverified" in _codes(payload["decisions"]["merge"])


def test_stored_review_with_wrong_candidate_fingerprint_is_stale(
    status_inputs: dict[str, list[dict[str, Any]]], tmp_path: Path
) -> None:
    """AQG-OWNER-004: a stored review must match the exact current candidate."""
    review = _review()
    review["change_fingerprint"] = "old-change"
    _write_review(tmp_path, review)

    payload = owner_status.build_owner_status(tmp_path)

    assert payload["review_freshness"]["state"] == "stale"
    assert "review_stale" in _codes(payload["decisions"]["merge"])


def test_inherited_debt_remains_visible_without_becoming_a_regression(
    status_inputs: dict[str, list[dict[str, Any]]], tmp_path: Path
) -> None:
    """AQG-OWNER-005: inherited debt and new regressions have different owner effects."""
    _write_review(tmp_path)
    status_inputs["runs"][:] = [
        _run(
            retrospective={
                "certification": "regression_free",
                "counts": {"inherited_debt": 2, "regressions": 0},
            }
        )
    ]

    inherited = owner_status.build_owner_status(tmp_path)

    assert inherited["retrospective"]["inherited_debt"] == 2
    assert inherited["retrospective"]["regressions"] == 0
    assert inherited["decisions"]["merge"]["state"] == "not_proven"
    status_inputs["runs"][:] = [
        _run(
            retrospective={
                "certification": "not_regression_free",
                "counts": {"inherited_debt": 2, "regressions": 1},
            }
        )
    ]

    regressed = owner_status.build_owner_status(tmp_path)

    assert regressed["decisions"]["merge"]["state"] == "blocked"
    assert "regressions" in _codes(regressed["decisions"]["merge"])


def test_missing_council_is_explicit_and_next_action_is_deterministic(
    status_inputs: dict[str, list[dict[str, Any]]], tmp_path: Path
) -> None:
    """AQG-OWNER-006/007: missing council evidence is explicit and action order is stable."""
    status_inputs["runs"][:] = []

    first = owner_status.build_owner_status(tmp_path)
    second = owner_status.build_owner_status(tmp_path)

    assert first["council"]["state"] == "not_configured"
    assert first["next_action"] == second["next_action"]
    assert first["next_action"]["code"] == "evidence_deep_missing"


def test_verified_current_council_is_visible_but_does_not_invent_authority(
    status_inputs: dict[str, list[dict[str, Any]]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AQG-OWNER-006: current agent advice is visible without becoming approval."""
    _write_review(tmp_path)
    latest = tmp_path / ".aqg" / "council" / "latest.json"
    latest.parent.mkdir(parents=True)
    latest.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        owner_status,
        "report_council",
        lambda root: {
            "run_id": "council-current",
            "scope": {
                "revision": "revision",
                "base_revision": "main",
                "change_fingerprint": "change",
                "control_fingerprint": "control",
            },
            "status": "advisory_clear",
            "members": [{"role": "test_evidence"}],
            "provider_groups": ["one", "two", "three"],
            "dissent": {"present": False},
        },
    )

    payload = owner_status.build_owner_status(tmp_path)

    assert payload["council"]["state"] == "current"
    assert payload["council"]["status"] == "advisory_clear"
    assert payload["decisions"]["merge"]["state"] == "not_proven"
    assert _codes(payload["decisions"]["merge"]) == {"authoritative_ci_not_reported"}


def test_council_for_another_candidate_is_stale(
    status_inputs: dict[str, list[dict[str, Any]]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AQG-OWNER-006: council advice is exact-candidate evidence."""
    latest = tmp_path / ".aqg" / "council" / "latest.json"
    latest.parent.mkdir(parents=True)
    latest.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        owner_status,
        "report_council",
        lambda root: {
            "scope": {
                "revision": "old-revision",
                "base_revision": "main",
                "change_fingerprint": "old-change",
                "control_fingerprint": "control",
            },
            "status": "advisory_clear",
            "members": [],
            "provider_groups": [],
            "dissent": {"present": False},
        },
    )

    payload = owner_status.build_owner_status(tmp_path)

    assert payload["council"]["state"] == "stale"
    assert len(payload["council"]["reasons"]) == 2
