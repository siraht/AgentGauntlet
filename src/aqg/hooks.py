"""Local Codex and Claude Code guard hooks."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .constants import CONFIGURATION_ERROR, PASS
from .errors import ConfigurationError
from .maintenance import load_maintenance_request
from .policy import human_review_patterns, load_policy, policy_override_enabled, protected_patterns
from .runner import run_profile
from .util import matches_any


def _collect_strings(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            output.extend(_collect_strings(child, f"{prefix}.{key}" if prefix else str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            output.extend(_collect_strings(child, f"{prefix}[{index}]"))
    elif isinstance(value, str):
        output.append((prefix, value))
    return output


def _patch_paths(patch: str) -> list[str]:
    paths: list[str] = []
    for line in patch.splitlines():
        match = re.match(r"(?:\*\*\* (?:Add|Update|Delete) File:|\+\+\+ b/|--- a/)\s*(.+)", line)
        if match:
            path = match.group(1).strip()
            if path != "/dev/null":
                paths.append(path)
    return paths


def _patch_changes(patch: str) -> list[dict[str, str]]:
    operations = {"Add": "add", "Update": "modify", "Delete": "delete"}
    changes: list[dict[str, str]] = []
    for line in patch.splitlines():
        match = re.match(r"\*\*\* (Add|Update|Delete) File:\s*(.+)", line)
        if match:
            changes.append(
                {"path": match.group(2).strip(), "operation": operations[match.group(1)]}
            )
    return changes


def _direct_write_paths(tool_name: str, tool_input: Any) -> list[str]:
    canonical = tool_name.lower()
    paths: list[str] = []
    verbs = (
        "write",
        "edit",
        "update",
        "create",
        "delete",
        "remove",
        "move",
        "rename",
        "patch",
        "put",
        "upload",
    )
    if canonical in {"edit", "write", "multiedit", "notebookedit", "apply_patch"} or any(
        verb in canonical for verb in verbs
    ):
        for key, value in _collect_strings(tool_input):
            if key.lower().rsplit(".", 1)[-1] in {
                "file_path",
                "filepath",
                "path",
                "filename",
                "file",
            }:
                paths.append(value)
    if isinstance(tool_input, dict):
        for key in ("patch", "command", "diff"):
            if isinstance(tool_input.get(key), str):
                paths.extend(_patch_paths(tool_input[key]))
    return paths


def _direct_write_changes(root: Path, tool_name: str, tool_input: Any) -> list[dict[str, str]]:
    if isinstance(tool_input, dict):
        for key in ("patch", "diff"):
            if isinstance(tool_input.get(key), str):
                changes = _patch_changes(tool_input[key])
                if changes:
                    return changes
    canonical = tool_name.lower()
    if any(token in canonical for token in ("delete", "remove")):
        operation = "delete"
    else:
        operation = "modify"
    changes = []
    for path in _direct_write_paths(tool_name, tool_input):
        normalized = _normalize(root, path)
        inferred = operation
        if operation == "modify" and not (root / normalized).exists():
            inferred = "add"
        changes.append({"path": normalized, "operation": inferred})
    return changes


def _normalize(root: Path, value: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return value.replace("\\", "/").lstrip("./")


def _command_policy_writes(command: str, patterns: list[str]) -> list[str]:
    write_operation = re.compile(
        r"(^|[;&|]\s*|\s)(?:rm|mv|cp|install|truncate|tee|sed\s+-i|perl\s+-pi|python(?:3)?\s+-c|ruby\s+-e|node\s+-e|chmod|chown|git\s+(?:checkout|restore|reset))\b|>",
        re.IGNORECASE,
    )
    if not write_operation.search(command):
        return []
    touched = [path for path in _patch_paths(command) if matches_any(path, patterns)]
    for pattern in patterns:
        stem = pattern.replace("**", "").rstrip("/*")
        if stem and stem in command:
            touched.append(pattern)
    return sorted(set(touched))


def hook_pretool(root: Path) -> int:
    policy = load_policy(root)
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"AQG hook received invalid JSON: {exc}", file=sys.stderr)
        return CONFIGURATION_ERROR
    maintenance_enabled = policy_override_enabled(policy)
    authorized: set[tuple[str, str]] = set()
    if maintenance_enabled:
        request_env = str(
            policy.get("policy", {}).get(
                "maintenance_request_env",
                "AQG_MAINTENANCE_REQUEST",
            )
        )
        request_id = os.environ.get(request_env, "")
        if not request_id:
            print(
                f"AQG policy maintenance requires a scoped request in {request_env}.",
                file=sys.stderr,
            )
            return CONFIGURATION_ERROR
        try:
            request = load_maintenance_request(root, request_id)
        except ConfigurationError as exc:
            print(f"AQG policy maintenance request is invalid: {exc}", file=sys.stderr)
            return CONFIGURATION_ERROR
        authorized = {
            (str(item["path"]), str(item["operation"])) for item in request["authorized_changes"]
        }
    tool_name = str(payload.get("tool_name") or payload.get("tool") or payload.get("name") or "")
    tool_input = payload.get("tool_input") or payload.get("input") or payload.get("arguments") or {}
    protected = protected_patterns(policy)
    expected_output_patterns = [
        pattern
        for pattern in human_review_patterns(policy)
        if any(token in pattern.lower() for token in ("golden", "snapshot", "__snapshots__"))
    ]
    golden_env = str(policy.get("policy", {}).get("golden_update_env", "AQG_ALLOW_GOLDEN_UPDATE"))
    allow_golden = os.environ.get(golden_env) == "1"
    violations: list[str] = []
    for change in _direct_write_changes(root, tool_name, tool_input):
        normalized = _normalize(root, change["path"])
        if matches_any(normalized, protected):
            identity = (normalized, change["operation"])
            if not maintenance_enabled or identity not in authorized:
                violations.append(
                    f"{change['operation']} to protected policy path {normalized} "
                    "is outside the scoped maintenance request"
                )
        elif matches_any(normalized, expected_output_patterns) and not allow_golden:
            violations.append(f"write to expected-output artifact {normalized}")
    command = str(tool_input.get("command", "")) if isinstance(tool_input, dict) else ""
    if command:
        for expression in policy.get("policy", {}).get("blocked_command_regex", []):
            if re.search(str(expression), command, re.IGNORECASE | re.MULTILINE):
                violations.append(f"command matches blocked policy {expression}")
        for path in _command_policy_writes(command, protected):
            violations.append(
                f"command may modify protected policy path {path}; "
                "scoped maintenance requires a structured file-edit tool"
            )
        if not allow_golden:
            for path in _command_policy_writes(command, expected_output_patterns):
                violations.append(f"command may modify expected-output artifact {path}")
    if violations:
        print(
            "Blocked by Agent Quality Gauntlet. An explicit policy-maintenance task and human approval are required:\n- "
            + "\n- ".join(sorted(set(violations))),
            file=sys.stderr,
        )
        return CONFIGURATION_ERROR
    return PASS


def hook_stop(root: Path) -> int:
    policy = load_policy(root)
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    config = policy.get("hooks", {})
    if not config.get("enforce_on_stop", False) or payload.get("stop_hook_active"):
        return PASS
    profile = str(config.get("stop_profile", "fast"))
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        code, _ = run_profile(root, policy, profile, keep_going=False, quiet=True)
    if code != PASS:
        output = captured.getvalue().strip()
        print(
            f"AQG {profile} is not green. Resolve the deterministic report before ending the task."
            + (f"\n{output[-5000:]}" if output else ""),
            file=sys.stderr,
        )
        return CONFIGURATION_ERROR
    return PASS
