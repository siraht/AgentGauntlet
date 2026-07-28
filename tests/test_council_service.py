from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import aqg.council_service as service
from aqg.constants import INFRASTRUCTURE_ERROR, PASS
from aqg.council import build_candidate_bundle
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
    bundle = _bundle()
    quality_run = tmp_path / ".aqg" / "runs" / "quality-current"
    quality_run.mkdir(parents=True)
    routing = service._provider_routing("public")
    plan = service._plan_payload(tier, quality_run, bundle, 100, 1000, "public", routing)
    return plan, bundle


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
    paths = {"grok": "/tools/grok", "opencode": None}

    def fake_version(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "grok 9.1\n", "TOKEN=secret")

    report = service.council_doctor(which=paths.get, executor=fake_version)

    assert report["missing_tools"] == ["opencode"]
    assert report["tools"]["grok"]["version"] == "grok 9.1"
    assert "TOKEN" not in json.dumps(report)
    assert report["models"]["smoke"] == [
        "synthetic/hf:zai-org/GLM-4.7-Flash",
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
    monkeypatch.setattr(service, "_matching_quality_run", lambda _root, _scope: (run_dir, {}))
    monkeypatch.setattr(service, "_bundle_inputs", lambda *_args: {"diff.patch": "x" * 100})

    plan = service.plan_council(
        tmp_path, "pr", max_bundle_bytes=10_000, data_classification="public"
    )

    assert plan["provider_calls"] is False
    assert plan["minimum_provider_groups"] == 3
    with pytest.raises(ConfigurationError, match="candidate bundle is"):
        service.plan_council(tmp_path, "pr", max_bundle_bytes=10, data_classification="public")


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
        "gates": [{"name": "secrets", "status": "pass", "exit_code": 0}],
    }
    write_evidence_json(run_dir / "summary.json", summary)
    write_run_manifest(run_dir, "run-1")

    selected, selected_summary = service._matching_quality_run(tmp_path, _scope())

    assert selected == run_dir
    assert selected_summary == summary


def test_fake_run_publishes_only_verified_immutable_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, bundle = _prepared(tmp_path, "pr")
    monkeypatch.setattr(service, "_prepare_plan", lambda *_args: (plan, bundle))
    code, report = service.run_council(
        tmp_path,
        "pr",
        executor=_clear_executor,
        run_id="council-test",
        data_classification="public",
    )

    assert code == PASS
    assert report["status"] == "advisory_clear"
    assert report["scope"] == bundle["scope"]
    assert len(report["members"]) == 3
    assert {member["role"] for member in report["members"]} == {
        "requirements_behavior",
        "test_evidence",
        "operability_rollback",
    }
    assert service.verify_council_run(tmp_path, "latest")["ok"] is True
    run_dir = tmp_path / ".aqg" / "council" / "council-test"
    execution = json.loads(next((run_dir / "executions").glob("*.json")).read_text())
    assert "stdout" not in execution and "stderr" not in execution
    toolchain = json.loads((run_dir / "toolchain.json").read_text())
    assert toolchain["kind"] == "aqg-council-doctor"
    assert (run_dir / "manifest.json").is_file()
    assert json.loads((run_dir.parent / "latest.json").read_text())["run_id"] == "council-test"

    (run_dir / "result.json").write_text("{}\n", encoding="utf-8")
    assert service.verify_council_run(tmp_path, "council-test")["ok"] is False


def test_smoke_is_explicitly_incomplete_by_high_assurance_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, bundle = _prepared(tmp_path, "smoke")
    monkeypatch.setattr(service, "_prepare_plan", lambda *_args: (plan, bundle))

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
    plan, bundle = _prepared(tmp_path, "pr")
    restricted = dict(plan)
    restricted["data_classification"] = "confidential"
    restricted["provider_routing"] = service._provider_routing("confidential")
    monkeypatch.setattr(service, "_prepare_plan", lambda *_args: (restricted, bundle))

    with pytest.raises(ConfigurationError, match="no approved external-provider route"):
        service.run_council(tmp_path, "pr", data_classification="confidential")

    with pytest.raises(ConfigurationError, match="unknown council data classification"):
        service._provider_routing("secret")


def test_service_evidence_reports_missing_files_as_errors(tmp_path: Path) -> None:
    errors = service._service_evidence_errors(tmp_path)

    assert errors
    assert "missing JSON file" in errors[0]
