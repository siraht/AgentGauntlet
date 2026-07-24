"""Deterministic command/session golden testing with explicit update separation."""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .constants import CONFIGURATION_ERROR, INFRASTRUCTURE_ERROR, PASS, QUALITY_FAILURE
from .errors import ConfigurationError
from .util import read_json, sha256_file, utc_now, write_json


def load_scenarios(root: Path) -> dict[str, Any]:
    path = root / "quality" / "golden" / "scenarios.json"
    payload = read_json(path)
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ConfigurationError("quality/golden/scenarios.json must be a schema_version 1 object")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ConfigurationError("golden scenarios must contain a non-empty scenarios array")
    return payload


def _normalize(value: str, rules: list[dict[str, Any]]) -> str:
    normalized = value.replace("\r\n", "\n")
    for rule in rules:
        pattern = rule.get("pattern")
        replacement = rule.get("replace")
        if not isinstance(pattern, str) or not isinstance(replacement, str):
            raise ConfigurationError(
                "golden normalize rules need string pattern and replace fields"
            )
        normalized = re.sub(pattern, replacement, normalized, flags=re.MULTILINE)
    return normalized


def _capture_file(root: Path, path_value: str, max_bytes: int) -> dict[str, Any]:
    path = (root / path_value).resolve()
    try:
        rel = path.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ConfigurationError(f"golden capture path escapes repository: {path_value}") from exc
    if not path.exists():
        return {"path": rel, "exists": False}
    if path.is_dir():
        entries = sorted(p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file())
        return {"path": rel, "exists": True, "type": "directory", "entries": entries}
    size = path.stat().st_size
    result: dict[str, Any] = {
        "path": rel,
        "exists": True,
        "type": "file",
        "size": size,
        "sha256": sha256_file(path),
    }
    if size <= max_bytes:
        try:
            result["content"] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            result["content"] = "[BINARY]"
    return result


def run_scenario(root: Path, scenario: dict[str, Any]) -> dict[str, Any]:
    name = scenario.get("name")
    command = scenario.get("command")
    if not isinstance(name, str) or not name.strip():
        raise ConfigurationError("each golden scenario needs a non-empty name")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(value, str) for value in command)
    ):
        raise ConfigurationError(f"golden scenario {name!r} needs a string-array command")
    cwd_value = str(scenario.get("cwd", "."))
    cwd = (root / cwd_value).resolve()
    try:
        cwd.relative_to(root.resolve())
    except ValueError as exc:
        raise ConfigurationError(f"golden scenario {name!r} cwd escapes repository") from exc
    timeout = int(scenario.get("timeout_seconds", 60))
    env = os.environ.copy()
    for key, value in scenario.get("env", {}).items():
        env[str(key)] = str(value)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout, check=False
        )
        timed_out = False
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = INFRASTRUCTURE_ERROR
        stdout = (
            exc.stdout.decode(errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            exc.stderr.decode(errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
    rules = scenario.get("normalize", [])
    if not isinstance(rules, list):
        raise ConfigurationError(f"golden scenario {name!r} normalize must be an array")
    max_bytes = int(scenario.get("max_capture_bytes", 200_000))
    captures = [
        _capture_file(root, str(path), max_bytes) for path in scenario.get("capture_files", [])
    ]
    return {
        "schema_version": 1,
        "name": name,
        "command": command,
        "cwd": cwd_value,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout": _normalize(stdout, rules),
        "stderr": _normalize(stderr, rules),
        "files": captures,
        "duration_class": "slow"
        if time.monotonic() - started > float(scenario.get("slow_seconds", 5))
        else "normal",
    }


def run_goldens(
    root: Path, *, update: bool = False, scenario_name: str | None = None
) -> tuple[int, dict[str, Any]]:
    payload = load_scenarios(root)
    if update and os.environ.get("AQG_ALLOW_GOLDEN_UPDATE") != "1":
        raise ConfigurationError(
            "golden updates require AQG_ALLOW_GOLDEN_UPDATE=1 and human review"
        )
    results: list[dict[str, Any]] = []
    final = PASS
    expected_dir = root / "quality" / "golden" / "expected"
    expected_dir.mkdir(parents=True, exist_ok=True)
    selected = [
        item
        for item in payload["scenarios"]
        if scenario_name is None or item.get("name") == scenario_name
    ]
    if scenario_name and not selected:
        raise ConfigurationError(f"unknown golden scenario {scenario_name!r}")
    for scenario in selected:
        actual = run_scenario(root, scenario)
        filename = re.sub(r"[^A-Za-z0-9._-]+", "-", actual["name"].lower()).strip("-") + ".json"
        expected_path = expected_dir / filename
        difference: Any
        if update:
            write_json(expected_path, actual)
            status = "updated"
            code = PASS
            difference = None
        elif not expected_path.exists():
            status = "missing"
            code = CONFIGURATION_ERROR
            difference = "expected artifact does not exist; run the separately reviewed golden update command"
        else:
            expected = read_json(expected_path)
            code = PASS if expected == actual else QUALITY_FAILURE
            status = "pass" if code == PASS else "changed"
            difference = None if code == PASS else {"expected": expected, "actual": actual}
        final = max(final, code)
        results.append(
            {
                "name": actual["name"],
                "status": status,
                "code": code,
                "expected": str(expected_path.relative_to(root)),
                "difference": difference,
            }
        )
    report = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "update": update,
        "status": final,
        "results": results,
    }
    write_json(root / ".aqg" / "work" / "golden" / "report.json", report)
    return final, report
