# Feature-Spec: AgentQualityGauntlet.ReviewCouncil AQG-COUNCIL-015

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

import aqg.council_service as service
from aqg.constants import INFRASTRUCTURE_ERROR, PASS
from aqg.council import aggregate_ballots, build_candidate_bundle, provider_identity
from aqg.council_chunks import build_bundle_series
from aqg.errors import ConfigurationError
from aqg.evidence_manifest import write_evidence_json, write_run_manifest


def _scope() -> dict[str, str]:
    return {
        "revision": "abc123",
        "base_revision": "origin/main",
        "change_fingerprint": "sha256:" + "1" * 64,
        "control_fingerprint": "sha256:" + "2" * 64,
    }


def _bundle() -> dict[str, Any]:
    return build_candidate_bundle(
        **_scope(),
        evidence_manifest_sha256="sha256:" + "3" * 64,
        inputs={"current.diff.patch": "diff --git a/app.py b/app.py\n"},
    )


def _prepared(tmp_path: Path, tier: str) -> tuple[dict[str, Any], dict[str, Any]]:
    series = build_bundle_series(
        scope=_scope(),
        evidence_manifest_sha256="sha256:" + "3" * 64,
        inputs={"current.diff.patch": "diff --git a/app.py b/app.py\n"},
        max_bundle_bytes=10_000,
    )
    quality_run = tmp_path / ".aqg" / "runs" / "quality-current"
    quality_run.mkdir(parents=True)
    routing = service._provider_routing("public")
    plan = service._plan_payload(tier, quality_run, series, 10_000, "public", routing)
    return plan, series


