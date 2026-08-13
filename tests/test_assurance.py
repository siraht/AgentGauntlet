# Feature-Spec: AgentQualityGauntlet AQG-CORE-025 AQG-CORE-028
"""Contracts for artifact-backed assurance and narrow human authority."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import aqg.assurance as assurance
from aqg.assurance import (
    _add_high_assurance_controls,
    _assurance_result,
    _authority_control,
    _council_errors,
    _execution_evidence,
    _functional_qa_errors,
    _independent_control,
    _load_rehearsal_output,
    _manual_qa_control,
    _manual_qa_errors,
    _qa_checks_errors,
    _qa_procedure_errors,
    _rehearsal_control,
    _validate_rehearsal_payload,
    evaluate_assurance,
)
from aqg.constants import INFRASTRUCTURE_ERROR, PASS, QUALITY_FAILURE
from aqg.util import CommandResult


def _identity(payload: dict[str, object]) -> str:
    stable = dict(payload)
    stable.pop("result_identity", None)
    stable.pop("durations_ms", None)
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _rehearsal() -> dict[str, object]:
    evidence = {
        "cold_start": {"bare_help": 0},
        "setup": {"exit_code": 0},
        "review": {"findings": 0},
        "conformance": {"passed": 1},
        "dashboard": {"checks": ["GET /=200"]},
        "tui": {"exit_code": 0},
    }
    payload: dict[str, object] = {
        "schema_version": 2,
        "evidence_type": "aqg.functional-rehearsal",
        "status": "pass",
        "candidate": {
            "revision": "a" * 40,
            "dirty": False,
            "source_tree_sha256": "b" * 64,
            "material_count": 3,
        },
        "result_identity": "",
        "durations_ms": {
            "total": 7,
            "cold_start": 1,
            "setup": 1,
            "commands": 1,
            "dashboard": 1,
            "tui": 1,
            "rollback": 1,
        },
        "cleanup": {"method": "TemporaryDirectory", "temporary_workspace_removed": True},
        "cold_start": evidence["cold_start"],
        "setup": evidence["setup"],
        "functional_qa": {
            "status": "pass",
            "procedure": {
                "id": "QA-AQG-CONTROL-SURFACES-001",
                "path": "qa/procedures/control-surface-rehearsal.md",
                "execution_mode": "agent-operated executable procedure",
                "executor": "aqg deterministic rehearsal",
            },
            "checks": list(evidence),
            "evidence": evidence,
        },
        "rollback": {
            "status": "pass",
            "mechanism": "content-addressed-copy-into-fresh-root",
            "before_identity": "sha256:" + "c" * 64,
            "candidate_identity": "sha256:" + "d" * 64,
            "restored_identity": "sha256:" + "c" * 64,
            "candidate_changed": True,
            "restored_matches_before": True,
            "operation_outputs_equal": True,
        },
        "cleanup_verified": True,
    }
    payload["result_identity"] = _identity(payload)
    return payload


def _command_result(code: int, status: str) -> CommandResult:
    return CommandResult(
        command=["rehearse"],
        cwd="/candidate",
        code=code,
        status=status,
        stdout="",
        stderr="",
        duration_ms=1,
    )


def test_rehearsal_output_distinguishes_failure_missing_invalid_and_valid(tmp_path: Path) -> None:
    output = tmp_path / "rehearsal.json"
    quality_result = _command_result(QUALITY_FAILURE, "quality_failure")
    payload, failure = _load_rehearsal_output(output, quality_result)
    assert payload is None
    assert failure == {
        "status": "broken",
        "command": quality_result.as_dict(),
        "errors": ["quality_failure"],
    }

    infrastructure_result = _command_result(INFRASTRUCTURE_ERROR, "infrastructure_error")
    payload, failure = _load_rehearsal_output(output, infrastructure_result)
    assert payload is None
    assert failure == {
        "status": "unusable",
        "command": infrastructure_result.as_dict(),
        "errors": ["infrastructure_error"],
    }

    pass_result = _command_result(PASS, "pass")
    payload, failure = _load_rehearsal_output(output, pass_result)
    assert payload is None
    assert failure == {
        "status": "unusable",
        "command": pass_result.as_dict(),
        "errors": ["rehearsal command produced no output"],
    }

    output.write_text("not json", encoding="utf-8")
    payload, failure = _load_rehearsal_output(output, _command_result(PASS, "pass"))
    assert payload is None
    assert failure == {
        "status": "unusable",
        "command": pass_result.as_dict(),
        "errors": [f"invalid JSON in {output}: Expecting value: line 1 column 1 (char 0)"],
    }

    output.write_text('{"status":"pass"}', encoding="utf-8")
    assert _load_rehearsal_output(output, _command_result(PASS, "pass")) == (
        {"status": "pass"},
        None,
    )


def test_execution_evidence_is_exact_and_content_addressed(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    output.write_bytes(b'{"result":"pass"}')
    payload = {"result_identity": "sha256:" + "a" * 64}
    expected = {
        "purpose": "manual-qa",
        "producer": "aqg assurance executor",
        "operator": "agent",
        "started_at": "2026-08-13T01:02:03+00:00",
        "finished_at": "2026-08-13T01:02:04+00:00",
        "artifact_sha256": "sha256:" + hashlib.sha256(output.read_bytes()).hexdigest(),
        "result_identity": payload["result_identity"],
    }
    expected["execution_identity"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )

    assert (
        _execution_evidence(
            output,
            payload,
            "manual-qa",
            "2026-08-13T01:02:03+00:00",
            "2026-08-13T01:02:04+00:00",
        )
        == expected
    )


def test_rehearsal_control_executes_fresh_artifact_and_binds_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / ".aqg" / "work" / "assurance" / "manual.json"
    output.parent.mkdir(parents=True)
    output.write_text("stale", encoding="utf-8")
    payload = _rehearsal()

    def execute(command: list[str], *, cwd: Path, timeout: int) -> CommandResult:
        assert str(output) in command
        assert not output.exists()
        assert cwd == tmp_path
        assert timeout == 37
        output.write_text(json.dumps(payload), encoding="utf-8")
        return _command_result(PASS, "pass")

    monkeypatch.setattr(assurance, "run_command", execute)

    def revision(root: Path) -> str:
        assert root == tmp_path
        return "a" * 40

    def dirty(root: Path) -> bool:
        assert root == tmp_path
        return False

    monkeypatch.setattr(assurance, "git_revision", revision)
    monkeypatch.setattr(assurance, "_candidate_dirty", dirty)
    times = iter(["2026-08-13T01:02:03+00:00", "2026-08-13T01:02:04+00:00"])
    monkeypatch.setattr(assurance, "utc_now", lambda: next(times))

    control = _rehearsal_control(
        tmp_path,
        {
            "assurance": {
                "rehearsal_command": ["rehearse", "{output}"],
                "timeout_seconds": 37,
            }
        },
        artifact_name="manual.json",
        execution_purpose="manual-qa",
    )

    artifact_digest = "sha256:" + hashlib.sha256(output.read_bytes()).hexdigest()
    execution = {
        "purpose": "manual-qa",
        "producer": "aqg assurance executor",
        "operator": "agent",
        "started_at": "2026-08-13T01:02:03+00:00",
        "finished_at": "2026-08-13T01:02:04+00:00",
        "artifact_sha256": artifact_digest,
        "result_identity": payload["result_identity"],
    }
    execution["execution_identity"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(execution, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    assert control == {
        "status": "works",
        "command": _command_result(PASS, "pass").as_dict(),
        "artifact": ".aqg/work/assurance/manual.json",
        "execution": execution,
        "result": payload,
        "errors": [],
    }


def test_rehearsal_control_fails_closed_for_missing_or_invalid_configuration(
    tmp_path: Path,
) -> None:
    missing = _rehearsal_control(tmp_path, {})
    assert missing == {
        "status": "not_tested",
        "errors": ["quality/project.json has no assurance rehearsal configuration"],
    }
    invalid = _rehearsal_control(tmp_path, {"assurance": {"rehearsal_command": ["rehearse"]}})
    assert invalid["status"] == "unusable"
    assert invalid["errors"] == ["assurance.rehearsal_command must contain {output}"]


def test_rehearsal_control_defaults_timeout_artifact_and_purpose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _rehearsal()

    def execute(command: list[str], *, cwd: Path, timeout: int) -> CommandResult:
        output = Path(command[-1])
        assert cwd == tmp_path
        assert timeout == 600
        assert output.name == "functional-rehearsal.json"
        output.write_text(json.dumps(payload), encoding="utf-8")
        return _command_result(PASS, "pass")

    monkeypatch.setattr(assurance, "run_command", execute)
    monkeypatch.setattr(assurance, "git_revision", lambda _root: "a" * 40)
    monkeypatch.setattr(assurance, "_candidate_dirty", lambda _root: False)
    monkeypatch.setattr(assurance, "utc_now", lambda: "2026-08-13T01:02:03+00:00")

    control = _rehearsal_control(
        tmp_path,
        {"assurance": {"rehearsal_command": ["rehearse", "{output}"]}},
    )

    assert control["artifact"] == ".aqg/work/assurance/functional-rehearsal.json"
    assert control["execution"]["purpose"] == "functional-rehearsal"


def test_rehearsal_control_binds_candidate_validation_and_reports_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _rehearsal()

    def execute(command: list[str], **_kwargs: object) -> CommandResult:
        Path(command[-1]).write_text(json.dumps(payload), encoding="utf-8")
        return _command_result(PASS, "pass")

    validate = Mock(return_value=["candidate mismatch"])
    monkeypatch.setattr(assurance, "run_command", execute)
    monkeypatch.setattr(assurance, "git_revision", lambda _root: "f" * 40)
    monkeypatch.setattr(assurance, "_candidate_dirty", lambda _root: True)
    monkeypatch.setattr(assurance, "_validate_rehearsal_payload", validate)

    control = _rehearsal_control(
        tmp_path,
        {"assurance": {"rehearsal_command": ["rehearse", "{output}"]}},
    )

    assert control["status"] == "broken"
    assert control["errors"] == ["candidate mismatch"]
    validate.assert_called_once_with(payload, revision="f" * 40, dirty=True)


def test_functional_rehearsal_requires_executed_qa_rollback_and_cleanup() -> None:
    assert _validate_rehearsal_payload(_rehearsal()) == []
    payload = _rehearsal()
    payload["functional_qa"] = {"status": "pass", "checks": [], "evidence": {}}
    rollback = payload["rollback"]
    assert isinstance(rollback, dict)
    rollback["restored_matches_before"] = False
    payload["cleanup_verified"] = False
    payload["result_identity"] = _identity(payload)
    errors = _validate_rehearsal_payload(payload)
    assert any("checks" in error for error in errors)
    assert any("exact restoration" in error for error in errors)
    assert any("cleanup_verified" in error for error in errors)


def test_manual_qa_is_a_distinct_executed_procedure_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    procedure_path = tmp_path / "qa" / "procedures" / "control-surface-rehearsal.md"
    procedure_path.parent.mkdir(parents=True)
    procedure_path.write_text("# executed procedure\n", encoding="utf-8")
    rehearsal = {
        "status": "works",
        "artifact": ".aqg/work/assurance/manual-qa-rehearsal.json",
        "execution": {
            "purpose": "manual-qa",
            "execution_identity": "sha256:" + "e" * 64,
        },
        "result": _rehearsal(),
        "errors": [],
    }
    execute = Mock(return_value=rehearsal)
    monkeypatch.setattr(assurance, "_rehearsal_control", execute)

    control = _manual_qa_control(tmp_path, {})

    procedure_artifact = {
        "path": "qa/procedures/control-surface-rehearsal.md",
        "sha256": "sha256:" + hashlib.sha256(b"# executed procedure\n").hexdigest(),
    }
    result = rehearsal["result"]
    assert isinstance(result, dict)
    functional_qa = result["functional_qa"]
    assert isinstance(functional_qa, dict)
    assert control == {
        "status": "works",
        "method": "agent-operated executable procedure",
        "procedure": functional_qa["procedure"],
        "procedure_artifact": procedure_artifact,
        "artifact": ".aqg/work/assurance/manual-qa-rehearsal.json",
        "execution": rehearsal["execution"],
        "observations": functional_qa["evidence"],
        "errors": [],
    }
    execute.assert_called_once_with(
        tmp_path,
        {},
        artifact_name="manual-qa-rehearsal.json",
        execution_purpose="manual-qa",
    )

    rehearsal["result"] = {"functional_qa": {}}
    broken = _manual_qa_control(tmp_path, {})
    assert broken["status"] == "broken"
    assert broken["errors"] == ["functional_qa procedure identity is invalid"]

    rehearsal["status"] = "broken"
    rehearsal["errors"] = ["functional rehearsal failed"]
    broken = _manual_qa_control(tmp_path, {})
    assert broken["errors"] == [
        "functional rehearsal failed",
        "the executed functional QA procedure is not green",
        "functional_qa procedure identity is invalid",
    ]

    assert _manual_qa_errors({"status": "works"}, {}, None) == [
        "functional_qa procedure identity is invalid",
        "manual QA execution provenance is missing",
        "manual QA procedure artifact digest is missing",
    ]


def test_functional_qa_diagnostics_are_stable_machine_contracts() -> None:
    assert _functional_qa_errors(None) == ["functional_qa must be an object"]
    assert _functional_qa_errors(
        {"status": "fail", "procedure": {}, "checks": [], "evidence": {}}
    ) == [
        "functional_qa.status must be pass",
        "functional_qa procedure identity is invalid",
        "functional_qa.checks must contain named executed checks",
    ]
    assert (
        _functional_qa_errors(
            {"status": "pass", "procedure": {}, "checks": [], "evidence": {}, "extra": True}
        )[0]
        == "functional_qa keys differ: missing=[], unknown=['extra']"
    )
    assert _qa_procedure_errors({}) == ["functional_qa procedure identity is invalid"]
    assert _qa_checks_errors({"checks": []}) == [
        "functional_qa.checks must contain named executed checks"
    ]
    assert _qa_checks_errors(
        {"checks": ["setup", "setup"], "evidence": {"setup": {"exit_code": 0}}}
    ) == [
        "functional_qa.checks must cover every required public control surface",
        "functional_qa.checks must be unique",
    ]


def test_assurance_result_preserves_schema_scope_and_failures() -> None:
    scope = {
        "revision": "revision",
        "base_ref": "base",
        "change_fingerprint": "sha256:change",
        "control_fingerprint": "sha256:control",
    }
    controls = {"proof": {"status": "broken", "errors": ["specific failure"]}}

    code, report = _assurance_result(controls, scope, "high_assurance")

    assert code == QUALITY_FAILURE
    assert report == {
        "schema_version": 1,
        "kind": "aqg-functional-assurance",
        "scope": scope,
        "risk_profile": "high_assurance",
        "controls": controls,
        "status": "not_ready",
        "failures": ["proof: specific failure"],
    }
    pass_code, pass_report = _assurance_result({"proof": {"status": "works"}}, scope, "standard")
    assert pass_code == PASS
    assert pass_report["failures"] == []
    assert pass_report["status"] == "works"


@pytest.mark.parametrize(
    ("functional_qa", "expected"),
    [
        (None, "must be an object"),
        (
            {
                "status": "fail",
                "procedure": {},
                "checks": ["setup"],
                "evidence": {"setup": {"exit_code": 1}},
            },
            "status must be pass",
        ),
    ],
)
def test_functional_qa_rejects_missing_or_failed_execution(
    functional_qa: object, expected: str
) -> None:
    payload = _rehearsal()
    payload["functional_qa"] = functional_qa
    payload["result_identity"] = _identity(payload)

    assert any(expected in error for error in _validate_rehearsal_payload(payload))


def test_high_assurance_adds_executed_manual_qa_when_risk_requires_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rehearsal = {
        "status": "works",
        "artifact": ".aqg/work/assurance/functional-rehearsal.json",
        "result": _rehearsal(),
        "errors": [],
    }
    behavior = Mock(return_value={"status": "works", "errors": []})
    rehearsal_control = Mock(return_value=rehearsal)
    manual_qa = Mock(return_value={"status": "works", "errors": []})
    independent = Mock(return_value={"status": "works", "errors": []})
    monkeypatch.setattr(assurance, "_behavior_control", behavior)
    monkeypatch.setattr(assurance, "_rehearsal_control", rehearsal_control)
    monkeypatch.setattr(assurance, "_manual_qa_control", manual_qa)
    monkeypatch.setattr(assurance, "_independent_control", independent)

    project = {"enforcement": {"base_ref": "HEAD"}}
    risk = {
        "selected_risk_profile": "high_assurance",
        "card": {"authority_triggers": {}},
        "required_controls": {"requires_manual_qa": True},
    }

    code, report = evaluate_assurance(
        tmp_path,
        project,
        risk,
    )

    assert code == PASS
    assert report["status"] == "works"
    assert report["controls"]["functional_rehearsal"] is rehearsal
    assert report["controls"]["manual_qa"]["status"] == "works"
    assert report["controls"]["independent_verification"]["status"] == "works"
    behavior.assert_called_once_with(tmp_path, project, "high_assurance", None)
    rehearsal_control.assert_called_once_with(tmp_path, project)
    manual_qa.assert_called_once_with(tmp_path, project)
    independent.assert_called_once_with(tmp_path, report["scope"])

    controls: dict[str, dict[str, object]] = {}
    _add_high_assurance_controls(controls, tmp_path, project, {}, report["scope"])
    assert "manual_qa" not in controls


def test_assurance_defaults_to_standard_without_high_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    behavior = Mock(return_value={"status": "works", "errors": []})
    high_controls = Mock()
    monkeypatch.setattr(assurance, "_behavior_control", behavior)
    monkeypatch.setattr(assurance, "_add_high_assurance_controls", high_controls)
    project = {"enforcement": {"base_ref": "HEAD"}}

    code, report = evaluate_assurance(tmp_path, project, {}, run_id="run-1")

    assert code == PASS
    assert report["risk_profile"] == "standard"
    assert set(report["controls"]) == {"behavior", "authority"}
    behavior.assert_called_once_with(tmp_path, project, "standard", "run-1")
    high_controls.assert_not_called()


def test_critical_assurance_uses_card_authority_and_high_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    behavior = Mock(return_value={"status": "works", "errors": []})
    high_controls = Mock()
    monkeypatch.setattr(assurance, "_behavior_control", behavior)
    monkeypatch.setattr(assurance, "_add_high_assurance_controls", high_controls)
    project = {"enforcement": {"base_ref": "HEAD"}}
    risk = {
        "selected_risk_profile": "critical",
        "card": {"authority_triggers": {"private_data_exposure": True}},
    }

    code, report = evaluate_assurance(tmp_path, project, risk, run_id="critical-run")

    assert code == QUALITY_FAILURE
    assert report["risk_profile"] == "critical"
    assert report["controls"]["authority"]["active"] == ["private_data_exposure"]
    behavior.assert_called_once_with(tmp_path, project, "critical", "critical-run")
    high_controls.assert_called_once_with(
        report["controls"], tmp_path, project, risk, report["scope"]
    )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda value: value.update({"unexpected": True}), "keys differ"),
        (lambda value: value.update({"evidence_type": "self-asserted"}), "evidence_type"),
        (lambda value: value["candidate"].update({"material_count": True}), "material_count"),
        (lambda value: value["durations_ms"].update({"dashboard": -1}), "non-negative"),
        (
            lambda value: value["cleanup"].update({"temporary_workspace_removed": False}),
            "cleanup was not verified",
        ),
        (lambda value: value["functional_qa"].update({"checks": ["setup", "setup"]}), "unique"),
        (
            lambda value: value["functional_qa"].update(
                {"checks": ["cold_start", "setup", "review"]}
            ),
            "every required public control surface",
        ),
        (lambda value: value["functional_qa"]["evidence"].pop("tui"), "match every"),
        (lambda value: value.update({"setup": {"exit_code": 9}}), "setup alias"),
        (
            lambda value: value["rollback"].update({"restored_identity": "sha256:" + "e" * 64}),
            "restored identity",
        ),
        (
            lambda value: value["rollback"].update({"candidate_identity": "sha256:" + "c" * 64}),
            "changed installation",
        ),
    ],
)
def test_functional_rehearsal_rejects_forged_or_incomplete_evidence(
    mutation: object, expected: str
) -> None:
    payload = copy.deepcopy(_rehearsal())
    assert callable(mutation)
    mutation(payload)
    payload["result_identity"] = _identity(payload)
    assert any(expected in error for error in _validate_rehearsal_payload(payload))


def test_functional_rehearsal_identity_binds_content_and_current_revision() -> None:
    payload = _rehearsal()
    rollback = payload["rollback"]
    assert isinstance(rollback, dict)
    rollback["operation_outputs_equal"] = False
    errors = _validate_rehearsal_payload(payload, revision="f" * 40, dirty=True)
    assert any("result_identity does not match" in error for error in errors)
    assert any("current candidate" in error for error in errors)
    assert any("dirty state" in error for error in errors)
    assert any("equal output" in error for error in errors)


def test_reserved_authority_is_distinct_from_broken_functionality() -> None:
    clear = _authority_control({"authority_triggers": {}})
    assert clear["status"] == "works"
    guarded = _authority_control({"authority_triggers": {"private_data_exposure": True}})
    assert guarded["status"] == "human_decision_needed"
    assert guarded["active"] == ["private_data_exposure"]


def test_trusted_mode_environment_without_manifested_verifier_evidence_is_unusable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted = tmp_path / "trusted"
    quality = trusted / "quality"
    quality.mkdir(parents=True)
    for name in ("qg.py", "policy.toml", "project.json"):
        (quality / name).write_text("trusted\n", encoding="utf-8")
    monkeypatch.setenv("AQG_TRUSTED_MODE", "1")
    monkeypatch.setenv("AQG_TRUSTED_LAUNCHER", str((quality / "qg.py").resolve()))
    monkeypatch.setenv("AQG_TRUSTED_POLICY_PATH", str((quality / "policy.toml").resolve()))
    monkeypatch.setenv("AQG_TRUSTED_PROJECT_PATH", str((quality / "project.json").resolve()))
    monkeypatch.setenv("AQG_TRUSTED_TOOLCHAIN_ROOT", str(trusted.resolve()))

    report = _independent_control(
        tmp_path,
        {
            "revision": "candidate",
            "base_ref": "base",
            "change_fingerprint": "sha256:" + "1" * 64,
            "control_fingerprint": "sha256:" + "2" * 64,
        },
    )

    assert report["status"] == "unusable"
    assert any("AQG_TRUSTED_EVIDENCE_DIR" in error for error in report["errors"])


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
            "adversarial",
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
