"""Contracts for the dependency-free, advisory-only review council core."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from aqg.constants import CONFIGURATION_ERROR, INFRASTRUCTURE_ERROR, PASS
from aqg.council import (
    ROLES,
    aggregate_ballots,
    build_candidate_bundle,
    build_review_prompt,
    create_ballot,
    fingerprint,
    validate_ballot,
    validate_candidate_bundle,
    validate_council_result,
    verify_council_evidence,
    write_council_evidence,
)
from aqg.council_providers import (
    build_provider_spec,
    collect_ballot,
    execute_provider,
    minimal_environment,
    validate_provider_spec,
)
from aqg.errors import ConfigurationError

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
MODELS = {
    "requirements_behavior": "grok-4.5",
    "test_evidence": "synthetic/hf:zai-org/GLM-5.2",
    "security_trust": "synthetic/hf:moonshotai/Kimi-K3",
    "operability_rollback": "opencode/deepseek-v4-flash-free",
}


def _bundle(*, source: str = "def answer():\n    return 42\n") -> dict[str, Any]:
    return build_candidate_bundle(
        revision="candidate-123",
        base_revision="base-456",
        change_fingerprint=SHA_A,
        control_fingerprint=SHA_B,
        evidence_manifest_sha256=SHA_C,
        inputs={
            "requirements.md": "The answer must be 42.\n",
            "src/app.py": source,
        },
    )


def _ref(bundle: dict[str, Any], material: str = "src/app.py") -> dict[str, str]:
    item = next(value for value in bundle["materials"] if value["name"] == material)
    return {"material": material, "sha256": item["sha256"]}


def _payload(
    bundle: dict[str, Any],
    verdict: str = "clear",
    *,
    finding_id: str = "F-1",
) -> dict[str, Any]:
    if verdict == "clear":
        findings: list[dict[str, Any]] = []
    else:
        findings = [
            {
                "id": finding_id,
                "severity": "blocker" if verdict == "block" else "warning",
                "category": "behavior",
                "claim": "A material concern is present.",
                "evidence_refs": [_ref(bundle)],
                "recommendation": "Inspect the cited behavior before proceeding.",
            }
        ]
    return {
        "verdict": verdict,
        "confidence": "high",
        "findings": findings,
        "limitations": ["The supplied bundle is the complete review scope."]
        if verdict == "abstain"
        else [],
    }


def _ballot(
    bundle: dict[str, Any],
    role: str,
    *,
    verdict: str = "clear",
    model_id: str | None = None,
    review_id: str | None = None,
) -> dict[str, Any]:
    prompt = build_review_prompt(bundle, role)
    return create_ballot(
        review_id=review_id or f"review-{role}",
        model_id=model_id or MODELS[role],
        role=role,
        bundle=bundle,
        payload=_payload(bundle, verdict, finding_id=f"F-{role}"),
        prompt_sha256=fingerprint(prompt),
        response_sha256=fingerprint({"role": role, "verdict": verdict}),
        command_sha256=fingerprint(["provider", role]),
        duration_ms=25,
    )


def _clear_ballots(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    return [_ballot(bundle, role) for role in sorted(ROLES)]


def _completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["provider"], returncode, stdout=stdout, stderr="")


def test_aqg_council_001_candidate_bundle_is_canonical_and_content_addressed() -> None:
    first = _bundle()
    second = build_candidate_bundle(
        revision="candidate-123",
        base_revision="base-456",
        change_fingerprint=SHA_A,
        control_fingerprint=SHA_B,
        evidence_manifest_sha256=SHA_C,
        inputs={
            "src/app.py": "def answer():\n    return 42\n",
            "requirements.md": "The answer must be 42.\n",
        },
    )

    assert first == second
    assert [item["name"] for item in first["materials"]] == [
        "requirements.md",
        "src/app.py",
    ]
    assert validate_candidate_bundle(first) == first
    assert (
        _bundle(source="def answer():\n    return 41\n")["bundle_sha256"] != first["bundle_sha256"]
    )


def test_aqg_council_002_prompt_injection_is_inert_data_and_never_a_shell_command() -> None:
    marker = '"; touch /tmp/AQG_COUNCIL_SHOULD_NOT_EXIST; #'
    bundle = _bundle(source=marker)
    prompt = build_review_prompt(bundle, "security_trust")
    spec = build_provider_spec("grok-4.5", prompt)

    assert marker in prompt
    assert isinstance(spec["command"], list)
    assert spec["command"][0] == "grok"
    assert spec["command"][2] == prompt
    assert "--verbatim" in spec["command"]
    assert all(not isinstance(argument, bytes) for argument in spec["command"])
    assert not Path("/tmp/AQG_COUNCIL_SHOULD_NOT_EXIST").exists()


def test_aqg_council_003_provider_specs_have_exact_no_shell_argument_shapes() -> None:
    prompt = build_review_prompt(_bundle(), "requirements_behavior")
    grok = validate_provider_spec(build_provider_spec("grok-4.5", prompt))
    synthetic = validate_provider_spec(build_provider_spec("synthetic/hf:zai-org/GLM-5.2", prompt))
    deepseek = validate_provider_spec(
        build_provider_spec("opencode/deepseek-v4-flash-free", prompt)
    )

    assert grok["command"][:3] == ["grok", "--single", prompt]
    assert grok["command"][-4:] == ["1", "--tools", "", "--verbatim"]
    assert synthetic["command"] == [
        "opencode",
        "run",
        prompt,
        "--pure",
        "--model",
        "synthetic/hf:zai-org/GLM-5.2",
        "--format",
        "json",
        "--agent",
        "plan",
    ]
    assert synthetic["provider_group"] == "synthetic:api.synthetic.new"
    assert deepseek["provider_group"] == "opencode:opencode.ai"


def test_aqg_council_004_minimal_environment_scrubs_unapproved_secrets() -> None:
    source = {
        "HOME": "/safe/home",
        "PATH": "/usr/bin",
        "LANG": "C.UTF-8",
        "SYNTHETIC_API_KEY": "approved-credential",
        "UNRELATED_SECRET": "must-not-leak",
        "GITHUB_TOKEN": "must-not-leak",
    }

    environment = minimal_environment(source, credential_names=["SYNTHETIC_API_KEY"])

    assert environment == {
        "HOME": "/safe/home",
        "PATH": "/usr/bin",
        "LANG": "C.UTF-8",
        "SYNTHETIC_API_KEY": "approved-credential",
        "CI": "1",
        "NO_COLOR": "1",
    }
    with pytest.raises(ConfigurationError, match="invalid environment"):
        minimal_environment(source, credential_names=["bad-name"])


def test_aqg_council_005_valid_output_creates_ballot_and_malformed_schema_fails(
    tmp_path: Path,
) -> None:
    bundle = _bundle()
    payload = _payload(bundle)
    captured: list[list[str]] = []

    def executor(arguments: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        captured.append(arguments)
        return _completed(json.dumps({"result": payload}))

    ballot, execution = collect_ballot(
        review_id="grok-review",
        model_id="grok-4.5",
        role="requirements_behavior",
        bundle=bundle,
        cwd=tmp_path,
        environment={"PATH": "/usr/bin"},
        timeout_seconds=10,
        executor=executor,
    )
    assert execution["exit_code"] == PASS
    assert ballot is not None
    assert validate_ballot(ballot, bundle=bundle) == ballot
    assert captured[0][0] == "grok"

    malformed = {**payload, "unexpected": True}

    def bad_executor(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _completed(json.dumps(malformed))

    rejected, failed = collect_ballot(
        review_id="bad-review",
        model_id="grok-4.5",
        role="requirements_behavior",
        bundle=bundle,
        cwd=tmp_path,
        environment={"PATH": "/usr/bin"},
        timeout_seconds=10,
        executor=bad_executor,
    )
    assert rejected is None
    assert failed["exit_code"] == CONFIGURATION_ERROR
    assert failed["status"].startswith("malformed provider review")


def test_aqg_council_006_timeout_and_start_failure_are_infrastructure_errors(
    tmp_path: Path,
) -> None:
    prompt = build_review_prompt(_bundle(), "test_evidence")
    spec = build_provider_spec("synthetic/hf:zai-org/GLM-5.2", prompt)

    def timeout(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(["opencode"], 1, output="partial")

    timed_out = execute_provider(
        spec,
        cwd=tmp_path,
        environment={"PATH": "/usr/bin"},
        timeout_seconds=1,
        executor=timeout,
    )
    assert timed_out["exit_code"] == INFRASTRUCTURE_ERROR
    assert timed_out["timed_out"] is True
    assert timed_out["status"] == "provider timed out"

    def missing(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("opencode")

    not_started = execute_provider(
        spec,
        cwd=tmp_path,
        environment={"PATH": "/usr/bin"},
        timeout_seconds=1,
        executor=missing,
    )
    assert not_started["exit_code"] == INFRASTRUCTURE_ERROR
    assert not_started["status"].startswith("provider could not start")


def test_aqg_council_007_ballots_and_results_are_versioned_and_advisory_only() -> None:
    bundle = _bundle()
    ballots = _clear_ballots(bundle)
    result = aggregate_ballots(bundle, ballots)

    assert all(validate_ballot(ballot, bundle=bundle) == ballot for ballot in ballots)
    assert validate_council_result(result, bundle=bundle) == result
    assert result["status"] == "advisory_clear"
    assert result["advisory_only"] is True
    assert "no human approval or release authority" in result["summary"]

    malformed_result = dict(result)
    malformed_result["provider_group_count"] = 99
    core = {key: value for key, value in malformed_result.items() if key != "result_sha256"}
    malformed_result["result_sha256"] = fingerprint(core)
    with pytest.raises(ConfigurationError, match="provider counts"):
        validate_council_result(malformed_result, bundle=bundle)

    impersonation = dict(ballots[0])
    impersonation["actor_type"] = "human"
    with pytest.raises(ConfigurationError, match="actor"):
        validate_ballot(impersonation, bundle=bundle)


def test_aqg_council_008_correlated_synthetic_models_count_as_one_provider_group() -> None:
    bundle = _bundle()
    ballots = _clear_ballots(bundle)
    result = aggregate_ballots(bundle, ballots)

    assert len(ballots) == 4
    assert result["provider_groups"] == [
        "opencode:opencode.ai",
        "synthetic:api.synthetic.new",
        "xai:grok.com",
    ]
    assert result["provider_group_count"] == 3
    assert result["complete"] is True


def test_aqg_council_009_any_valid_blocker_vetoes_a_clear_majority() -> None:
    bundle = _bundle()
    ballots = _clear_ballots(bundle)
    ballots[0] = _ballot(bundle, ballots[0]["reviewer"]["role"], verdict="block")

    result = aggregate_ballots(bundle, ballots)

    assert result["status"] == "advisory_blocked"
    assert len(result["blockers"]) == 1
    assert result["dissent"]["present"] is True
    assert "human attention" in result["summary"]


def test_aqg_council_010_disagreement_and_missing_quorum_remain_visible() -> None:
    bundle = _bundle()
    ballots = _clear_ballots(bundle)
    ballots[0] = _ballot(bundle, ballots[0]["reviewer"]["role"], verdict="concerns")
    disputed = aggregate_ballots(bundle, ballots)

    assert disputed["status"] == "advisory_dissent"
    assert disputed["dissent"]["present"] is True

    incomplete = aggregate_ballots(
        bundle,
        ballots[:2],
        required_roles=sorted(ROLES),
        minimum_provider_groups=3,
    )
    assert incomplete["status"] == "advisory_incomplete"
    assert incomplete["complete"] is False
    assert incomplete["missing_roles"]
    assert any("provider quorum" in reason for reason in incomplete["incomplete_reasons"])


def test_aqg_council_011_stale_ballot_scope_cannot_enter_quorum() -> None:
    old_bundle = _bundle()
    fresh_bundle = _bundle(source="def answer():\n    return 43\n")
    stale = _ballot(old_bundle, "requirements_behavior")

    with pytest.raises(ConfigurationError, match="stale"):
        validate_ballot(stale, bundle=fresh_bundle)
    result = aggregate_ballots(
        fresh_bundle,
        [stale],
        required_roles=["requirements_behavior"],
        minimum_provider_groups=1,
    )
    assert result["status"] == "advisory_incomplete"
    assert result["provider_group_count"] == 0
    assert any("stale" in reason for reason in result["incomplete_reasons"])


def test_aqg_council_012_evidence_is_exclusive_manifested_and_tamper_evident(
    tmp_path: Path,
) -> None:
    bundle = _bundle()
    ballots = _clear_ballots(bundle)
    result = aggregate_ballots(bundle, ballots)

    run_dir = write_council_evidence(tmp_path / "council", "review-001", bundle, ballots, result)
    verified = verify_council_evidence(run_dir)
    assert verified["ok"] is True
    assert (run_dir / "manifest.json").is_file()

    with pytest.raises(ConfigurationError, match="already exists"):
        write_council_evidence(tmp_path / "council", "review-001", bundle, ballots, result)

    (run_dir / "result.json").write_text("{}\n", encoding="utf-8")
    tampered = verify_council_evidence(run_dir)
    assert tampered["ok"] is False
    assert any("modified evidence" in error for error in tampered["errors"])