def _clear_executor(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    assert isinstance(command, list)
    assert kwargs["cwd"] != Path.cwd()
    assert kwargs["env"].get("CI") == "1"
    payload = {
        "verdict": "clear",
        "confidence": "high",
        "findings": [],
        "limitations": [],
    }
    return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")


def test_doctor_reports_exact_models_versions_and_missing_tools_without_credentials() -> None:
    paths = {"codex": "/tools/codex", "grok": "/tools/grok", "opencode": None}

    def fake_version(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "grok 9.1\n", "TOKEN=secret")

    report = service.council_doctor(which=paths.get, executor=fake_version)

    assert report["missing_tools"] == ["opencode"]
    assert report["tools"]["grok"]["version"] == "grok 9.1"
    assert report["tools"]["codex"]["version"] == "grok 9.1"
    assert "TOKEN" not in json.dumps(report)
    assert report["models"]["smoke"] == [
        "synthetic/hf:zai-org/GLM-4.7-Flash",
        "opencode/deepseek-v4-flash-free",
    ]
    assert report["models"]["high"] == [
        "grok-4.5",
        "codex/gpt-5.6-sol",
        "codex/gpt-5.6-sol",
        "opencode/deepseek-v4-flash-free",
    ]


def test_plan_has_no_provider_calls_and_bundle_cap_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / ".aqg" / "runs" / "quality-current"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(service, "_base_ref", lambda _root: "origin/main")
    monkeypatch.setattr(service, "_scope", lambda _root, _base: _scope())
    monkeypatch.setattr(
        service, "_matching_quality_run", lambda _root, _scope, _profile: (run_dir, {})
    )
    monkeypatch.setattr(service, "_bundle_inputs", lambda *_args: {"current.diff.patch": "x" * 100})

    plan = service.plan_council(
        tmp_path, "pr", max_bundle_bytes=10_000, data_classification="public"
    )

    assert plan["provider_calls"] is False
    assert plan["minimum_provider_groups"] == 3
    assert plan["bundle_mode"] == "single"
    with pytest.raises(ConfigurationError, match="exceeds the bundle cap"):
        service.plan_council(tmp_path, "pr", max_bundle_bytes=10, data_classification="public")
    with pytest.raises(ConfigurationError) as error:
        service.plan_council(tmp_path, "pr", max_bundle_bytes=0, data_classification="public")
    assert str(error.value) == "council bundle size cap must be positive"


def test_plan_contract_is_exact(tmp_path: Path) -> None:
    plan, series = _prepared(tmp_path, "pr")
    members = [
        {"role": role, "model_id": model, **provider_identity(model)}
        for role, model in service.TIER_MEMBERS["pr"]
    ]

    assert plan == {
        "schema_version": 1,
        "kind": "aqg-council-plan",
        "advisory_only": True,
        "banner": service.ADVISORY_BANNER,
        "tier": "pr",
        "purpose": "candidate",
        "provider_calls": False,
        "data_classification": "public",
        "provider_routing": service._provider_routing("public"),
        "members": members,
        "required_roles": ["operability_rollback", "requirements_behavior", "test_evidence"],
        "minimum_provider_groups": 3,
        "expected_standard": "complete",
        "quality_run_id": "quality-current",
        "scope": series["scope"],
        "bundle_sha256": series["series_sha256"],
        "bundle_mode": "single",
        "bundle_count": 1,
        "review_scope": "candidate",
        "completion_meaning": "all_required_candidate_ballots_received",
        "series_limitations": [],
        "bundle_bytes": series["chunks"][0]["bundle_bytes"],
        "total_bundle_bytes": series["chunks"][0]["bundle_bytes"],
        "max_bundle_bytes": 10_000,
    }


def test_high_tier_uses_subscription_reviewers_without_synthetic_spend(
    tmp_path: Path,
) -> None:
    plan, _series = _prepared(tmp_path, "high")

    assert [member["model_id"] for member in plan["members"]] == [
        "grok-4.5",
        "codex/gpt-5.6-sol",
        "codex/gpt-5.6-sol",
        "opencode/deepseek-v4-flash-free",
    ]
    assert {member["provider_group"] for member in plan["members"]} == {
        "xai:grok.com",
        "openai:codex",
        "opencode:opencode.ai",
    }
    assert not any(member["provider_id"] == "synthetic" for member in plan["members"])


def test_smoke_plan_marks_high_assurance_as_incomplete(tmp_path: Path) -> None:
    plan, _series = _prepared(tmp_path, "smoke")

    assert plan["expected_standard"] == "high_assurance_incomplete"


def test_quality_run_selection_requires_scope_match_manifest_and_secrets(
    tmp_path: Path,
) -> None:
    summaryless = tmp_path / ".aqg" / "runs" / "zzz-summaryless"
    summaryless.mkdir(parents=True)
    write_run_manifest(summaryless, "zzz-summaryless")
    run_dir = tmp_path / ".aqg" / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    summary = {
        "revision": "abc123",
        "change_fingerprint": "sha256:" + "1" * 64,
        "control_fingerprint": "sha256:" + "2" * 64,
        "profile": "deep",
        "gates": [{"name": "secrets", "status": "pass", "exit_code": 0}],
    }
    write_evidence_json(run_dir / "summary.json", summary)
    write_run_manifest(run_dir, "run-1")

    selected, selected_summary = service._matching_quality_run(tmp_path, _scope(), "deep")

    assert selected == run_dir
    assert selected_summary == summary


def test_deep_security_gate_satisfies_council_secret_prerequisite() -> None:
    summary = {"gates": [{"name": "security_fast", "status": "pass", "exit_code": 0}]}

    assert service._secret_gate_passed(summary) is True
    assert service._is_secret_gate("secrets") is True
    assert service._is_secret_gate("other") is False


@pytest.mark.parametrize(
    "summary",
    [
        {},
        {"gates": "malformed"},
        {"gates": ["malformed"]},
        {"gates": [{"name": "other", "status": "pass", "exit_code": 0}]},
        {"gates": [{"name": "security_fast", "status": "fail", "exit_code": 0}]},
        {"gates": [{"name": "security_fast", "status": "pass", "exit_code": 1}]},
    ],
)
def test_council_secret_prerequisite_fails_closed(summary: dict[str, Any]) -> None:
    assert service._secret_gate_passed(summary) is False


def test_high_tier_does_not_bundle_a_newer_fast_run(
    tmp_path: Path,
) -> None:
    for run_id, profile in (
        ("run-1-deep", "deep"),
        ("run-2-fast", "fast"),
        ("run-3-deep", "deep"),
    ):
        run_dir = tmp_path / ".aqg" / "runs" / run_id
        run_dir.mkdir(parents=True)
        summary = {
            **_scope(),
            "profile": profile,
            "gates": [{"name": "secrets", "status": "pass", "exit_code": 0}],
        }
        write_evidence_json(run_dir / "summary.json", summary)
        write_run_manifest(run_dir, run_id)

    selected, selected_summary = service._matching_quality_run(tmp_path, _scope(), "deep")

    assert selected.name == "run-3-deep"
    assert selected_summary["profile"] == "deep"


def test_high_tier_fails_closed_without_a_deep_run(tmp_path: Path) -> None:
    run_dir = tmp_path / ".aqg" / "runs" / "run-fast"
    run_dir.mkdir(parents=True)
    summary = {
        **_scope(),
        "profile": "fast",
        "gates": [{"name": "secrets", "status": "pass", "exit_code": 0}],
    }
    write_evidence_json(run_dir / "summary.json", summary)
    write_run_manifest(run_dir, "run-fast")

    expected = (
        "no finalized quality run matches the current revision, change fingerprint, "
        "control fingerprint, passing secrets gate, and 'deep' evidence profile"
    )
    with pytest.raises(ConfigurationError, match=expected):
        service._matching_quality_run(tmp_path, _scope(), "deep")

    assert service._profile_satisfies("unknown", "deep") is False


def test_prepare_plan_preserves_every_evidence_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scope = _scope()
    run_dir = tmp_path / "run"
    summary = {"profile": "deep"}
    inputs = {"current.diff.patch": "diff"}
    series = {
        "scope": _bundle()["scope"],
        "series_sha256": "sha256:" + "4" * 64,
        "bundles": [_bundle()],
        "chunks": [{"bundle_bytes": 1}],
    }
    routing = {"external_providers_allowed": True}
    matching = Mock(return_value=(run_dir, summary))
    bundle_inputs = Mock(return_value=inputs)
    build_series = Mock(return_value=series)
    plan_payload = Mock(return_value={"kind": "plan"})
    base_ref = Mock(return_value="origin/main")
    build_scope = Mock(return_value=scope)
    monkeypatch.setattr(service, "_base_ref", base_ref)
    monkeypatch.setattr(service, "_provider_routing", lambda classification: routing)
    monkeypatch.setattr(service, "_scope", build_scope)
    monkeypatch.setattr(service, "_matching_quality_run", matching)
    monkeypatch.setattr(service, "_bundle_inputs", bundle_inputs)
    monkeypatch.setattr(service, "build_bundle_series", build_series)
    monkeypatch.setattr(service, "sha256_file", lambda path: "5" * 64)
    monkeypatch.setattr(service, "_plan_payload", plan_payload)

    plan, selected_bundle = service._prepare_plan(tmp_path, "high", 1, "public")

    assert plan == {"kind": "plan"}
    assert selected_bundle == series
    base_ref.assert_called_once_with(tmp_path)
    build_scope.assert_called_once_with(tmp_path, "origin/main")
    matching.assert_called_once_with(tmp_path, scope, "deep")
    bundle_inputs.assert_called_once_with(tmp_path, "origin/main", run_dir, summary)
    build_series.assert_called_once_with(
        scope=scope,
        evidence_manifest_sha256="sha256:" + "5" * 64,
        inputs=inputs,
        max_bundle_bytes=1,
    )
    plan_payload.assert_called_once_with("high", run_dir, series, 1, "public", routing, "candidate")


def test_fake_run_publishes_only_verified_immutable_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, series = _prepared(tmp_path, "pr")
    monkeypatch.setattr(service, "_prepare_plan", lambda *_args: (plan, series))
    code, report = service.run_council(
        tmp_path,
        "pr",
        executor=_clear_executor,
        run_id="council-test",
        data_classification="public",
    )

    assert code == PASS
    verification = report.pop("verification")
    members = report.pop("members")
    assert report == {
        "schema_version": 1,
        "kind": "aqg-council-report",
        "advisory_only": True,
        "banner": service.ADVISORY_BANNER,
        "run_id": "council-test",
        "tier": "pr",
        "purpose": "candidate",
        "scope": series["scope"],
        "status": "advisory_clear",
        "summary": (
            "Agent advisory only: advisory_clear across 1 bounded bundle(s); "
            "no human approval or release authority is granted."
        ),
        "complete": True,
        "provider_groups": [
            "opencode:opencode.ai",
            "synthetic:api.synthetic.new",
            "xai:grok.com",
        ],
        "covered_roles": ["operability_rollback", "requirements_behavior", "test_evidence"],
        "blockers": [],
        "dissent": {"present": False, "chunk_indexes": []},
        "incomplete_reasons": [],
        "bundle_mode": "single",
        "bundle_count": 1,
        "review_scope": "candidate",
        "completion_meaning": "all_required_candidate_ballots_received",
        "series_limitations": [],
        "executions": 3,
    }
    expected_members = [
        {
            "model_id": model,
            "provider_group": provider_identity(model)["provider_group"],
            "role": role,
            "verdict": "clear",
            "confidence": "high",
            "findings": 0,
        }
        for role, model in service.TIER_MEMBERS["pr"]
    ]
    assert sorted(members, key=lambda item: item["role"]) == sorted(
        expected_members, key=lambda item: item["role"]
    )
    assert report["status"] == "advisory_clear"
    assert report["scope"] == series["scope"]
    assert len(members) == 3
    assert set(verification) == {
        "schema_version",
        "kind",
        "advisory_only",
        "banner",
        "run_id",
        "ok",
        "errors",
        "manifest",
    }
    assert verification["schema_version"] == 1
    assert verification["kind"] == "aqg-council-verification"
    assert verification["advisory_only"] is True
    assert verification["banner"] == service.ADVISORY_BANNER
    assert verification["run_id"] == "council-test"
    assert verification["ok"] is True
    assert verification["errors"] == []
    assert service.verify_council_run(tmp_path)["ok"] is True
    assert service.verify_council_run(tmp_path, "latest")["ok"] is True
    assert service.report_council(tmp_path)["run_id"] == "council-test"
    run_dir = tmp_path / ".aqg" / "council" / "council-test"
    execution = json.loads(next((run_dir / "executions").glob("*.json")).read_text())
    assert "stdout" not in execution and "stderr" not in execution
    toolchain = json.loads((run_dir / "toolchain.json").read_text())
    assert toolchain["kind"] == "aqg-council-doctor"
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "chunks" / "chunk-0000" / "manifest.json").is_file()
    assert json.loads((run_dir.parent / "latest.json").read_text())["run_id"] == "council-test"

    (run_dir / "result.json").write_text("{}\n", encoding="utf-8")
    assert service.verify_council_run(tmp_path, "council-test")["ok"] is False


