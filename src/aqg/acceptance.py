"""Strict Gherkin validation and specification-data mutation testing."""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
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


def discover_mutations(feature: dict[str, Any], feature_path: str) -> list[dict[str, Any]]:
    mutations: list[dict[str, Any]] = []
    for scenario_index, scenario in enumerate(feature.get("scenarios", [])):
        for example_index, example in enumerate(scenario.get("examples", [])):
            for key in sorted(example):
                path = f"$.scenarios[{scenario_index}].examples[{example_index}].{key}"
                original = str(example[key])
                mutated = mutate_value(path, original)
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
                    }
                )
    return mutations


def _execute(command: list[str], root: Path, feature_json: Path, timeout: int) -> dict[str, Any]:
    argv = [part.replace("{feature_json}", str(feature_json)) for part in command]
    env = os.environ.copy()
    env["AQG_FEATURE_JSON"] = str(feature_json)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv, cwd=root, env=env, text=True, capture_output=True, timeout=timeout, check=False
        )
        outcome = "test_success" if completed.returncode == 0 else "test_failure"
        return {
            "outcome": outcome,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {
            "outcome": "infrastructure_error",
            "exit_code": INFRASTRUCTURE_ERROR,
            "stdout": "",
            "stderr": str(exc),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }


def run_acceptance_mutation(root: Path) -> tuple[int, dict[str, Any]]:
    lint = lint_features(root)
    if lint["errors"]:
        report = {"schema_version": 1, "status": CONFIGURATION_ERROR, "lint": lint, "results": []}
        write_json(root / ".aqg" / "work" / "acceptance-mutation" / "report.json", report)
        return CONFIGURATION_ERROR, report
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
    work = root / ".aqg" / "work" / "acceptance-mutation"
    results: list[dict[str, Any]] = []
    final = PASS
    for parsed in lint["features"]:
        feature_path = parsed["path"]
        feature = parsed["feature"]
        base_dir = work / re.sub(r"[^A-Za-z0-9._-]+", "-", feature_path)
        base_json = base_dir / "base.json"
        write_json(base_json, feature)
        baseline = _execute(command, root, base_json, timeout)
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
        for mutation in discover_mutations(feature, feature_path):
            mutated = copy.deepcopy(feature)
            mutated["scenarios"][mutation["scenario_index"]]["examples"][mutation["example_index"]][
                mutation["key"]
            ] = mutation["mutated"]
            mutation_json = base_dir / mutation["id"] / "feature.json"
            write_json(mutation_json, mutated)
            execution = _execute(command, root, mutation_json, timeout)
            if execution["outcome"] == "test_failure":
                status = "killed"
                code = PASS
            elif execution["outcome"] == "test_success":
                status = "survived"
                code = QUALITY_FAILURE
            else:
                status = "error"
                code = INFRASTRUCTURE_ERROR
            final = max(final, code)
            results.append(
                {
                    "feature": feature_path,
                    "mutation": mutation,
                    "status": status,
                    "execution": execution,
                }
            )
    summary = {
        "total": sum("mutation" in result for result in results),
        "killed": sum(result.get("status") == "killed" for result in results),
        "survived": sum(result.get("status") == "survived" for result in results),
        "errors": sum(result.get("status") in {"error", "baseline_failed"} for result in results),
    }
    report = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "status": final,
        "summary": summary,
        "lint": lint,
        "results": results,
    }
    write_json(work / "report.json", report)
    return final, report
