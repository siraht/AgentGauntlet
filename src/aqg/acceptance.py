"""Strict Gherkin validation and specification-data mutation testing."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .checks import lint_features
from .constants import CONFIGURATION_ERROR, INFRASTRUCTURE_ERROR, PASS, QUALITY_FAILURE
from .errors import ConfigurationError
from .project import load_project
from .util import utc_now, write_json


def _seed(path: str, value: str) -> int:
    return int(hashlib.sha256(f"{path}\0{value}".encode()).hexdigest()[:16], 16)


def mutate_value(path: str, value: str) -> str:
    trimmed = value.strip()
    lower = trimmed.lower()
    if "," in trimmed:
        parts = [part.strip() for part in trimmed.split(",")]
        index = _seed(path, value) % len(parts)
        parts[index] = mutate_value(f"{path}[{index}]", parts[index])
        return ", ".join(parts)
    if lower == "true":
        return "false"
    if lower == "false":
        return "true"
    if lower in {"null", "nil", "none"}:
        return "value"
    if re.fullmatch(r"[-+]?\d+", trimmed):
        integer_number = int(trimmed)
        integer_delta = (_seed(path, value) % 9) + 1
        return str(integer_number + integer_delta)
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)", trimmed):
        decimal_number = float(trimmed)
        decimal_delta = ((_seed(path, value) % 19) + 1) / 10
        return f"{decimal_number + decimal_delta:g}"
    try:
        date = dt.date.fromisoformat(trimmed)
        return (date + dt.timedelta(days=1 + _seed(path, value) % 7)).isoformat()
    except ValueError:
        pass
    if not value:
        return "x"
    index = _seed(path, value) % len(value)
    replacement = "x" if value[index].lower() != "x" else "y"
    return value[:index] + replacement + value[index + 1 :]


def semantic_rules(config: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
    raw_rules = config.get("semantic_mutations", [])
    if not isinstance(raw_rules, list):
        raise ConfigurationError("acceptance_mutation.semantic_mutations must be an array")
    rules: dict[tuple[str, str, str], dict[str, Any]] = {}
    ids: set[str] = set()
    for raw in raw_rules:
        if not isinstance(raw, dict):
            raise ConfigurationError("semantic mutation rule must be an object")
        rule_id = str(raw.get("id") or "").strip()
        feature = str(raw.get("feature") or "").strip()
        scenario = str(raw.get("scenario") or "").strip()
        key = str(raw.get("key") or "").strip()
        mapping = raw.get("mapping")
        if (
            not all((rule_id, feature, scenario, key))
            or not isinstance(mapping, dict)
            or not mapping
        ):
            raise ConfigurationError(
                "semantic mutation rule needs id, feature, scenario, key, and non-empty mapping"
            )
        if rule_id in ids:
            raise ConfigurationError(f"duplicate semantic mutation rule id {rule_id!r}")
        normalized_mapping = {str(original): str(mutated) for original, mutated in mapping.items()}
        if any(original == mutated for original, mutated in normalized_mapping.items()):
            raise ConfigurationError(f"semantic mutation rule {rule_id!r} contains a no-op")
        identity = (feature, scenario, key)
        if identity in rules:
            raise ConfigurationError(f"duplicate semantic mutation target {identity!r}")
        rules[identity] = {
            "id": rule_id,
            "mapping": normalized_mapping,
        }
        ids.add(rule_id)
    return rules


def discover_mutations(
    feature: dict[str, Any],
    feature_path: str,
    *,
    rules: dict[tuple[str, str, str], dict[str, Any]] | None = None,
    semantic_required: bool = False,
) -> list[dict[str, Any]]:
    mutations: list[dict[str, Any]] = []
    configured = rules or {}
    for scenario_index, scenario in enumerate(feature.get("scenarios", [])):
        for example_index, example in enumerate(scenario.get("examples", [])):
            for key in sorted(example):
                path = f"$.scenarios[{scenario_index}].examples[{example_index}].{key}"
                original = str(example[key])
                rule = configured.get((feature_path, str(scenario.get("name")), key))
                if rule is not None:
                    mapping = rule["mapping"]
                    if original not in mapping:
                        raise ConfigurationError(
                            f"semantic rule {rule['id']!r} has no mapping for {original!r}"
                        )
                    mutated = str(mapping[original])
                    strategy = "semantic"
                    rule_id: str | None = str(rule["id"])
                else:
                    if semantic_required:
                        raise ConfigurationError(
                            f"no semantic mutation rule for {feature_path} / "
                            f"{scenario.get('name')} / {key}"
                        )
                    mutated = mutate_value(path, original)
                    strategy = "generic"
                    rule_id = None
                mutations.append(
                    {
                        "id": f"m{len(mutations) + 1}",
                        "feature_path": feature_path,
                        "scenario_index": scenario_index,
                        "scenario_name": scenario.get("name"),
                        "example_index": example_index,
                        "key": key,
                        "path": path,
                        "original": original,
                        "mutated": mutated,
                        "strategy": strategy,
                        "domain_valid": strategy == "semantic",
                        "rule_id": rule_id,
                    }
                )
    return mutations


def _trace(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"reached_application_boundary": False, "stage": "pre_boundary"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "reached_application_boundary": False,
            "stage": "invalid_boundary_trace",
        }
    if not isinstance(payload, dict) or payload.get("reached_application_boundary") is not True:
        return {
            "reached_application_boundary": False,
            "stage": "invalid_boundary_trace",
        }
    return payload


def _execute(
    command: list[str],
    root: Path,
    feature_json: Path,
    timeout: int,
    trace_path: Path,
) -> dict[str, Any]:
    argv = [part.replace("{feature_json}", str(feature_json)) for part in command]
    env = os.environ.copy()
    env["AQG_FEATURE_JSON"] = str(feature_json)
    env["AQG_ACCEPTANCE_TRACE"] = str(trace_path)
    trace_path.unlink(missing_ok=True)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv, cwd=root, env=env, text=True, capture_output=True, timeout=timeout, check=False
        )
        outcome = "test_success" if completed.returncode == 0 else "test_failure"
        result = {
            "outcome": outcome,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
        result["boundary_trace"] = _trace(trace_path)
        return result
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        result = {
            "outcome": "infrastructure_error",
            "exit_code": INFRASTRUCTURE_ERROR,
            "stdout": "",
            "stderr": str(exc),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
        result["boundary_trace"] = _trace(trace_path)
        return result


def _configuration_report(
    root: Path,
    lint: dict[str, Any],
    message: str,
) -> tuple[int, dict[str, Any]]:
    report = {
        "schema_version": 2,
        "generated_at": utc_now(),
        "status": CONFIGURATION_ERROR,
        "failures": [message],
        "lint": lint,
        "results": [],
    }
    write_json(root / ".aqg" / "work" / "acceptance-mutation" / "report.json", report)
    return CONFIGURATION_ERROR, report


def run_acceptance_mutation(root: Path) -> tuple[int, dict[str, Any]]:
    lint = lint_features(root)
    if lint["errors"]:
        return _configuration_report(root, lint, "strict Gherkin lint failed")
    project = load_project(root)
    config = project.get("acceptance_mutation", {})
    command = config.get("command") if isinstance(config, dict) else None
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(value, str) for value in command)
    ):
        raise ConfigurationError(
            "acceptance mutation is applicable but quality/project.json lacks acceptance_mutation.command; "
            "the command must run the same generated acceptance entry points against AQG_FEATURE_JSON"
        )
    timeout = int(config.get("timeout_seconds", 60))
    semantic_required = bool(config.get("semantic_required", False))
    require_boundary = bool(config.get("require_boundary_trace", semantic_required))
    try:
        rules = semantic_rules(config)
        planned = [
            (
                parsed,
                discover_mutations(
                    parsed["feature"],
                    parsed["path"],
                    rules=rules,
                    semantic_required=semantic_required,
                ),
            )
            for parsed in lint["features"]
        ]
        used = {
            mutation["rule_id"]
            for _, mutations in planned
            for mutation in mutations
            if mutation["rule_id"]
        }
        unused = sorted(str(rule["id"]) for rule in rules.values() if rule["id"] not in used)
        if unused:
            raise ConfigurationError(
                "semantic mutation rule(s) did not match executable examples: " + ", ".join(unused)
            )
    except ConfigurationError as exc:
        return _configuration_report(root, lint, str(exc))
    work = root / ".aqg" / "work" / "acceptance-mutation"
    results: list[dict[str, Any]] = []
    final = PASS
    for parsed, mutations in planned:
        feature_path = parsed["path"]
        feature = parsed["feature"]
        base_dir = work / re.sub(r"[^A-Za-z0-9._-]+", "-", feature_path)
        base_json = base_dir / "base.json"
        write_json(base_json, feature)
        baseline = _execute(command, root, base_json, timeout, base_dir / "baseline.trace.json")
        if baseline["outcome"] != "test_success":
            final = (
                INFRASTRUCTURE_ERROR
                if baseline["outcome"] == "infrastructure_error"
                else CONFIGURATION_ERROR
            )
            results.append(
                {"feature": feature_path, "status": "baseline_failed", "baseline": baseline}
            )
            continue
        if require_boundary and not baseline["boundary_trace"]["reached_application_boundary"]:
            final = CONFIGURATION_ERROR
            results.append(
                {
                    "feature": feature_path,
                    "status": "baseline_disconnected",
                    "baseline": baseline,
                }
            )
            continue
        for mutation in mutations:
            mutated = copy.deepcopy(feature)
            mutated["scenarios"][mutation["scenario_index"]]["examples"][mutation["example_index"]][
                mutation["key"]
            ] = mutation["mutated"]
            mutation_json = base_dir / mutation["id"] / "feature.json"
            write_json(mutation_json, mutated)
            execution = _execute(
                command,
                root,
                mutation_json,
                timeout,
                mutation_json.parent / "boundary.trace.json",
            )
            reached = bool(execution["boundary_trace"].get("reached_application_boundary"))
            if execution["outcome"] == "test_failure":
                status = "killed"
                code = PASS
                kill_stage = "after_application_boundary" if reached else "pre_boundary"
            elif execution["outcome"] == "test_success":
                status = "survived"
                code = QUALITY_FAILURE
                kill_stage = "survived_after_boundary" if reached else "disconnected"
            else:
                status = "error"
                code = INFRASTRUCTURE_ERROR
                kill_stage = "infrastructure"
            final = max(final, code)
            results.append(
                {
                    "feature": feature_path,
                    "mutation": mutation,
                    "status": status,
                    "reached_application_boundary": reached,
                    "kill_stage": kill_stage,
                    "execution": execution,
                }
            )
    summary = {
        "total": sum("mutation" in result for result in results),
        "killed": sum(result.get("status") == "killed" for result in results),
        "survived": sum(result.get("status") == "survived" for result in results),
        "errors": sum(
            result.get("status") in {"error", "baseline_failed", "baseline_disconnected"}
            for result in results
        ),
        "semantic_total": sum(
            result.get("mutation", {}).get("strategy") == "semantic" for result in results
        ),
        "semantic_killed": sum(
            result.get("status") == "killed"
            and result.get("mutation", {}).get("strategy") == "semantic"
            for result in results
        ),
        "pre_boundary_kills": sum(result.get("kill_stage") == "pre_boundary" for result in results),
    }
    report = {
        "schema_version": 2,
        "generated_at": utc_now(),
        "status": final,
        "summary": summary,
        "lint": lint,
        "results": results,
    }
    write_json(work / "report.json", report)
    return final, report