def test_run_council_wires_all_authoritative_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, series = _prepared(tmp_path, "pr")
    prepare = Mock(return_value=(plan, series))
    route = Mock()
    environment = {"PATH": "/tools", "CI": "1"}
    environment_filter = Mock(return_value=environment)
    rules = Mock(return_value=(["required-role"], 4))
    ballots = [[{"ballot": 1}]]
    executions = [[{"execution": 1}]]
    chunk_results = [{"chunk": 1}]
    run_series = Mock(return_value=(ballots, executions, chunk_results))
    result = {"status": "advisory_clear", "result_sha256": "sha256:result"}
    aggregate = Mock(return_value=result)
    run_dir = tmp_path / ".aqg" / "council" / "wired"
    write = Mock(return_value=run_dir)
    publish = Mock()
    exit_code = Mock(return_value=7)
    report = {"run_id": "wired"}
    reporter = Mock(return_value=report)
    executor = Mock()
    monkeypatch.setattr(service, "_prepare_plan", prepare)
    monkeypatch.setattr(service, "_require_provider_route", route)
    monkeypatch.setattr(service, "minimal_environment", environment_filter)
    monkeypatch.setattr(service, "_tier_rules", rules)
    monkeypatch.setattr(service, "_run_series", run_series)
    monkeypatch.setattr(service, "aggregate_series", aggregate)
    monkeypatch.setattr(service, "_write_series_run", write)
    monkeypatch.setattr(service, "_verify_and_publish", publish)
    monkeypatch.setattr(service, "_result_exit_code", exit_code)
    monkeypatch.setattr(service, "report_council", reporter)

    actual = service.run_council(
        tmp_path,
        "pr",
        timeout_seconds=1,
        max_bundle_bytes=123,
        executor=executor,
        run_id="wired",
        data_classification="public",
    )

    assert actual == (7, report)
    prepare.assert_called_once_with(tmp_path, "pr", 123, "public", "candidate")
    route.assert_called_once_with(plan, "public")
    assert environment_filter.call_args.args[0] is service.os.environ
    rules.assert_called_once_with("pr")
    run_series.assert_called_once_with(
        "pr",
        series,
        environment,
        1,
        executor,
        "wired",
        ["required-role"],
        4,
    )
    aggregate.assert_called_once_with(series, chunk_results)
    write.assert_called_once_with(
        tmp_path,
        "wired",
        plan,
        series,
        ballots,
        executions,
        chunk_results,
        result,
    )
    publish.assert_called_once_with(tmp_path, run_dir, "wired", result)
    exit_code.assert_called_once_with(result, [{"execution": 1}])
    reporter.assert_called_once_with(tmp_path, "wired")


