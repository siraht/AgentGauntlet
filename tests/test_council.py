# Feature-Spec: AgentQualityGauntlet.ReviewCouncil AQG-COUNCIL-001 AQG-COUNCIL-002
# Feature-Spec: AgentQualityGauntlet.ReviewCouncil AQG-COUNCIL-003 AQG-COUNCIL-004
# Feature-Spec: AgentQualityGauntlet.ReviewCouncil AQG-COUNCIL-005 AQG-COUNCIL-006
# Feature-Spec: AgentQualityGauntlet.ReviewCouncil AQG-COUNCIL-007 AQG-COUNCIL-008
# Feature-Spec: AgentQualityGauntlet.ReviewCouncil AQG-COUNCIL-009 AQG-COUNCIL-010
# Feature-Spec: AgentQualityGauntlet.ReviewCouncil AQG-COUNCIL-011 AQG-COUNCIL-012
# Feature-Spec: AgentQualityGauntlet.ReviewCouncil AQG-COUNCIL-016
"""Contracts for the dependency-free, advisory-only review council core."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

from aqg.constants import CONFIGURATION_ERROR, INFRASTRUCTURE_ERROR, PASS
from aqg.council import (
    ROLES,
    _validate_findings,
    aggregate_ballots,
    build_candidate_bundle,
    build_review_prompt,
    canonical_json,
    create_ballot,
    fingerprint,
    provider_identity,
    validate_ballot,
    validate_candidate_bundle,
    validate_council_result,
    validate_review_payload,
    verify_council_evidence,
    write_council_evidence,
)
from aqg.council_providers import (
    GEMINI_DENY_ALL_POLICY,
    GEMINI_POLICY_FILENAME,
    PROMPT_FILENAME,
    SCHEMA_FILENAME,
    _claude_stdin_command,
    _gemini_stdin_command,
    build_file_provider_spec,
    build_provider_spec,
    collect_ballot,
    execute_provider,
    minimal_environment,
    review_payload_json_schema,
    validate_provider_spec,
)
from aqg.errors import ConfigurationError

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64
MODELS = {
    "adversarial": "grok-4.5",
    "requirements_behavior": "grok-4.5",
    "test_evidence": "codex/gpt-5.6-sol",
    "security_trust": "codex/gpt-5.6-sol",
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
                "oracle_resolutions": [],
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


def test_debt_baseline_purpose_is_explicit_and_cannot_authorize_release() -> None:
    purpose = json.dumps(
        {
            "purpose": "debt_baseline",
            "decision": "Review inherited debt only; this does not authorize release.",
        }
    )
    bundle = build_candidate_bundle(
        revision="candidate-123",
        base_revision="base-456",
        change_fingerprint=SHA_A,
        control_fingerprint=SHA_B,
        evidence_manifest_sha256=SHA_C,
        inputs={
            "controller/review-purpose.json": purpose,
            "current.diff.patch": "diff --git a/app.py b/app.py\n",
        },
    )

    prompt = build_review_prompt(bundle, "test_evidence")
    assert "REVIEW_PURPOSE=debt_baseline" in prompt
    assert "this does not authorize release" in prompt


def test_policy_maintenance_purpose_is_narrower_than_candidate_assurance() -> None:
    purpose = json.dumps(
        {
            "purpose": "policy_maintenance",
            "decision": "Review control changes only; do not certify unrelated implementation.",
        }
    )
    bundle = build_candidate_bundle(
        revision="candidate-123",
        base_revision="base-456",
        change_fingerprint=SHA_A,
        control_fingerprint=SHA_B,
        evidence_manifest_sha256=SHA_C,
        inputs={
            "controller/review-purpose.json": purpose,
            "current.diff.patch": "diff --git a/quality/policy.toml b/quality/policy.toml\n",
        },
    )

    prompt = build_review_prompt(bundle, "security_trust")
    assert "REVIEW_PURPOSE=policy_maintenance" in prompt
    assert "do not certify unrelated implementation" in prompt


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


def test_aqg_council_002_prompt_lists_only_citable_bundled_materials() -> None:
    bundle = _bundle(source='see "outside-report.json" in this manifest')
    prompt = build_review_prompt(bundle, "security_trust")
    marker = "VALID_EVIDENCE_MATERIALS="
    line = next(value for value in prompt.splitlines() if value.startswith(marker))

    materials = json.loads(line.removeprefix(marker))

    assert materials == [
        {"material": item["name"], "sha256": item["sha256"]} for item in bundle["materials"]
    ]
    assert all(item["material"] != "outside-report.json" for item in materials)
    assert "A file named inside a manifest" in prompt
    assert (
        'REQUIRED_FINDING_KEYS=["id","severity","category","claim","evidence_refs",'
        '"oracle_resolutions","recommendation"]' in prompt
    )


def test_authority_schema_prompt_command_and_payload_are_exact_contracts() -> None:
    import hashlib

    bundle = _bundle()
    prompt = build_review_prompt(bundle, "test_evidence")
    schema = review_payload_json_schema()
    command = build_provider_spec("grok-4.5", prompt)["command"]
    normalized = validate_review_payload(_payload(bundle, "concerns"))
    contracts = {
        "schema": (
            canonical_json(schema),
            "8e67c67f69aa7f5f5e6b959b2ddcd9c595765901904f8704797e42e202f569ef",
        ),
        "prompt": (
            prompt.encode(),
            "5cff6fd589973762d4bd30ab33206409f07c61ce9157fd8fdaca4387a8b5098f",
        ),
        "command": (
            canonical_json(command),
            "9741c50b7116e48e62fa56368ae6c2076b146b45e81518b52b397f96b64e035e",
        ),
        "payload": (
            canonical_json(normalized),
            "e967ef9c4212a548422e72e2882a788842d7abe9bd6d29d2315852dbbf8fe58b",
        ),
    }

    assert {
        name: hashlib.sha256(content).hexdigest() for name, (content, _) in contracts.items()
    } == {name: expected for name, (_, expected) in contracts.items()}


def test_aqg_council_003_provider_specs_have_exact_no_shell_argument_shapes() -> None:
    prompt = build_review_prompt(_bundle(), "requirements_behavior")
    grok = validate_provider_spec(build_provider_spec("grok-4.5", prompt))
    synthetic = validate_provider_spec(build_provider_spec("synthetic/hf:zai-org/GLM-5.2", prompt))
    deepseek = validate_provider_spec(
        build_provider_spec("opencode/deepseek-v4-flash-free", prompt)
    )
    codex = validate_provider_spec(build_provider_spec("codex/gpt-5.6-sol", prompt))
    gemini = validate_provider_spec(build_provider_spec("gemini/gemini-3-flash-preview", prompt))
    claude = validate_provider_spec(build_provider_spec("claude/sonnet", prompt))

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
    assert codex["provider_group"] == "openai:codex"
    assert codex["endpoint_origin"] == "local-subscription"
    assert codex["command"][-1] == prompt
    assert codex["command"][:2] == ["codex", "exec"]
    assert "--ignore-user-config" in codex["command"]
    assert "--ignore-rules" in codex["command"]
    assert "--ephemeral" in codex["command"]
    assert "--skip-git-repo-check" in codex["command"]
    assert codex["command"][codex["command"].index("--sandbox") + 1] == "read-only"
    assert codex["command"][codex["command"].index("--output-schema") + 1] == SCHEMA_FILENAME
    assert "--search" not in codex["command"]
    disabled = {
        codex["command"][index + 1]
        for index, argument in enumerate(codex["command"][:-1])
        if argument == "--disable"
    }
    assert {"shell_tool", "unified_exec", "standalone_web_search"} <= disabled
    assert gemini["provider_group"] == "google:gemini-cli"
    assert gemini["endpoint_origin"] == "oauth-personal-free-quota"
    assert gemini["command"] == [
        "gemini",
        "--prompt",
        prompt,
        "--model",
        "gemini-3-flash-preview",
        "--output-format",
        "json",
        "--approval-mode",
        "plan",
        "--admin-policy",
        GEMINI_POLICY_FILENAME,
        "--sandbox",
        "--skip-trust",
    ]
    assert claude["provider_group"] == "anthropic:claude-cli"
    assert claude["endpoint_origin"] == "local-subscription"
    assert claude["command"][-1] == prompt
    assert claude["command"][:2] == ["claude", "--print"]
    assert claude["command"][claude["command"].index("--tools") + 1] == ""
    assert "--no-session-persistence" in claude["command"]
    assert "--safe-mode" in claude["command"]
    assert "--strict-mcp-config" in claude["command"]

    grok_file = validate_provider_spec(build_file_provider_spec("grok-4.5"))
    synthetic_file = validate_provider_spec(
        build_file_provider_spec("synthetic/hf:zai-org/GLM-5.2")
    )
    codex_file = validate_provider_spec(build_file_provider_spec("codex/gpt-5.6-sol"))
    gemini_file = validate_provider_spec(build_file_provider_spec("gemini/gemini-3-flash-preview"))
    claude_file = validate_provider_spec(build_file_provider_spec("claude/sonnet"))
    assert grok_file["command"][:3] == ["grok", "--prompt-file", PROMPT_FILENAME]
    assert synthetic_file["command"][:3] == [
        "opencode",
        "run",
        "--pure",
    ]
    assert "--file" not in synthetic_file["command"]
    assert codex_file["command"][-1] == "-"
    assert gemini_file["command"] == _gemini_stdin_command("gemini/gemini-3-flash-preview")
    assert claude_file["command"] == _claude_stdin_command("claude/sonnet")

    tampered = dict(codex_file)
    tampered["command"] = list(codex_file["command"])
    tampered["command"].remove("--ignore-rules")
    with pytest.raises(ConfigurationError, match="protected argument shape"):
        validate_provider_spec(tampered)


def test_all_provider_identities_are_exact_contracts() -> None:
    expected = {
        "grok-4.5": ("grok", "xai:grok.com", "https://grok.com", "grok"),
        "synthetic/hf:zai-org/GLM-5.2": (
            "synthetic",
            "synthetic:api.synthetic.new",
            "https://api.synthetic.new/openai/v1",
            "synthetic:glm",
        ),
        "opencode/deepseek-v4-flash-free": (
            "opencode",
            "opencode:opencode.ai",
            "https://opencode.ai/zen/v1",
            "opencode:deepseek",
        ),
        "codex/gpt-5.6-sol": ("codex", "openai:codex", "local-subscription", "openai:gpt"),
        "gemini/gemini-3-flash-preview": (
            "gemini",
            "google:gemini-cli",
            "oauth-personal-free-quota",
            "google:gemini",
        ),
        "claude/sonnet": (
            "claude",
            "anthropic:claude-cli",
            "local-subscription",
            "anthropic:sonnet",
        ),
    }
    actual = {
        model: (
            identity["provider_id"],
            identity["provider_group"],
            identity["endpoint_origin"],
            identity["model_family"],
        )
        for model in expected
        for identity in (provider_identity(model),)
    }
    assert actual == expected
    assert provider_identity("synthetic/foo-bar-baz")["model_family"] == "synthetic:foo"
    assert provider_identity("claude/sonnet-latest-fast")["model_family"] == "anthropic:sonnet"
    with pytest.raises(ConfigurationError, match="^model_id must be a non-empty string$"):
        provider_identity(None)  # type: ignore[arg-type]


def test_all_file_provider_commands_and_protocols_are_exact() -> None:
    schema = canonical_json(review_payload_json_schema()).decode()
    codex_prefix = [
        "codex",
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--model",
        "gpt-5.6-sol",
        "--output-schema",
        SCHEMA_FILENAME,
        "--json",
        "--color",
        "never",
        "--cd",
        ".",
    ]
    for feature in (
        "apps",
        "browser_use",
        "browser_use_external",
        "computer_use",
        "image_generation",
        "in_app_browser",
        "multi_agent",
        "multi_agent_v2",
        "shell_tool",
        "skill_search",
        "standalone_web_search",
        "unified_exec",
        "workspace_dependencies",
    ):
        codex_prefix.extend(("--disable", feature))
    commands = {
        "grok-4.5": [
            "grok",
            "--prompt-file",
            PROMPT_FILENAME,
            "--model",
            "grok-4.5",
            "--output-format",
            "json",
            "--json-schema",
            schema,
            "--no-memory",
            "--no-subagents",
            "--disable-web-search",
            "--permission-mode",
            "plan",
            "--max-turns",
            "1",
            "--tools",
            "",
            "--verbatim",
        ],
        "synthetic/hf:zai-org/GLM-5.2": [
            "opencode",
            "run",
            "--pure",
            "--model",
            "synthetic/hf:zai-org/GLM-5.2",
            "--format",
            "json",
            "--agent",
            "plan",
        ],
        "opencode/deepseek-v4-flash-free": [
            "opencode",
            "run",
            "--pure",
            "--model",
            "opencode/deepseek-v4-flash-free",
            "--format",
            "json",
            "--agent",
            "plan",
        ],
        "codex/gpt-5.6-sol": [*codex_prefix, "-"],
        "gemini/gemini-3-flash-preview": [
            "gemini",
            "--prompt",
            "",
            "--model",
            "gemini-3-flash-preview",
            "--output-format",
            "json",
            "--approval-mode",
            "plan",
            "--admin-policy",
            GEMINI_POLICY_FILENAME,
            "--sandbox",
            "--skip-trust",
        ],
        "claude/sonnet": [
            "claude",
            "--print",
            "--model",
            "sonnet",
            "--output-format",
            "json",
            "--json-schema",
            schema,
            "--permission-mode",
            "plan",
            "--tools",
            "",
            "--no-session-persistence",
            "--disable-slash-commands",
            "--safe-mode",
            "--no-chrome",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--setting-sources",
            "",
        ],
    }
    protocols = {
        "grok-4.5": ("grok", "json-document"),
        "synthetic/hf:zai-org/GLM-5.2": ("opencode", "json-or-jsonl"),
        "opencode/deepseek-v4-flash-free": ("opencode", "json-or-jsonl"),
        "codex/gpt-5.6-sol": ("codex", "jsonl"),
        "gemini/gemini-3-flash-preview": ("gemini", "json-document"),
        "claude/sonnet": ("claude", "json-document"),
    }
    prompt = "bounded review prompt"
    inline_commands = {
        "grok-4.5": [commands["grok-4.5"][0], "--single", prompt, *commands["grok-4.5"][3:]],
        "synthetic/hf:zai-org/GLM-5.2": [
            *commands["synthetic/hf:zai-org/GLM-5.2"][:2],
            prompt,
            *commands["synthetic/hf:zai-org/GLM-5.2"][2:],
        ],
        "opencode/deepseek-v4-flash-free": [
            *commands["opencode/deepseek-v4-flash-free"][:2],
            prompt,
            *commands["opencode/deepseek-v4-flash-free"][2:],
        ],
        "codex/gpt-5.6-sol": [*commands["codex/gpt-5.6-sol"][:-1], prompt],
        "gemini/gemini-3-flash-preview": [
            *commands["gemini/gemini-3-flash-preview"][:2],
            prompt,
            *commands["gemini/gemini-3-flash-preview"][3:],
        ],
        "claude/sonnet": [*commands["claude/sonnet"], prompt],
    }
    for model, expected_command in commands.items():
        file_spec = validate_provider_spec(build_file_provider_spec(model))
        inline_spec = validate_provider_spec(build_provider_spec(model, prompt))
        assert file_spec["command"] == expected_command
        assert inline_spec["command"] == inline_commands[model]
        assert (file_spec["executable"], file_spec["output_protocol"]) == protocols[model]
        assert (inline_spec["executable"], inline_spec["output_protocol"]) == protocols[model]


def test_every_file_provider_command_rejects_argument_tampering() -> None:
    models = (
        "grok-4.5",
        "synthetic/hf:zai-org/GLM-5.2",
        "opencode/deepseek-v4-flash-free",
        "codex/gpt-5.6-sol",
        "gemini/gemini-3-flash-preview",
        "claude/sonnet",
    )
    prompt_slots = {"codex/gpt-5.6-sol": {43}, "gemini/gemini-3-flash-preview": {2}}
    for model in models:
        spec = build_file_provider_spec(model)
        for index, argument in enumerate(spec["command"]):
            if index in prompt_slots.get(model, set()):
                continue
            tampered = dict(spec)
            tampered["command"] = list(spec["command"])
            tampered["command"][index] = argument + "-tampered"
            with pytest.raises(ConfigurationError, match="command|protected argument shape"):
                validate_provider_spec(tampered)


def test_provider_command_failures_name_the_exact_protected_adapter() -> None:
    expected = {
        "grok-4.5": "grok provider command does not match the protected argument shape",
        "synthetic/hf:zai-org/GLM-5.2": (
            "OpenCode provider command does not match the protected argument shape"
        ),
        "opencode/deepseek-v4-flash-free": (
            "OpenCode provider command does not match the protected argument shape"
        ),
        "codex/gpt-5.6-sol": "Codex provider command does not match the protected argument shape",
        "gemini/gemini-3-flash-preview": (
            "Gemini provider command does not match the protected argument shape"
        ),
        "claude/sonnet": "Claude provider command does not match the protected argument shape",
    }
    for model, message in expected.items():
        tampered = build_file_provider_spec(model)
        tampered["command"] = list(tampered["command"])
        tampered["command"][1] += "-tampered"
        with pytest.raises(ConfigurationError) as raised:
            validate_provider_spec(tampered)
        assert str(raised.value) == message


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

    def executor(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.append(arguments)
        if arguments[0] == "grok":
            assert kwargs["input"] is None
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
    assert captured[0][1:3] == ["--prompt-file", PROMPT_FILENAME]
    assert (tmp_path / PROMPT_FILENAME).read_text(encoding="utf-8") == build_review_prompt(
        bundle, "requirements_behavior"
    )

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


def test_oracle_resolution_payload_is_structured_and_fail_closed() -> None:
    payload = _payload(_bundle(), "concerns")
    finding = payload["findings"][0]
    finding["oracle_resolutions"] = [
        {
            "path": "tests/test_app.py",
            "removed_oracle": "assert old",
            "replacement_oracle": "assert new",
            "preserved_behavior": "the result is still checked exactly",
        }
    ]

    normalized = validate_review_payload(payload)
    assert normalized["findings"][0]["oracle_resolutions"] == finding["oracle_resolutions"]

    invalid_values: tuple[Any, ...] = (
        None,
        "not-an-array",
        [None],
        [{"path": "tests/test_app.py"}],
        [
            {
                "path": "tests/test_app.py",
                "removed_oracle": "assert old",
                "replacement_oracle": "assert new",
                "preserved_behavior": "",
            }
        ],
    )
    for invalid in invalid_values:
        candidate = json.loads(json.dumps(payload))
        candidate["findings"][0]["oracle_resolutions"] = invalid
        with pytest.raises(ConfigurationError):
            validate_review_payload(candidate)


def test_finding_validation_reports_exact_invalid_field_and_order() -> None:
    bundle = _bundle()
    first = _payload(bundle, "concerns")["findings"][0]
    second = {**first, "id": "A-0"}
    payload = _payload(bundle, "concerns")
    payload["findings"] = [first, second]
    assert [item["id"] for item in validate_review_payload(payload)["findings"]] == ["A-0", "F-1"]

    invalid_cases = (
        (None, "review payload findings must be an array"),
        ([None], "findings[0] must be an object"),
        ([{"id": "F-1"}], "findings[0] is missing"),
        ([{**first, "id": ""}], "findings[0].id must be a non-empty string"),
        ([{**first, "severity": "invalid"}], "findings[0] has duplicate id or invalid severity"),
        ([first, dict(first)], "findings[1] has duplicate id or invalid severity"),
        ([{**first, "evidence_refs": None}], "findings[0].evidence_refs must be an array"),
        (
            [{**first, "oracle_resolutions": None}],
            "findings[0].oracle_resolutions must be an array",
        ),
        ([{**first, "category": ""}], "findings[0].category must be a non-empty string"),
        ([{**first, "claim": ""}], "findings[0].claim must be a non-empty string"),
        (
            [{**first, "recommendation": ""}],
            "findings[0].recommendation must be a non-empty string",
        ),
    )
    for findings, message in invalid_cases:
        candidate = _payload(bundle, "concerns")
        candidate["findings"] = findings
        with pytest.raises(ConfigurationError, match=f"^{re.escape(message)}(?:$|:)"):
            validate_review_payload(candidate)


def test_extracted_finding_validator_preserves_sorting_and_duplicate_rejection() -> None:
    first = _payload(_bundle(), "concerns")["findings"][0]
    second = {**first, "id": "A-0"}

    assert [item["id"] for item in _validate_findings([first, second])] == ["A-0", "F-1"]
    with pytest.raises(
        ConfigurationError, match=r"findings\[1\] has duplicate id or invalid severity"
    ):
        _validate_findings([first, dict(first)])


def test_oracle_resolution_validation_reports_exact_invalid_field() -> None:
    bundle = _bundle()
    finding = _payload(bundle, "concerns")["findings"][0]
    resolution = {
        "path": "tests/test_app.py",
        "removed_oracle": "assert old",
        "replacement_oracle": "assert new",
        "preserved_behavior": "the result remains checked",
    }
    invalid_cases = (
        ([None], "findings[0].oracle_resolutions[0] must be an object"),
        ([{"path": "tests/test_app.py"}], "oracle resolution is missing"),
        ([{**resolution, "unexpected": "x"}], "oracle resolution has unknown fields"),
        ([{**resolution, "path": ""}], "oracle resolution path must be a non-empty string"),
    )
    for resolutions, message in invalid_cases:
        payload = _payload(bundle, "concerns")
        payload["findings"][0] = {**finding, "oracle_resolutions": resolutions}
        with pytest.raises(ConfigurationError, match=re.escape(message)):
            validate_review_payload(payload)


def test_aqg_council_005_codex_is_read_only_isolated_and_schema_bound(
    tmp_path: Path,
) -> None:
    bundle = _bundle()
    payload = _payload(bundle)

    def executor(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert arguments[:2] == ["codex", "exec"]
        assert arguments[-1] == "-"
        assert kwargs["cwd"] == tmp_path
        assert kwargs["input"] == build_review_prompt(bundle, "test_evidence")
        schema = json.loads((tmp_path / SCHEMA_FILENAME).read_text(encoding="utf-8"))
        assert schema == review_payload_json_schema()
        evidence_ref = schema["properties"]["findings"]["items"]["properties"]["evidence_refs"][
            "items"
        ]
        oracle_resolution = schema["properties"]["findings"]["items"]["properties"][
            "oracle_resolutions"
        ]["items"]
        assert evidence_ref["required"] == ["material", "sha256", "line"]
        assert evidence_ref["properties"]["line"]["type"] == ["integer", "null"]
        assert oracle_resolution["required"] == [
            "path",
            "removed_oracle",
            "replacement_oracle",
            "preserved_behavior",
        ]
        event = {"type": "item.completed", "item": {"type": "agent_message", "text": payload}}
        return _completed(json.dumps(event))

    ballot, execution = collect_ballot(
        review_id="codex-review",
        model_id="codex/gpt-5.6-sol",
        role="test_evidence",
        bundle=bundle,
        cwd=tmp_path,
        environment={"HOME": "/safe/home", "PATH": "/usr/bin"},
        timeout_seconds=10,
        executor=executor,
    )

    assert execution["exit_code"] == PASS
    assert ballot is not None
    assert ballot["reviewer"]["provider_group"] == "openai:codex"


def test_aqg_council_005_gemini_is_tool_denied_and_isolated(tmp_path: Path) -> None:
    bundle = _bundle()
    payload = _payload(bundle)

    def executor(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert arguments[0] == "gemini"
        assert arguments[arguments.index("--admin-policy") + 1] == GEMINI_POLICY_FILENAME
        assert "--allowed-tools" not in arguments
        assert "--allowed-mcp-server-names" not in arguments
        assert kwargs["cwd"] == tmp_path
        assert kwargs["input"] == build_review_prompt(bundle, "operability_rollback")
        assert (tmp_path / GEMINI_POLICY_FILENAME).read_text(
            encoding="utf-8"
        ) == GEMINI_DENY_ALL_POLICY
        return _completed(json.dumps({"response": payload}))

    ballot, execution = collect_ballot(
        review_id="gemini-review",
        model_id="gemini/gemini-3-flash-preview",
        role="operability_rollback",
        bundle=bundle,
        cwd=tmp_path,
        environment={"HOME": "/safe/home", "PATH": "/usr/bin"},
        timeout_seconds=10,
        executor=executor,
    )

    assert execution["exit_code"] == PASS
    assert ballot is not None
    assert ballot["reviewer"]["provider_group"] == "google:gemini-cli"


def test_aqg_council_005_claude_is_tool_denied_and_ephemeral(tmp_path: Path) -> None:
    bundle = _bundle()
    payload = _payload(bundle)

    def executor(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert arguments[0] == "claude"
        assert arguments[arguments.index("--tools") + 1] == ""
        assert "--no-session-persistence" in arguments
        assert "--safe-mode" in arguments
        assert "--disable-slash-commands" in arguments
        assert kwargs["cwd"] == tmp_path
        assert kwargs["input"] == build_review_prompt(bundle, "operability_rollback")
        return _completed(json.dumps({"structured_output": payload}))

    ballot, execution = collect_ballot(
        review_id="claude-review",
        model_id="claude/sonnet",
        role="operability_rollback",
        bundle=bundle,
        cwd=tmp_path,
        environment={"HOME": "/safe/home", "PATH": "/usr/bin"},
        timeout_seconds=10,
        executor=executor,
    )

    assert execution["exit_code"] == PASS
    assert ballot is not None
    assert ballot["reviewer"]["provider_group"] == "anthropic:claude-cli"


@pytest.mark.parametrize(
    "wrapped",
    [
        {"structuredOutput": {"placeholder": True}},
        {
            "type": "text",
            "part": {
                "text": "Analysis complete.\n```json\nPAYLOAD\n```\n",
            },
        },
    ],
)
def test_aqg_council_005_real_cli_wrappers_preserve_strict_payload_validation(
    tmp_path: Path, wrapped: dict[str, Any]
) -> None:
    bundle = _bundle()
    payload = _payload(bundle)
    if "structuredOutput" in wrapped:
        wrapped["structuredOutput"] = payload
    else:
        wrapped["part"]["text"] = wrapped["part"]["text"].replace("PAYLOAD", json.dumps(payload))

    def executor(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _completed(json.dumps(wrapped))

    ballot, execution = collect_ballot(
        review_id="wrapped-review",
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


def test_aqg_council_005_out_of_bundle_citation_fails_the_member(
    tmp_path: Path,
) -> None:
    bundle = _bundle()
    payload = _payload(bundle)
    payload["findings"] = [
        {
            "id": "OUTSIDE-1",
            "severity": "warning",
            "category": "evidence",
            "claim": "This cites material the controller did not provide.",
            "evidence_refs": [
                {
                    "material": "outside.txt",
                    "sha256": "sha256:" + "0" * 64,
                }
            ],
            "oracle_resolutions": [],
            "recommendation": "Cite an exact bundled material.",
        }
    ]
    payload["verdict"] = "concerns"

    def executor(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _completed(json.dumps(payload))

    ballot, execution = collect_ballot(
        review_id="outside-review",
        model_id="grok-4.5",
        role="requirements_behavior",
        bundle=bundle,
        cwd=tmp_path,
        environment={"PATH": "/usr/bin"},
        timeout_seconds=10,
        executor=executor,
    )

    assert ballot is None
    assert execution["exit_code"] == CONFIGURATION_ERROR
    assert "outside the candidate bundle" in execution["status"]


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


def test_aqg_council_008_repeated_codex_roles_count_as_one_provider_group() -> None:
    bundle = _bundle()
    all_ballots = _clear_ballots(bundle)
    ballots = [ballot for ballot in all_ballots if ballot["reviewer"]["role"] != "adversarial"]
    result = aggregate_ballots(bundle, all_ballots)

    assert len(ballots) == 4
    assert len(all_ballots) == 5
    assert result["provider_groups"] == [
        "openai:codex",
        "opencode:opencode.ai",
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
