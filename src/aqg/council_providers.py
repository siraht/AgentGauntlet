"""No-shell provider adapters for the advisory review council."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .constants import CONFIGURATION_ERROR, INFRASTRUCTURE_ERROR, PASS
from .council import (
    build_review_prompt,
    canonical_json,
    create_ballot,
    fingerprint,
    provider_identity,
    validate_ballot,
    validate_candidate_bundle,
    validate_review_payload,
)
from .errors import ConfigurationError

PROVIDER_SPEC_SCHEMA_VERSION = 1
EXECUTION_SCHEMA_VERSION = 1
PROMPT_FILENAME = "review-prompt.txt"
_ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_BASE_ENV_NAMES = (
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "TMPDIR",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
)

REVIEW_PAYLOAD_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "confidence", "findings", "limitations"],
    "properties": {
        "verdict": {"enum": ["clear", "concerns", "block", "abstain"]},
        "confidence": {"enum": ["low", "medium", "high"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "severity",
                    "category",
                    "claim",
                    "evidence_refs",
                    "recommendation",
                ],
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "severity": {"enum": ["info", "warning", "blocker"]},
                    "category": {"type": "string", "minLength": 1},
                    "claim": {"type": "string", "minLength": 1},
                    "recommendation": {"type": "string", "minLength": 1},
                    "evidence_refs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["material", "sha256"],
                            "properties": {
                                "material": {"type": "string", "minLength": 1},
                                "sha256": {
                                    "type": "string",
                                    "pattern": "^sha256:[0-9a-f]{64}$",
                                },
                                "line": {"type": "integer", "minimum": 1},
                            },
                        },
                    },
                },
            },
        },
        "limitations": {"type": "array", "items": {"type": "string", "minLength": 1}},
    },
}
_PROVIDER_SPEC_FIELDS = {
    "schema_version",
    "kind",
    "advisory_only",
    "provider_id",
    "provider_group",
    "endpoint_origin",
    "model_family",
    "model_id",
    "executable",
    "output_protocol",
    "command",
}


def minimal_environment(
    source: Mapping[str, str] | None = None,
    *,
    credential_names: Sequence[str] = (),
) -> dict[str, str]:
    """Copy only runtime essentials and explicitly named credential variables."""
    source = source if source is not None else os.environ
    names = [*_BASE_ENV_NAMES, *credential_names]
    invalid = [name for name in names if not _ENV_NAME.fullmatch(name)]
    if invalid:
        raise ConfigurationError(f"invalid environment variable name: {invalid[0]!r}")
    environment = {name: source[name] for name in names if name in source}
    environment.update({"CI": "1", "NO_COLOR": "1"})
    return environment


def build_provider_spec(model_id: str, prompt: str) -> dict[str, Any]:
    """Return an exact argument array for one supported local CLI."""
    identity = provider_identity(model_id)
    if identity["provider_id"] == "grok":
        command = _grok_command(model_id, prompt)
        protocol = "json-document"
        executable = "grok"
    else:
        command = _opencode_command(model_id, prompt)
        protocol = "json-or-jsonl"
        executable = "opencode"
    return {
        "schema_version": PROVIDER_SPEC_SCHEMA_VERSION,
        "kind": "aqg-council-provider-spec",
        "advisory_only": True,
        **identity,
        "model_id": model_id,
        "executable": executable,
        "output_protocol": protocol,
        "command": command,
    }


def build_file_provider_spec(model_id: str, prompt_path: str = PROMPT_FILENAME) -> dict[str, Any]:
    """Return an exact file/stdin provider command that avoids argument limits."""
    if prompt_path != PROMPT_FILENAME:
        raise ConfigurationError("provider prompt file must use the isolated fixed filename")
    identity = provider_identity(model_id)
    if identity["provider_id"] == "grok":
        command = _grok_file_command(model_id, prompt_path)
        protocol = "json-document"
        executable = "grok"
    else:
        command = _opencode_stdin_command(model_id)
        protocol = "json-or-jsonl"
        executable = "opencode"
    return {
        "schema_version": PROVIDER_SPEC_SCHEMA_VERSION,
        "kind": "aqg-council-provider-spec",
        "advisory_only": True,
        **identity,
        "model_id": model_id,
        "executable": executable,
        "output_protocol": protocol,
        "command": command,
    }


def _grok_command(model_id: str, prompt: str) -> list[str]:
    schema = canonical_json(REVIEW_PAYLOAD_JSON_SCHEMA).decode("utf-8")
    return [
        "grok",
        "--single",
        prompt,
        "--model",
        model_id,
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
    ]


def _grok_file_command(model_id: str, prompt_path: str) -> list[str]:
    command = _grok_command(model_id, "")
    command[1:3] = ["--prompt-file", prompt_path]
    return command


def _opencode_command(model_id: str, prompt: str) -> list[str]:
    return [
        "opencode",
        "run",
        prompt,
        "--pure",
        "--model",
        model_id,
        "--format",
        "json",
        "--agent",
        "plan",
    ]


def _opencode_stdin_command(model_id: str) -> list[str]:
    command = _opencode_command(model_id, "")
    del command[2]
    return command


def validate_provider_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Validate that provider identity and exact no-shell command agree."""
    if not isinstance(spec, Mapping):
        raise ConfigurationError("provider spec must be an object")
    value = dict(spec)
    if set(value) != _PROVIDER_SPEC_FIELDS:
        raise ConfigurationError("provider spec fields are incomplete or unknown")
    _validate_provider_header(value)
    _validate_provider_identity(value)
    _validate_provider_command(value)
    return value


