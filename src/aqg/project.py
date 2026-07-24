"""Project-local AQG configuration model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .constants import DEFAULT_EXCLUDES
from .errors import ConfigurationError
from .util import read_json


def load_project(root: Path) -> dict[str, Any]:
    path = root / "quality" / "project.json"
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ConfigurationError(f"{path} must contain a JSON object")
    errors = validate_project(payload)
    if errors:
        raise ConfigurationError("invalid quality/project.json: " + "; ".join(errors))
    return payload


def validate_project(project: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if project.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    if not isinstance(project.get("name"), str) or not project.get("name", "").strip():
        errors.append("name must be a non-empty string")

    stacks = project.get("stacks")
    if not isinstance(stacks, dict):
        errors.append("stacks must be an object")
    else:
        for name in ("javascript", "typescript", "python", "html", "css"):
            if not isinstance(stacks.get(name), bool):
                errors.append(f"stacks.{name} must be boolean")
        if stacks.get("typescript") and not stacks.get("javascript"):
            errors.append("stacks.typescript=true requires stacks.javascript=true")

    paths = project.get("paths")
    if not isinstance(paths, dict):
        errors.append("paths must be an object")
    else:
        for key in ("source", "tests", "html", "css", "exclude"):
            value = paths.get(key)
            if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
                errors.append(f"paths.{key} must be an array of non-empty strings")

    enforcement = project.get("enforcement")
    if not isinstance(enforcement, dict):
        errors.append("enforcement must be an object")
    else:
        if enforcement.get("mode") not in {"adopt", "greenfield"}:
            errors.append("enforcement.mode must be adopt or greenfield")
        if enforcement.get("scope") not in {"changed", "full"}:
            errors.append("enforcement.scope must be changed or full")
        if not isinstance(enforcement.get("base_ref"), str) or not enforcement.get("base_ref", "").strip():
            errors.append("enforcement.base_ref must be a non-empty Git ref")

    gates = project.get("gates")
    if not isinstance(gates, dict) or not gates:
        errors.append("gates must be a non-empty object")
    else:
        for gate, config in gates.items():
            if not isinstance(config, dict):
                errors.append(f"gates.{gate} must be an object")
                continue
            if not isinstance(config.get("applicable"), bool):
                errors.append(f"gates.{gate}.applicable must be boolean")
            if config.get("applicable") is False and not str(config.get("reason", "")).strip():
                errors.append(f"gates.{gate}.reason is required when the gate is not applicable")

    thresholds = project.get("thresholds")
    if not isinstance(thresholds, dict):
        errors.append("thresholds must be an object")
    else:
        for group in ("coverage", "structure", "mutation", "security", "performance"):
            if not isinstance(thresholds.get(group), dict):
                errors.append(f"thresholds.{group} must be an object")
        coverage = thresholds.get("coverage", {}) if isinstance(thresholds.get("coverage"), dict) else {}
        for key in ("lines", "branches", "functions", "statements", "changed_lines"):
            value = coverage.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 100:
                errors.append(f"thresholds.coverage.{key} must be a number from 0 to 100")
        structure = thresholds.get("structure", {}) if isinstance(thresholds.get("structure"), dict) else {}
        for key in ("max_function_lines", "max_cyclomatic_complexity", "max_crap", "max_nesting_depth"):
            value = structure.get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                errors.append(f"thresholds.structure.{key} must be a positive number")
        mutation = thresholds.get("mutation", {}) if isinstance(thresholds.get("mutation"), dict) else {}
        score = mutation.get("minimum_score")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 100:
            errors.append("thresholds.mutation.minimum_score must be a number from 0 to 100")
        survivors = mutation.get("maximum_survivors")
        if not isinstance(survivors, int) or isinstance(survivors, bool) or survivors < 0:
            errors.append("thresholds.mutation.maximum_survivors must be a non-negative integer")

    profile_thresholds = project.get("profile_thresholds", {})
    if not isinstance(profile_thresholds, dict):
        errors.append("profile_thresholds must be an object")
    else:
        for profile, overrides in profile_thresholds.items():
            if profile not in {"fast", "pr", "deep", "release"}:
                errors.append(f"profile_thresholds has unknown execution profile {profile!r}")
            if not isinstance(overrides, dict):
                errors.append(f"profile_thresholds.{profile} must be an object")

    web = project.get("web")
    if not isinstance(web, dict):
        errors.append("web must be an object")
    else:
        start = web.get("start_command")
        if start is not None and (not isinstance(start, list) or not start or any(not isinstance(item, str) for item in start)):
            errors.append("web.start_command must be null or a non-empty string array")
        url = web.get("base_url")
        if url is not None and (not isinstance(url, str) or not url.startswith(("http://", "https://"))):
            errors.append("web.base_url must be null or an http(s) URL")
    return errors


def source_paths(project: dict[str, Any]) -> list[str]:
    paths = project.get("paths", {}).get("source", ["."])
    return [str(value) for value in paths] if isinstance(paths, list) else ["."]


def test_paths(project: dict[str, Any]) -> list[str]:
    paths = project.get("paths", {}).get("tests", [])
    return [str(value) for value in paths] if isinstance(paths, list) else []


def excludes(project: dict[str, Any]) -> list[str]:
    values = project.get("paths", {}).get("exclude", DEFAULT_EXCLUDES)
    return [str(value) for value in values] if isinstance(values, list) else list(DEFAULT_EXCLUDES)


def gate_config(project: dict[str, Any], gate: str) -> dict[str, Any]:
    value = project.get("gates", {}).get(gate, {})
    return value if isinstance(value, dict) else {}


def gate_applicable(project: dict[str, Any], gate: str) -> tuple[bool, str]:
    config = gate_config(project, gate)
    applicable = config.get("applicable", True)
    reason = str(config.get("reason", ""))
    return bool(applicable), reason