def test_run_council_rejects_zero_timeout_before_preparation(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError) as error:
        service.run_council(
            tmp_path,
            timeout_seconds=0,
            data_classification="public",
        )

    assert str(error.value) == "council member timeout must be positive"


def test_run_series_forwards_stricter_provider_group_requirement(tmp_path: Path) -> None:
    _plan, series = _prepared(tmp_path, "pr")
    roles, _minimum_groups = service._tier_rules("pr")

    _ballots, _executions, results = service._run_series(
        "pr",
        series,
        {"PATH": "/usr/bin", "CI": "1"},
        10,
        _clear_executor,
        "strict-groups",
        roles,
        4,
    )

    assert results[0]["complete"] is False
    assert results[0]["status"] == "advisory_incomplete"
    assert results[0]["provider_groups"] == [
        "opencode:opencode.ai",
        "synthetic:api.synthetic.new",
        "xai:grok.com",
    ]


def test_oversized_run_reviews_every_chunk_and_manifests_nested_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    series = build_bundle_series(
        scope=_scope(),
        evidence_manifest_sha256="sha256:" + "3" * 64,
        inputs={"current.diff.patch": "x" * 4_000},
        max_bundle_bytes=3_000,
    )
    quality_run = tmp_path / ".aqg" / "runs" / "quality-current"
    quality_run.mkdir(parents=True)
    plan = service._plan_payload(
        "pr",
        quality_run,
        series,
        3_000,
        "public",
        service._provider_routing("public"),
    )
    assert len(series["bundles"]) == 2
    monkeypatch.setattr(service, "_prepare_plan", lambda *_args: (plan, series))

    code, report = service.run_council(
        tmp_path,
        "pr",
        executor=_clear_executor,
        run_id="chunked-test",
        data_classification="public",
    )

    assert code == PASS
    assert report["bundle_mode"] == "chunked"
    assert report["bundle_count"] == len(series["chunks"])
    assert report["review_scope"] == "bounded_diff_chunk"
    assert report["completion_meaning"] == "all_required_chunk_ballots_received"
    assert report["series_limitations"] == [
        (
            "Each ballot sees one bounded diff chunk plus the shared candidate context; "
            "cross-chunk relationships remain a residual review unknown."
        )
    ]
    assert report["executions"] == len(series["chunks"]) * 3
    run_dir = tmp_path / ".aqg" / "council" / "chunked-test"
    child_manifests = sorted((run_dir / "chunks").glob("chunk-*/manifest.json"))
    assert len(child_manifests) == len(series["chunks"])
    assert service.verify_council_run(tmp_path, "chunked-test")["ok"] is True

    with pytest.raises(ConfigurationError, match="already exists"):
        service.run_council(
            tmp_path,
            "pr",
            executor=_clear_executor,
            run_id="chunked-test",
            data_classification="public",
        )

    parent_result = run_dir / "result.json"
    original_result = parent_result.read_text(encoding="utf-8")
    parent_result.write_text("{}\n", encoding="utf-8")
    (run_dir / "manifest.json").unlink()
    write_run_manifest(run_dir, "chunked-test")
    semantic = service.verify_council_run(tmp_path, "chunked-test")
    assert semantic["ok"] is False
    assert "series result does not match its bounded chunk results" in semantic["errors"]
    parent_result.write_text(original_result, encoding="utf-8")
    (run_dir / "manifest.json").unlink()
    write_run_manifest(run_dir, "chunked-test")

    child_result = child_manifests[0].parent / "result.json"
    child_result.write_text("{}\n", encoding="utf-8")
    (run_dir / "manifest.json").unlink()
    write_run_manifest(run_dir, "chunked-test")
    assert service.verify_council_run(tmp_path, "chunked-test")["ok"] is False