def _validate_provider_header(value: Mapping[str, Any]) -> None:
    if (
        value["schema_version"] != PROVIDER_SPEC_SCHEMA_VERSION
        or value["kind"] != "aqg-council-provider-spec"
        or value["advisory_only"] is not True
    ):
        raise ConfigurationError("provider spec version or advisory marker is invalid")


def _validate_provider_identity(value: Mapping[str, Any]) -> None:
    expected_identity = provider_identity(str(value["model_id"]))
    if any(value.get(key) != expected for key, expected in expected_identity.items()):
        raise ConfigurationError("provider spec identity does not match model namespace")


def _validate_provider_command(value: Mapping[str, Any]) -> None:
    command = _command_array(value["command"])
    if len(command) < 3:
        raise ConfigurationError("provider command is missing its prompt argument")
    if command[0] != value["executable"]:
        raise ConfigurationError("provider executable does not match command")
    _validate_exact_provider_command(value, command)


def _command_array(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(arg, str) for arg in value):
        raise ConfigurationError("provider command must be a non-empty string array")
    return value


def _validate_exact_provider_command(value: Mapping[str, Any], command: list[str]) -> None:
    if value["executable"] == "grok" and not _valid_grok_command(value["model_id"], command):
        raise ConfigurationError(
            "grok provider command does not match the protected argument shape"
        )
    if value["executable"] == "opencode" and not _valid_opencode_command(
        value["model_id"], command
    ):
        raise ConfigurationError(
            "OpenCode provider command does not match the protected argument shape"
        )


def _valid_grok_command(model_id: str, command: list[str]) -> bool:
    inline = len(command) > 2 and command == _grok_command(model_id, command[2])
    attached = command == _grok_file_command(model_id, PROMPT_FILENAME)
    return inline or attached


def _valid_opencode_command(model_id: str, command: list[str]) -> bool:
    inline = len(command) > 2 and command == _opencode_command(model_id, command[2])
    stdin = command == _opencode_stdin_command(model_id)
    return inline or stdin


def execute_provider(
    spec: Mapping[str, Any],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    executor: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    monotonic: Callable[[], float] = time.monotonic,
    stdin_text: str | None = None,
) -> dict[str, Any]:
    """Execute an exact argument array and normalize timeout/process failures."""
    normalized = validate_provider_spec(spec)
    isolated = _validate_execution_inputs(cwd, timeout_seconds)
    started = monotonic()
    return _invoke_provider(
        normalized,
        isolated,
        environment,
        timeout_seconds,
        executor,
        monotonic,
        started,
        stdin_text,
    )


def _validate_execution_inputs(cwd: Path, timeout_seconds: float) -> Path:
    if timeout_seconds <= 0:
        raise ConfigurationError("provider timeout must be positive")
    isolated = Path(cwd)
    if not isolated.is_dir():
        raise ConfigurationError("provider cwd must be an existing isolated directory")
    return isolated


def _invoke_provider(
    spec: Mapping[str, Any],
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    executor: Callable[..., subprocess.CompletedProcess[str]],
    monotonic: Callable[[], float],
    started: float,
    stdin_text: str | None,
) -> dict[str, Any]:
    try:
        completed = executor(
            spec["command"],
            cwd=cwd,
            env=dict(environment),
            capture_output=True,
            text=True,
            input=stdin_text,
            timeout=timeout_seconds,
            check=False,
        )
        return _completed_provider_execution(spec, completed, monotonic, started)
    except subprocess.TimeoutExpired as exc:
        return _execution_result(
            spec,
            INFRASTRUCTURE_ERROR,
            "provider timed out",
            None,
            _text(exc.stdout),
            _text(exc.stderr),
            _duration_ms(monotonic, started),
            True,
        )
    except OSError as exc:
        return _execution_result(
            spec,
            INFRASTRUCTURE_ERROR,
            f"provider could not start: {exc}",
            None,
            "",
            "",
            _duration_ms(monotonic, started),
            False,
        )


def _completed_provider_execution(
    spec: Mapping[str, Any],
    completed: subprocess.CompletedProcess[str],
    monotonic: Callable[[], float],
    started: float,
) -> dict[str, Any]:
    stdout = _text(completed.stdout)
    stderr = _text(completed.stderr)
    passed = completed.returncode == 0 and bool(stdout.strip())
    status = (
        "completed"
        if passed
        else "provider returned no review output"
        if completed.returncode == 0
        else "provider process failed"
    )
    return _execution_result(
        spec,
        PASS if passed else INFRASTRUCTURE_ERROR,
        status,
        completed.returncode,
        stdout,
        stderr,
        _duration_ms(monotonic, started),
        False,
    )


