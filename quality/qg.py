#!/usr/bin/env python3
"""Language-agnostic quality-gate orchestrator and local agent guard.

Python 3.11+ is required for stdlib tomllib. The script deliberately keeps its
own responsibilities small: policy loading, safe cleanup, deterministic command
execution, evidence capture, protected-path guarding, and review-plane diffs.
Stack-specific quality semantics belong in adapters.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fnmatch
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
from typing import Any, Iterable

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - explicit, actionable failure
    print("qg requires Python 3.11+ (stdlib tomllib is unavailable)", file=sys.stderr)
    raise SystemExit(2)

PASS = 0
QUALITY_FAILURE = 1
CONFIGURATION_ERROR = 2
INFRASTRUCTURE_ERROR = 3
PLACEHOLDER = "__CONFIGURE__"
RISK_ORDER = ["experiment", "standard", "high_assurance", "critical"]


class PolicyError(RuntimeError):
    pass


def find_repo_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "quality" / "policy.toml").is_file():
            return candidate
    raise PolicyError("could not find quality/policy.toml from the current directory")


def load_policy(root: Path) -> dict[str, Any]:
    path = root / "quality" / "policy.toml"
    try:
        with path.open("rb") as handle:
            policy = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise PolicyError(f"missing policy: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise PolicyError(f"invalid TOML in {path}: {exc}") from exc
    if policy.get("version") != 1:
        raise PolicyError("quality policy version must be 1")
    return policy


def relpath(root: Path, value: str | Path) -> str:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix().lstrip("./")


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    for pattern in patterns:
        p = str(pattern).replace("\\", "/").lstrip("./")
        if fnmatch.fnmatchcase(normalized, p):
            return True
        # pathlib-like "**/" should also match the repository root.
        if p.startswith("**/") and fnmatch.fnmatchcase(normalized, p[3:]):
            return True
        # A directory pattern should cover descendants.
        if p.endswith("/**") and normalized == p[:-3].rstrip("/"):
            return True
    return False


def safe_remove(root: Path, configured_path: str) -> None:
    target = (root / configured_path).resolve()
    root_resolved = root.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise PolicyError(f"refusing to clean path outside repository: {configured_path}") from exc
    if target == root_resolved:
        raise PolicyError("refusing to clean repository root")
    if target.is_symlink() or target.is_file():
        target.unlink(missing_ok=True)
    elif target.is_dir():
        shutil.rmtree(target)


def validate_policy(policy: dict[str, Any], require_initialized: bool = True) -> list[str]:
    errors: list[str] = []
    if require_initialized and not policy.get("initialized", False):
        errors.append("policy initialized=false; bootstrap has not completed")

    profiles = policy.get("profiles")
    gates = policy.get("gates")
    if not isinstance(profiles, dict) or not profiles:
        errors.append("no execution profiles are configured")
        profiles = {}
    if not isinstance(gates, dict) or not gates:
        errors.append("no gates are configured")
        gates = {}

    referenced: set[str] = set()
    for profile_name, profile in profiles.items():
        gate_names = profile.get("gates") if isinstance(profile, dict) else None
        if not isinstance(gate_names, list) or not gate_names:
            errors.append(f"profile {profile_name!r} has no gates")
            continue
        for gate_name in gate_names:
            if not isinstance(gate_name, str):
                errors.append(f"profile {profile_name!r} contains a non-string gate")
                continue
            referenced.add(gate_name)
            if gate_name not in gates:
                errors.append(f"profile {profile_name!r} references missing gate {gate_name!r}")

    for gate_name in sorted(referenced):
        gate = gates.get(gate_name, {})
        command = gate.get("command") if isinstance(gate, dict) else None
        if not isinstance(command, str) or not command.strip() or PLACEHOLDER in command:
            errors.append(f"gate {gate_name!r} has an unconfigured command")
        timeout = gate.get("timeout_seconds", 0) if isinstance(gate, dict) else 0
        if not isinstance(timeout, int) or timeout <= 0:
            errors.append(f"gate {gate_name!r} needs a positive timeout_seconds")
        clean_paths = gate.get("clean_paths", []) if isinstance(gate, dict) else []
        if not isinstance(clean_paths, list) or not all(isinstance(v, str) for v in clean_paths):
            errors.append(f"gate {gate_name!r} clean_paths must be a string array")

    policy_cfg = policy.get("policy", {})
    for key in ("protected_paths", "human_review_paths", "blocked_command_regex"):
        values = policy_cfg.get(key, []) if isinstance(policy_cfg, dict) else []
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            errors.append(f"policy.{key} must be a string array")
    for expression in policy_cfg.get("blocked_command_regex", []) if isinstance(policy_cfg, dict) else []:
        try:
            re.compile(expression, re.IGNORECASE)
        except re.error as exc:
            errors.append(f"invalid blocked command regex {expression!r}: {exc}")

    risk_profiles = policy.get("risk_profiles", {})
    if not isinstance(risk_profiles, dict):
        errors.append("risk_profiles must be a table")
        risk_profiles = {}
    for profile_name in RISK_ORDER:
        config = risk_profiles.get(profile_name)
        if not isinstance(config, dict):
            errors.append(f"missing risk profile {profile_name!r}")
            continue
        required = config.get("required_execution_profiles")
        if not isinstance(required, list) or not required:
            errors.append(f"risk profile {profile_name!r} has no required execution profiles")
            continue
        for execution_profile in required:
            if execution_profile not in profiles:
                errors.append(
                    f"risk profile {profile_name!r} references missing execution profile {execution_profile!r}"
                )

    rules = policy.get("risk_rules", {})
    minimum_by_factor = rules.get("minimum_profile_by_factor", {}) if isinstance(rules, dict) else {}
    if not isinstance(minimum_by_factor, dict):
        errors.append("risk_rules.minimum_profile_by_factor must be a table")
    else:
        for factor, minimum in minimum_by_factor.items():
            if minimum not in RISK_ORDER:
                errors.append(f"risk factor {factor!r} has invalid minimum profile {minimum!r}")
    return errors


def unsafe_override_errors(policy: dict[str, Any]) -> list[str]:
    policy_cfg = policy.get("policy", {})
    errors: list[str] = []
    for key, fallback in (
        ("policy_maintenance_env", "AQG_POLICY_MAINTENANCE"),
        ("golden_update_env", "AQG_ALLOW_GOLDEN_UPDATE"),
    ):
        variable = str(policy_cfg.get(key, fallback))
        if os.environ.get(variable) == "1":
            errors.append(f"unsafe override {variable}=1 is enabled")
    return errors


def load_risk_card(root: Path, card_path: str) -> dict[str, Any]:
    path = Path(card_path)
    if not path.is_absolute():
        path = root / path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PolicyError(f"missing change-risk card: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PolicyError(f"invalid JSON in change-risk card {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PolicyError("change-risk card must be a JSON object")
    return payload


def risk_card_errors(card: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = {
        "schema_version": str,
        "summary": str,
        "risk_profile": str,
        "production_scope": bool,
        "reversible": bool,
        "blast_radius": str,
        "behavior_changes": list,
        "behavior_preserved": list,
        "risk_factors": dict,
        "failure_detection": str,
        "rollback": str,
        "human_review": list,
    }
    for field, expected_type in required.items():
        value = card.get(field)
        if not isinstance(value, expected_type):
            errors.append(f"risk card field {field!r} must be {expected_type.__name__}")

    if card.get("schema_version") != "1":
        errors.append("risk card schema_version must be '1'")
    selected = card.get("risk_profile")
    if selected not in RISK_ORDER:
        errors.append(f"risk_profile must be one of: {', '.join(RISK_ORDER)}")
    if card.get("blast_radius") not in {"local", "single_service", "multi_service", "organization", "public"}:
        errors.append("blast_radius must be local, single_service, multi_service, organization, or public")

    for field in ("summary", "failure_detection", "rollback"):
        value = card.get(field)
        if isinstance(value, str) and not value.strip():
            errors.append(f"risk card field {field!r} must not be blank")
    changes = card.get("behavior_changes")
    if isinstance(changes, list) and not changes:
        errors.append("behavior_changes must contain at least one observable change")
    for field in ("behavior_changes", "behavior_preserved", "human_review"):
        value = card.get(field)
        if isinstance(value, list) and not all(isinstance(item, str) and item.strip() for item in value):
            errors.append(f"risk card field {field!r} must contain non-empty strings")

    factors = card.get("risk_factors")
    configured_factors = policy.get("risk_rules", {}).get("minimum_profile_by_factor", {})
    if isinstance(factors, dict):
        for factor, value in factors.items():
            if not isinstance(value, bool):
                errors.append(f"risk factor {factor!r} must be boolean")
        missing = sorted(set(configured_factors) - set(factors))
        for factor in missing:
            errors.append(f"risk card is missing configured risk factor {factor!r}")
    return errors


def risk_rank(profile: str) -> int:
    try:
        return RISK_ORDER.index(profile)
    except ValueError:
        return -1


def minimum_risk_profile(card: dict[str, Any], policy: dict[str, Any]) -> tuple[str, list[str]]:
    minimum = "experiment"
    reasons: list[str] = []

    def raise_to(profile: str, reason: str) -> None:
        nonlocal minimum
        if risk_rank(profile) > risk_rank(minimum):
            minimum = profile
        reasons.append(reason)

    if card.get("production_scope") is True:
        raise_to("standard", "production_scope=true")
    if card.get("reversible") is False:
        raise_to("high_assurance", "reversible=false")
    if card.get("blast_radius") in {"multi_service", "organization", "public"}:
        raise_to("high_assurance", f"blast_radius={card.get('blast_radius')}")

    factors = card.get("risk_factors", {})
    rules = policy.get("risk_rules", {}).get("minimum_profile_by_factor", {})
    if isinstance(factors, dict) and isinstance(rules, dict):
        for factor, minimum_profile in rules.items():
            if factors.get(factor) is True:
                raise_to(str(minimum_profile), f"risk_factors.{factor}=true")
    return minimum, reasons


def risk_card_summary(root: Path, policy: dict[str, Any], card_path: str) -> tuple[int, dict[str, Any]]:
    card = load_risk_card(root, card_path)
    errors = risk_card_errors(card, policy)
    selected = str(card.get("risk_profile", ""))
    minimum, reasons = minimum_risk_profile(card, policy)
    if selected in RISK_ORDER and risk_rank(selected) < risk_rank(minimum):
        errors.append(
            f"selected risk profile {selected!r} is below deterministic minimum {minimum!r}"
        )
    effective = selected
    if selected not in RISK_ORDER or risk_rank(selected) < risk_rank(minimum):
        effective = minimum

    profiles = []
    required_controls: dict[str, bool] = {}
    if effective in policy.get("risk_profiles", {}):
        effective_policy = policy["risk_profiles"][effective]
        profiles = list(effective_policy.get("required_execution_profiles", []))
        required_controls = {
            key: bool(value)
            for key, value in effective_policy.items()
            if key.startswith("requires_")
        }
    payload = {
        "status": "pass" if not errors else "configuration_error",
        "card": relpath(root, card_path),
        "selected_risk_profile": selected,
        "minimum_risk_profile": minimum,
        "effective_risk_profile": effective,
        "minimum_reasons": reasons,
        "required_execution_profiles": profiles,
        "required_controls": required_controls,
        "errors": errors,
    }
    return (PASS if not errors else CONFIGURATION_ERROR), payload


def run_doctor(root: Path, policy: dict[str, Any], as_json: bool) -> int:
    errors = validate_policy(policy, require_initialized=True) + unsafe_override_errors(policy)
    payload = {
        "status": "pass" if not errors else "configuration_error",
        "repository": str(root),
        "python": sys.version.split()[0],
        "errors": errors,
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if errors:
            print("Quality gauntlet is not ready:", file=sys.stderr)
            for error in errors:
                print(f"  - {error}", file=sys.stderr)
        else:
            print("Quality gauntlet policy is valid.")
    return PASS if not errors else CONFIGURATION_ERROR


def classify_exit(exit_code: int, quality_codes: set[int]) -> str:
    if exit_code == 0:
        return "pass"
    if exit_code in quality_codes:
        return "fail"
    if exit_code == 2:
        return "configuration_error"
    if exit_code == 3:
        return "infrastructure_error"
    return "infrastructure_error"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run_gate(
    root: Path,
    run_dir: Path,
    gate_name: str,
    gate: dict[str, Any],
    profile_name: str,
    remaining_seconds: float | None,
) -> dict[str, Any]:
    command = str(gate["command"])
    timeout = int(gate.get("timeout_seconds", 600))
    if remaining_seconds is not None:
        timeout = max(1, min(timeout, int(remaining_seconds)))

    for clean_path in gate.get("clean_paths", []):
        safe_remove(root, clean_path)

    gate_dir = run_dir / gate_name
    gate_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = gate_dir / "stdout.log"
    stderr_path = gate_dir / "stderr.log"

    env = os.environ.copy()
    env.update({
        "AQG_PROFILE": profile_name,
        "AQG_GATE": gate_name,
        "AQG_RUN_DIR": str(run_dir),
        "AQG_GATE_DIR": str(gate_dir),
        "AQG_REPO_ROOT": str(root),
    })

    started_at = now_iso()
    start = time.monotonic()
    timed_out = False
    exit_code = 3
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=env,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        exit_code = int(completed.returncode)
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr + f"\nTimed out after {timeout} seconds.\n", encoding="utf-8")
    except OSError as exc:
        stderr_path.write_text(f"Failed to execute gate: {exc}\n", encoding="utf-8")

    duration_ms = int((time.monotonic() - start) * 1000)
    quality_codes = {int(v) for v in gate.get("quality_failure_exit_codes", [1])}
    status = "infrastructure_error" if timed_out else classify_exit(exit_code, quality_codes)
    return {
        "schema_version": "1",
        "gate": gate_name,
        "status": status,
        "started_at": started_at,
        "duration_ms": duration_ms,
        "command": command,
        "exit_code": exit_code,
        "timeout_seconds": timeout,
        "timed_out": timed_out,
        "findings": [],
        "stdout_log": relpath(root, stdout_path),
        "stderr_log": relpath(root, stderr_path),
        "artifacts": [relpath(root, gate_dir)],
    }


def run_profile(root: Path, policy: dict[str, Any], profile_name: str, keep_going: bool) -> int:
    errors = validate_policy(policy, require_initialized=True) + unsafe_override_errors(policy)
    if errors:
        for error in errors:
            print(f"configuration error: {error}", file=sys.stderr)
        return CONFIGURATION_ERROR

    profiles = policy["profiles"]
    if profile_name not in profiles:
        print(f"unknown execution profile: {profile_name}", file=sys.stderr)
        return CONFIGURATION_ERROR

    profile = profiles[profile_name]
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = root / "build" / "quality" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    max_total = int(profile.get("max_total_seconds", 0)) or None
    started = time.monotonic()
    reports: list[dict[str, Any]] = []
    overall = "pass"

    for gate_name in profile["gates"]:
        elapsed = time.monotonic() - started
        remaining = None if max_total is None else max_total - elapsed
        if remaining is not None and remaining <= 0:
            report = {
                "schema_version": "1",
                "gate": gate_name,
                "status": "infrastructure_error",
                "started_at": now_iso(),
                "duration_ms": 0,
                "command": policy["gates"][gate_name]["command"],
                "exit_code": 3,
                "findings": [{"rule": "profile_timeout", "message": "Profile time budget exhausted"}],
                "artifacts": [],
            }
        else:
            print(f"[{profile_name}] {gate_name} ...", flush=True)
            report = run_gate(root, run_dir, gate_name, policy["gates"][gate_name], profile_name, remaining)
        reports.append(report)
        print(f"[{profile_name}] {gate_name}: {report['status']} ({report['duration_ms']} ms)", flush=True)

        if report["status"] != "pass":
            if report["status"] == "fail" and overall == "pass":
                overall = "fail"
            elif report["status"] in {"configuration_error", "infrastructure_error"}:
                overall = report["status"]
            if not keep_going:
                break

    summary = {
        "schema_version": "1",
        "run_id": run_id,
        "profile": profile_name,
        "status": overall,
        "started_at": now_iso(),
        "duration_ms": int((time.monotonic() - started) * 1000),
        "reports": reports,
    }
    summary_path = run_dir / "report.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Evidence: {relpath(root, summary_path)}")

    if overall == "pass":
        return PASS
    if overall == "fail":
        return QUALITY_FAILURE
    if overall == "configuration_error":
        return CONFIGURATION_ERROR
    return INFRASTRUCTURE_ERROR


def collect_strings(value: Any, key_hint: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.extend(collect_strings(child, str(key)))
    elif isinstance(value, list):
        for child in value:
            found.extend(collect_strings(child, key_hint))
    elif isinstance(value, str):
        found.append((key_hint, value))
    return found


def patch_paths(command: str) -> list[str]:
    patterns = [
        r"^\*\*\* (?:Add|Update|Delete) File:\s+(.+?)\s*$",
        r"^(?:\+\+\+|---)\s+(?:[ab]/)?(.+?)\s*$",
    ]
    paths: list[str] = []
    for line in command.splitlines():
        for pattern in patterns:
            match = re.match(pattern, line)
            if match:
                path = match.group(1).strip()
                if path != "/dev/null":
                    paths.append(path)
    return paths


def direct_write_paths(tool_name: str, tool_input: Any) -> list[str]:
    paths: list[str] = []
    canonical = tool_name.lower()
    mutation_verbs = ("write", "edit", "update", "create", "delete", "remove", "move", "rename", "patch", "put", "upload")
    if canonical in {"edit", "write", "multiedit", "notebookedit"} or any(
        verb in canonical for verb in mutation_verbs
    ):
        for key, value in collect_strings(tool_input):
            if key.lower() in {"file_path", "filepath", "path", "filename", "file"}:
                paths.append(value)
    if canonical == "apply_patch" and isinstance(tool_input, dict):
        command = str(tool_input.get("command", ""))
        paths.extend(patch_paths(command))
    return paths


def command_attempts_policy_write(command: str, protected_patterns: list[str]) -> list[str]:
    write_tokens = re.compile(
        r"(^|[;&|]\s*|\s)(rm|mv|cp|install|truncate|tee|sed\s+-i|perl\s+-pi|"
        r"python(?:3)?\s+-c|ruby\s+-e|node\s+-e|chmod|chown|git\s+(?:checkout|restore|reset))\b|>",
        re.IGNORECASE,
    )
    if not write_tokens.search(command):
        return []
    touched: list[str] = []
    for pattern in protected_patterns:
        stem = pattern.replace("**", "").rstrip("/").rstrip("*")
        if stem and stem in command:
            touched.append(pattern)
    touched.extend(path for path in patch_paths(command) if matches_any(path, protected_patterns))
    return sorted(set(touched))


def hook_pretool(root: Path, policy: dict[str, Any]) -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"quality guard received invalid JSON: {exc}", file=sys.stderr)
        return CONFIGURATION_ERROR

    if os.environ.get(policy.get("policy", {}).get("policy_maintenance_env", "AQG_POLICY_MAINTENANCE")) == "1":
        return PASS

    tool_name = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input", {})
    policy_cfg = policy.get("policy", {})
    protected = [str(v) for v in policy_cfg.get("protected_paths", [])]
    blocked_regex = [str(v) for v in policy_cfg.get("blocked_command_regex", [])]

    violations: list[str] = []
    for path in direct_write_paths(tool_name, tool_input):
        normalized = relpath(root, path)
        if matches_any(normalized, protected):
            violations.append(f"write to protected policy path {normalized}")

    command = ""
    if isinstance(tool_input, dict):
        command = str(tool_input.get("command", ""))
    if command:
        for expression in blocked_regex:
            if re.search(expression, command, re.IGNORECASE | re.MULTILINE):
                violations.append(f"command matches blocked policy: {expression}")
        for path in command_attempts_policy_write(command, protected):
            violations.append(f"command may modify protected policy path {path}")

    if violations:
        print(
            "Blocked by the Agent Quality Gauntlet. "
            "This requires an explicit policy-maintenance task and human approval:\n- "
            + "\n- ".join(sorted(set(violations))),
            file=sys.stderr,
        )
        return CONFIGURATION_ERROR  # exit 2 blocks PreToolUse in Codex and Claude Code
    return PASS


def hook_stop(root: Path, policy: dict[str, Any]) -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    hooks = policy.get("hooks", {})
    if not hooks.get("enforce_on_stop", False):
        return PASS
    if payload.get("stop_hook_active"):
        return PASS
    profile = str(hooks.get("stop_profile", "fast"))
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        result = run_profile(root, policy, profile, keep_going=False)
    if result != PASS:
        diagnostics = captured.getvalue().strip()
        print(
            f"The {profile} quality profile is not green. Resolve the report before ending the task."
            + (f"\n{diagnostics[-4000:]}" if diagnostics else ""),
            file=sys.stderr,
        )
        return CONFIGURATION_ERROR
    return PASS


def git_changed_files(root: Path, base: str) -> tuple[int, list[str], str]:
    commands = [
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        ["git", "diff", "--name-only", base],
    ]
    last_error = ""
    for command in commands:
        completed = subprocess.run(command, cwd=root, text=True, capture_output=True, check=False)
        if completed.returncode == 0:
            return PASS, [line.strip() for line in completed.stdout.splitlines() if line.strip()], ""
        last_error = completed.stderr.strip()
    return INFRASTRUCTURE_ERROR, [], last_error


def review_required(root: Path, policy: dict[str, Any], base: str, as_json: bool) -> int:
    code, changed, error = git_changed_files(root, base)
    if code != PASS:
        print(f"could not determine changed files: {error}", file=sys.stderr)
        return code
    patterns = policy.get("policy", {}).get("human_review_paths", [])
    matches = [path for path in changed if matches_any(path, patterns)]
    payload = {"base": base, "changed_files": changed, "human_review_required": matches}
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        if matches:
            print("Human review is required for:")
            for path in matches:
                print(f"  - {path}")
        else:
            print("No configured human-review-plane files changed.")
    return QUALITY_FAILURE if matches else PASS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qg", description="Agent Quality Gauntlet")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="validate the quality policy")
    doctor.add_argument("--json", action="store_true")

    check = sub.add_parser("check", help="run an execution profile")
    check.add_argument("profile")
    check.add_argument("--keep-going", action="store_true")

    risk = sub.add_parser("risk-card", help="validate a change-risk card and resolve required profiles")
    risk.add_argument("--card", default=os.environ.get("AQG_RISK_CARD", "quality/change-risk.json"))
    risk.add_argument("--json", action="store_true")

    check_risk = sub.add_parser("check-risk", help="run every profile required by a change-risk card")
    check_risk.add_argument("--card", default=os.environ.get("AQG_RISK_CARD", "quality/change-risk.json"))
    check_risk.add_argument("--keep-going", action="store_true")

    sub.add_parser("hook-pretool", help="PreToolUse guard for Codex/Claude Code")
    sub.add_parser("hook-stop", help="Stop hook that can enforce the fast profile")

    review = sub.add_parser("review-required", help="list changed human-review-plane files")
    review.add_argument("--base", default=os.environ.get("AQG_DIFF_BASE", "origin/main"))
    review.add_argument("--json", action="store_true")

    changed = sub.add_parser("changed-files", help="list changed files")
    changed.add_argument("--base", default=os.environ.get("AQG_DIFF_BASE", "origin/main"))
    changed.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        root = find_repo_root()
        policy = load_policy(root)
        if args.command == "doctor":
            return run_doctor(root, policy, args.json)
        if args.command == "check":
            return run_profile(root, policy, args.profile, args.keep_going)
        if args.command == "risk-card":
            result, payload = risk_card_summary(root, policy, args.card)
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            elif result == PASS:
                print(
                    f"Risk card valid: selected={payload['selected_risk_profile']}, "
                    f"minimum={payload['minimum_risk_profile']}, "
                    f"profiles={','.join(payload['required_execution_profiles'])}, "
                    "controls="
                    + ",".join(
                        key.removeprefix("requires_")
                        for key, required in payload["required_controls"].items()
                        if required
                    )
                )
            else:
                print("Change-risk card is invalid:", file=sys.stderr)
                for error in payload["errors"]:
                    print(f"  - {error}", file=sys.stderr)
            return result
        if args.command == "check-risk":
            result, payload = risk_card_summary(root, policy, args.card)
            if result != PASS:
                print("Change-risk card is invalid:", file=sys.stderr)
                for error in payload["errors"]:
                    print(f"  - {error}", file=sys.stderr)
                return result
            for profile in payload["required_execution_profiles"]:
                result = run_profile(root, policy, profile, args.keep_going)
                if result != PASS:
                    return result
            return PASS
        if args.command == "hook-pretool":
            return hook_pretool(root, policy)
        if args.command == "hook-stop":
            return hook_stop(root, policy)
        if args.command == "review-required":
            return review_required(root, policy, args.base, args.json)
        if args.command == "changed-files":
            code, files, error = git_changed_files(root, args.base)
            if code != PASS:
                print(error, file=sys.stderr)
                return code
            if args.json:
                print(json.dumps(files, indent=2))
            else:
                print("\n".join(files))
            return PASS
    except PolicyError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return CONFIGURATION_ERROR
    return CONFIGURATION_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