def test_existing_single_bundle_run_remains_verifiable(
    tmp_path: Path,
) -> None:
    bundle = _bundle()
    ballots, executions = service._run_members(
        "pr", bundle, tmp_path, {"PATH": "/usr/bin", "CI": "1"}, 10, _clear_executor, "legacy"
    )
    result = aggregate_ballots(
        bundle,
        ballots,
        required_roles=sorted(role for role, _ in service.TIER_MEMBERS["pr"]),
        minimum_provider_groups=3,
    )
    plan = {
        "kind": "aqg-council-plan",
        "advisory_only": True,
        "tier": "pr",
        "bundle_sha256": bundle["bundle_sha256"],
    }
    service._write_council_run(
        tmp_path,
        "legacy",
        plan,
        bundle,
        ballots,
        executions,
        result,
        {"kind": "aqg-council-doctor", "advisory_only": True},
    )

    assert service.verify_council_run(tmp_path, "legacy")["ok"] is True
    report = service.report_council(tmp_path, "legacy")
    assert report["run_id"] == "legacy"
    assert report["bundle_mode"] == "single"
    assert report["bundle_count"] == 1
    assert report["review_scope"] == "candidate"
    assert report["completion_meaning"] == "all_required_candidate_ballots_received"
    assert report["series_limitations"] == []
    assert report["executions"] == 3
    assert report["scope"] == bundle["scope"]
    assert sorted(member["role"] for member in report["members"]) == sorted(
        role for role, _model in service.TIER_MEMBERS["pr"]
    )