def _duration_ms(monotonic: Callable[[], float], started: float) -> int:
    return max(0, int((monotonic() - started) * 1000))


def _execution_result(
    spec: Mapping[str, Any],
    exit_code: int,
    status: str,
    raw_exit_code: int | None,
    stdout: str,
    stderr: str,
    duration_ms: int,
    timed_out: bool,
) -> dict[str, Any]:
    return {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "kind": "aqg-council-provider-execution",
        "advisory_only": True,
        "provider_id": spec["provider_id"],
        "provider_group": spec["provider_group"],
        "model_id": spec["model_id"],
        "exit_code": exit_code,
        "status": status,
        "raw_exit_code": raw_exit_code,
        "timed_out": timed_out,
        "duration_ms": duration_ms,
        "command_sha256": fingerprint(spec["command"]),
        "response_sha256": fingerprint(stdout),
        "stdout": stdout,
        "stderr": stderr,
    }


def collect_ballot(
    *,
    review_id: str,
    model_id: str,
    role: str,
    bundle: Mapping[str, Any],
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    executor: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Run one isolated reviewer and create a ballot only from valid JSON."""
    normalized_bundle = validate_candidate_bundle(bundle)
    prompt = build_review_prompt(normalized_bundle, role)
    prompt_path = Path(cwd) / PROMPT_FILENAME
    prompt_path.write_text(prompt, encoding="utf-8")
    spec = build_file_provider_spec(model_id)
    execution = execute_provider(
        spec,
        cwd=cwd,
        environment=environment,
        timeout_seconds=timeout_seconds,
        executor=executor,
        monotonic=monotonic,
        stdin_text=prompt if spec["provider_id"] != "grok" else None,
    )
    if execution["exit_code"] != PASS:
        return None, execution
    try:
        payload = validate_review_payload(_extract_review_payload(execution["stdout"]))
    except ConfigurationError as exc:
        return None, _malformed_execution(execution, exc)
    try:
        ballot = create_ballot(
            review_id=review_id,
            model_id=model_id,
            role=role,
            bundle=normalized_bundle,
            payload=payload,
            prompt_sha256=fingerprint(prompt),
            response_sha256=execution["response_sha256"],
            command_sha256=execution["command_sha256"],
            duration_ms=execution["duration_ms"],
        )
        ballot = validate_ballot(ballot, bundle=normalized_bundle)
    except ConfigurationError as exc:
        return None, _malformed_execution(execution, exc)
    return ballot, execution


def _malformed_execution(execution: Mapping[str, Any], error: ConfigurationError) -> dict[str, Any]:
    failed = dict(execution)
    failed.update(
        {
            "exit_code": CONFIGURATION_ERROR,
            "status": f"malformed provider review: {error}",
        }
    )
    return failed


def _extract_review_payload(stdout: str) -> dict[str, Any]:
    candidates: list[Any] = []
    try:
        candidates.append(json.loads(stdout))
    except json.JSONDecodeError:
        for line in stdout.splitlines():
            try:
                candidates.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    for candidate in candidates:
        payload = _find_payload(candidate)
        if payload is not None:
            return payload
    raise ConfigurationError("provider output contains no JSON review payload")


def _find_payload(value: Any, depth: int = 0) -> dict[str, Any] | None:
    pending = [(value, depth)]
    while pending:
        current, current_depth = pending.pop()
        if current_depth > 5:
            continue
        direct = _direct_payload(current)
        if direct is not None:
            return direct
        pending.extend(_payload_children(current, current_depth + 1))
    return None


def _direct_payload(value: Any) -> dict[str, Any] | None:
    required = {"verdict", "confidence", "findings", "limitations"}
    return dict(value) if isinstance(value, Mapping) and required <= set(value) else None


def _payload_children(value: Any, depth: int) -> list[tuple[Any, int]]:
    if isinstance(value, Mapping):
        keys = (
            "structuredOutput",
            "result",
            "output",
            "content",
            "text",
            "part",
            "message",
        )
        return [(value[key], depth) for key in reversed(keys) if key in value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [(item, depth) for item in value]
    if isinstance(value, str):
        return _decoded_child(value, depth)
    return []


def _decoded_child(value: str, depth: int) -> list[tuple[Any, int]]:
    decoded: list[tuple[Any, int]] = []
    candidates = [value.strip()]
    candidates.extend(
        match.group(1).strip()
        for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", value, re.IGNORECASE)
    )
    for candidate in candidates:
        decoded.extend((item, depth) for item in _embedded_json(candidate))
    return decoded


def _embedded_json(value: str) -> list[Any]:
    decoded: list[Any] = []
    decoder = json.JSONDecoder()
    starts = [index for index, character in enumerate(value) if character in "[{"][:100]
    for start in starts:
        try:
            item, _ = decoder.raw_decode(value[start:])
        except json.JSONDecodeError:
            continue
        decoded.append(item)
    return decoded


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""
