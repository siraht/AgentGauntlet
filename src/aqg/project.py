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


def _validate_identity(project: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if project.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    if not isinstance(project.get("name"), str) or not project.get("name", "").strip():
        errors.append("name must be a non-empty string")
    return errors


def _validate_stacks(project: dict[str, Any]) -> list[str]:
    stacks = project.get("stacks")
    if not isinstance(stacks, dict):
        return ["stacks must be an object"]
    errors = [
        f"stacks.{name} must be boolean"
        for name in ("javascript", "typescript", "python", "html", "css")
        if not isinstance(stacks.get(name), bool)
    ]
    if stacks.get("typescript") and not stacks.get("javascript"):
        errors.append("stacks.typescript=true requires stacks.javascript=true")
    return errors


def _validate_paths(project: dict[str, Any]) -> list[str]:
    paths = project.get("paths")
    if not isinstance(paths, dict):
        return ["paths must be an object"]
    return [
        f"paths.{key} must be an array of non-empty strings"
        for key in ("source", "tests", "html", "css", "exclude")
        if not isinstance(paths.get(key), list)
        or any(not isinstance(item, str) or not item.strip() for item in paths[key])
    ]


def _validate_enforcement(project: dict[str, Any]) -> list[str]:
    enforcement = project.get("enforcement")
    if not isinstance(enforcement, dict):
        return ["enforcement must be an object"]
    errors: list[str] = []
    if enforcement.get("mode") not in {"adopt", "greenfield"}:
        errors.append("enforcement.mode must be adopt or greenfield")
    if enforcement.get("scope") not in {"changed", "full"}:
        errors.append("enforcement.scope must be changed or full")
    if not isinstance(enforcement.get("base_ref"), str) or not enforcement["base_ref"].strip():
        errors.append("enforcement.base_ref must be a non-empty Git ref")
    return errors


def _validate_gates(project: dict[str, Any]) -> list[str]:
    gates = project.get("gates")
    if not isinstance(gates, dict) or not gates:
        return ["gates must be a non-empty object"]
    errors: list[str] = []
    for gate, config in gates.items():
        if not isinstance(config, dict):
            errors.append(f"gates.{gate} must be an object")
        elif not isinstance(config.get("applicable"), bool):
            errors.append(f"gates.{gate}.applicable must be boolean")
        if isinstance(config, dict) and config.get("applicable") is False:
            if not str(config.get("reason", "")).strip():
                errors.append(f"gates.{gate}.reason is required when the gate is not applicable")
    return errors


def _validate_threshold_groups(thresholds: Any) -> list[str]:
    if not isinstance(thresholds, dict):
        return ["thresholds must be an object"]
    return [
        f"thresholds.{group} must be an object"
        for group in ("coverage", "structure", "mutation", "security", "performance")
        if not isinstance(thresholds.get(group), dict)
    ]


def _validate_coverage_thresholds(thresholds: Any) -> list[str]:
    coverage = thresholds.get("coverage", {}) if isinstance(thresholds, dict) else {}
    if not isinstance(coverage, dict):
        return []
    errors: list[str] = []
    for key in ("lines", "branches", "functions", "statements", "changed_lines"):
        value = coverage.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 100:
            errors.append(f"thresholds.coverage.{key} must be a number from 0 to 100")
    return errors


def _validate_structure_thresholds(thresholds: Any) -> list[str]:
    structure = thresholds.get("structure", {}) if isinstance(thresholds, dict) else {}
    if not isinstance(structure, dict):
        return []
    errors: list[str] = []
    for key in (
        "max_function_lines",
        "max_cyclomatic_complexity",
        "max_crap",
        "max_nesting_depth",
    ):
        value = structure.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            errors.append(f"thresholds.structure.{key} must be a positive number")
    return errors


def _validate_mutation_thresholds(thresholds: Any) -> list[str]:
    mutation = thresholds.get("mutation", {}) if isinstance(thresholds, dict) else {}
    if not isinstance(mutation, dict):
        return []
    errors: list[str] = []
    score = mutation.get("minimum_score")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 100:
        errors.append("thresholds.mutation.minimum_score must be a number from 0 to 100")
    survivors = mutation.get("maximum_survivors")
    if not isinstance(survivors, int) or isinstance(survivors, bool) or survivors < 0:
        errors.append("thresholds.mutation.maximum_survivors must be a non-negative integer")
    return errors


def _validate_thresholds(project: dict[str, Any]) -> list[str]:
    thresholds = project.get("thresholds")
    return [
        *_validate_threshold_groups(thresholds),
        *_validate_coverage_thresholds(thresholds),
        *_validate_structure_thresholds(thresholds),
        *_validate_mutation_thresholds(thresholds),
    ]


def _validate_profile_thresholds(project: dict[str, Any]) -> list[str]:
    profile_thresholds = project.get("profile_thresholds", {})
    if not isinstance(profile_thresholds, dict):
        return ["profile_thresholds must be an object"]
    errors: list[str] = []
    for profile, overrides in profile_thresholds.items():
        if profile not in {"fast", "pr", "deep", "release"}:
            errors.append(f"profile_thresholds has unknown execution profile {profile!r}")
        if not isinstance(overrides, dict):
            errors.append(f"profile_thresholds.{profile} must be an object")
    return errors


def _validate_web(project: dict[str, Any]) -> list[str]:
    web = project.get("web")
    if not isinstance(web, dict):
        return ["web must be an object"]
    errors: list[str] = []
    start = web.get("start_command")
    if start is not None and (
        not isinstance(start, list) or not start or any(not isinstance(item, str) for item in start)
    ):
        errors.append("web.start_command must be null or a non-empty string array")
    url = web.get("base_url")
    if url is not None and (
        not isinstance(url, str) or not url.startswith(("http://", "https://"))
    ):
        errors.append("web.base_url must be null or an http(s) URL")
    return errors


def validate_project(project: dict[str, Any]) -> list[str]:
    """Return every project configuration defect in stable document order."""
    return [
        *_validate_identity(project),
        *_validate_stacks(project),
        *_validate_paths(project),
        *_validate_enforcement(project),
        *_validate_gates(project),
        *_validate_thresholds(project),
        *_validate_profile_thresholds(project),
        *_validate_web(project),
    ]


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