def test_legacy_writer_binds_ballots_and_result_to_candidate_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = _bundle()
    ballots, executions = service._run_members(
        "pr", bundle, tmp_path, {"PATH": "/usr/bin", "CI": "1"}, 10, _clear_executor, "binding"
    )
    result = aggregate_ballots(
        bundle,
        ballots,
        required_roles=sorted(role for role, _model in service.TIER_MEMBERS["pr"]),
        minimum_provider_groups=3,
    )
    ballot_validator = Mock(wraps=service.validate_ballot)
    result_validator = Mock(wraps=service.validate_council_result)
    monkeypatch.setattr(service, "validate_ballot", ballot_validator)
    monkeypatch.setattr(service, "validate_council_result", result_validator)

    service._write_council_run(
        tmp_path,
        "binding",
        {
            "kind": "aqg-council-plan",
            "advisory_only": True,
            "tier": "pr",
            "bundle_sha256": bundle["bundle_sha256"],
        },
        bundle,
        ballots,
        executions,
        result,
        {"kind": "aqg-council-doctor", "advisory_only": True},
    )

    assert ballot_validator.call_count == len(ballots)
    assert all(call.kwargs == {"bundle": bundle} for call in ballot_validator.call_args_list)
    result_validator.assert_called_once_with(result, bundle=bundle)


def test_verifier_checks_service_metadata_only_after_core_integrity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / ".aqg" / "council" / "verified"
    run_dir.mkdir(parents=True)
    (run_dir / "bundle-series.json").write_text("{}\n", encoding="utf-8")
    manifest = {"ok": True, "errors": []}
    core = Mock(return_value={"errors": [], "manifest": manifest})
    service_errors = Mock(return_value=["service metadata failed"])
    monkeypatch.setattr(service, "_verify_series_evidence", core)
    monkeypatch.setattr(service, "_service_evidence_errors", service_errors)

    verification = service.verify_council_run(tmp_path, "verified")

    assert verification["errors"] == ["service metadata failed"]
    service_errors.assert_called_once_with(run_dir)
    core.return_value = {"errors": ["core integrity failed"], "manifest": manifest}
    service_errors.reset_mock()

    verification = service.verify_council_run(tmp_path, "verified")

    assert verification["errors"] == ["core integrity failed"]
    service_errors.assert_not_called()


def test_series_verifier_stops_on_parent_manifest_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = {"ok": False, "errors": ["parent manifest failed"]}
    reader = Mock()
    monkeypatch.setattr(service, "verify_run_manifest", Mock(return_value=manifest))
    monkeypatch.setattr(service, "read_json", reader)

    verification = service._verify_series_evidence(tmp_path)

    assert verification == {"errors": ["parent manifest failed"], "manifest": manifest}
    reader.assert_not_called()


def test_smoke_is_explicitly_incomplete_by_high_assurance_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, series = _prepared(tmp_path, "smoke")
    monkeypatch.setattr(service, "_prepare_plan", lambda *_args: (plan, series))

    code, report = service.run_council(
        tmp_path,
        "smoke",
        executor=_clear_executor,
        run_id="smoke-test",
        data_classification="public",
    )

    assert code == INFRASTRUCTURE_ERROR
    assert report["status"] == "advisory_incomplete"
    assert report["incomplete_reasons"]


def test_external_review_requires_explicit_public_classification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, series = _prepared(tmp_path, "pr")
    restricted = dict(plan)
    restricted["data_classification"] = "confidential"
    restricted["provider_routing"] = service._provider_routing("confidential")
    monkeypatch.setattr(service, "_prepare_plan", lambda *_args: (restricted, series))

    with pytest.raises(ConfigurationError, match="no approved external-provider route"):
        service.run_council(tmp_path, "pr", data_classification="confidential")

    with pytest.raises(ConfigurationError, match="unknown council data classification"):
        service._provider_routing("secret")


def test_service_evidence_reports_missing_files_as_errors(tmp_path: Path) -> None:
    errors = service._service_evidence_errors(tmp_path)

    assert errors
    assert "missing JSON file" in errors[0]


@pytest.mark.parametrize("leaked_key", ["stdout", "stderr"])
def test_execution_evidence_rejects_raw_provider_output(tmp_path: Path, leaked_key: str) -> None:
    executions = tmp_path / "executions"
    executions.mkdir()
    (executions / "member.json").write_text(
        json.dumps({leaked_key: "provider output"}) + "\n", encoding="utf-8"
    )

    assert service._execution_evidence_errors(tmp_path) == [
        "provider output was persisted instead of digest-only execution evidence"
    ]


@pytest.mark.parametrize(
    ("document", "field", "value", "message"),
    [
        ("plan", "kind", "wrong", "plan is not an advisory council plan"),
        ("plan", "advisory_only", False, "plan is not an advisory council plan"),
        (
            "plan",
            "bundle_sha256",
            "wrong",
            "plan does not identify the manifested candidate bundle",
        ),
        ("result", "advisory_only", False, "result is missing its advisory-only marker"),
        ("toolchain", "kind", "wrong", "toolchain provenance is missing or malformed"),
        (
            "toolchain",
            "advisory_only",
            False,
            "toolchain provenance is missing or malformed",
        ),
    ],
)
def test_service_metadata_rejects_each_broken_contract(
    document: str, field: str, value: object, message: str
) -> None:
    documents: dict[str, dict[str, object]] = {
        "plan": {
            "kind": "aqg-council-plan",
            "advisory_only": True,
            "bundle_sha256": "sha256:bundle",
        },
        "bundle": {"bundle_sha256": "sha256:bundle"},
        "result": {"advisory_only": True},
        "toolchain": {"kind": "aqg-council-doctor", "advisory_only": True},
    }
    documents[document][field] = value

    assert service._service_metadata_errors(
        documents["plan"],
        documents["bundle"],
        documents["result"],
        documents["toolchain"],
    ) == [message]
