"""Artifact-backed assurance for exact-candidate functional evidence."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .constants import INFRASTRUCTURE_ERROR, PASS, QUALITY_FAILURE
from .council import ROLES
from .council_service import report_council
from .errors import ConfigurationError
from .project import gate_applicable
from .util import (
    change_fingerprint,
    control_fingerprint,
    git_revision,
    read_json,
    run_command,
)

ASSURANCE_SCHEMA_VERSION = 1
AUTHORITY_TRIGGERS = (
    "guardrail_weakening",
    "paid_external_action",
    "private_data_exposure",
    "irreversible_execution",
)


def _base_ref(project: Mapping[str, Any]) -> str:
    return os.environ.get("AQG_DIFF_BASE") or str(
        project.get("enforcement", {}).get("base_ref", "HEAD")
    )


def _scope(root: Path, project: Mapping[str, Any]) -> dict[str, str]:
    base = _base_ref(project)
    return {
        "revision": git_revision(root),
        "base_ref": base,
        "change_fingerprint": change_fingerprint(root, base),
        "control_fingerprint": control_fingerprint(root),
    }


def _gate_details(root: Path, run_id: str, gate: str) -> dict[str, Any] | None:
    path = root / ".aqg" / "runs" / run_id / "gates" / f"{gate}.details.json"
    if not path.is_file():
        return None
    payload = read_json(path)
    return payload if isinstance(payload, dict) else None


def _required_behavior_gates(selected: str, project: Mapping[str, Any]) -> list[str]:
    names = ["acceptance", "review"]
    if selected in {"high_assurance", "critical"}:
        names.append("mutation_acceptance")
    return [name for name in names if gate_applicable(dict(project), name)[0]]


def _behavior_control(
    root: Path, project: Mapping[str, Any], selected: str, run_id: str | None
) -> dict[str, Any]:
    required = _required_behavior_gates(selected, project)
    if not run_id:
        return {
            "status": "unusable",
            "required_gates": required,
            "evidence": [],
            "errors": ["assurance must run inside a profile-owned evidence directory"],
        }
    evidence: list[dict[str, Any]] = []
    errors: list[str] = []
    for gate in required:
        details = _gate_details(root, run_id, gate)
        if details is None:
            errors.append(f"missing current {gate} gate details")
            continue
        evidence.append(
            {
                "gate": gate,
                "status": details.get("status"),
                "exit_code": details.get("exit_code"),
                "path": f"gates/{gate}.details.json",
            }
        )
        if details.get("exit_code") != PASS or details.get("status") != "pass":
            errors.append(f"current {gate} evidence is {details.get('status', 'unknown')}")
    return {
        "status": "works" if not errors else "broken",
        "required_gates": required,
        "evidence": evidence,
        "errors": errors,
    }


def _render_command(command: Any, output: Path) -> list[str]:
    if not isinstance(command, list) or not command or any(not isinstance(v, str) for v in command):
        raise ConfigurationError("assurance.rehearsal_command must be a non-empty string array")
    rendered = [value.replace("{output}", str(output)) for value in command]
    if not any(str(output) in value for value in rendered):
        raise ConfigurationError("assurance.rehearsal_command must contain {output}")
    return rendered


def _validate_rehearsal_payload(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["functional rehearsal output must be a JSON object"]
    errors: list[str] = []
    if payload.get("schema_version") != 2:
        errors.append("functional rehearsal schema_version must be 2")
    if payload.get("status") != "pass":
        errors.append("functional rehearsal status must be pass")
    qa = payload.get("functional_qa")
    if not isinstance(qa, dict) or qa.get("status") != "pass":
        errors.append("functional_qa.status must be pass")
    elif not isinstance(qa.get("checks"), list) or not qa["checks"]:
        errors.append("functional_qa.checks must contain executed checks")
    rollback = payload.get("rollback")
    if not isinstance(rollback, dict) or rollback.get("status") != "pass":
        errors.append("rollback.status must be pass")
    elif rollback.get("restored_matches_before") is not True:
        errors.append("rollback must prove restored_matches_before")
    if payload.get("cleanup_verified") is not True:
        errors.append("functional rehearsal must prove cleanup_verified")
    return errors


def _rehearsal_control(root: Path, project: Mapping[str, Any]) -> dict[str, Any]:
    config = project.get("assurance")
    if not isinstance(config, Mapping):
        return {
            "status": "not_tested",
            "errors": ["quality/project.json has no assurance rehearsal configuration"],
        }
    output = root / ".aqg" / "work" / "assurance" / "functional-rehearsal.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    try:
        command = _render_command(config.get("rehearsal_command"), output)
    except ConfigurationError as exc:
        return {"status": "unusable", "errors": [str(exc)]}
    result = run_command(command, cwd=root, timeout=int(config.get("timeout_seconds", 600)))
    if result.code != 0:
        state = "broken" if result.code == QUALITY_FAILURE else "unusable"
        return {"status": state, "command": result.as_dict(), "errors": [result.status]}
    if not output.is_file():
        return {
            "status": "unusable",
            "command": result.as_dict(),
            "errors": ["rehearsal command produced no output"],
        }
    try:
        payload = read_json(output)
    except ConfigurationError as exc:
        return {
            "status": "unusable",
            "command": result.as_dict(),
            "errors": [str(exc)],
        }
    errors = _validate_rehearsal_payload(payload)
    return {
        "status": "works" if not errors else "broken",
        "command": result.as_dict(),
        "artifact": str(output.relative_to(root)),
        "result": payload,
        "errors": errors,
    }


def _council_errors(report: Mapping[str, Any], scope: Mapping[str, str]) -> list[str]:
    council_scope = report.get("scope")
    if not isinstance(council_scope, Mapping):
        return ["council report has no scope"]
    expected = {
        "revision": scope["revision"],
        "base_revision": scope["base_ref"],
        "change_fingerprint": scope["change_fingerprint"],
        "control_fingerprint": scope["control_fingerprint"],
    }
    errors = [
        f"council {name} does not match the current candidate"
        for name, value in expected.items()
        if council_scope.get(name) != value
    ]
    if report.get("tier") != "high":
        errors.append("independent agent verification requires the high council tier")
    if report.get("status") != "advisory_clear" or report.get("complete") is not True:
        errors.append("independent agent verification is not complete and clear")
    if set(report.get("covered_roles", [])) != set(ROLES):
        errors.append("independent agent verification does not cover every required role")
    if len(set(report.get("provider_groups", []))) < 3:
        errors.append("independent agent verification needs at least three provider groups")
    dissent = report.get("dissent")
    if not isinstance(dissent, Mapping) or dissent.get("present") is not False:
        errors.append("independent agent verification contains or cannot classify dissent")
    if report.get("blockers") or report.get("incomplete_reasons"):
        errors.append("independent agent verification contains blockers or incomplete evidence")
    verification = report.get("verification")
    if not isinstance(verification, Mapping) or verification.get("ok") is not True:
        errors.append("independent agent verification manifest is invalid")
    return errors


def _independent_control(root: Path, scope: Mapping[str, str]) -> dict[str, Any]:
    if os.environ.get("AQG_TRUSTED_MODE") == "1":
        required = (
            "AQG_TRUSTED_LAUNCHER",
            "AQG_TRUSTED_POLICY_PATH",
            "AQG_TRUSTED_PROJECT_PATH",
            "AQG_TRUSTED_TOOLCHAIN_ROOT",
        )
        missing = [name for name in required if not os.environ.get(name)]
        return {
            "status": "works" if not missing else "unusable",
            "method": "base-controlled-trusted-grader",
            "errors": [f"missing {name}" for name in missing],
        }
    try:
        report = report_council(root)
    except (ConfigurationError, OSError) as exc:
        return {"status": "not_tested", "method": "agent-council", "errors": [str(exc)]}
    errors = _council_errors(report, scope)
    return {
        "status": "works" if not errors else "broken",
        "method": "agent-council",
        "run_id": report.get("run_id"),
        "report": report,
        "errors": errors,
    }


def _authority_control(card: Mapping[str, Any]) -> dict[str, Any]:
    raw = card.get("authority_triggers", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        return {
            "status": "unusable",
            "triggers": {},
            "errors": ["authority_triggers must be an object"],
        }
    invalid = [name for name in AUTHORITY_TRIGGERS if not isinstance(raw.get(name, False), bool)]
    active = [name for name in AUTHORITY_TRIGGERS if raw.get(name) is True]
    errors = [f"authority trigger {name} must be boolean" for name in invalid]
    return {
        "status": "unusable" if errors else ("human_decision_needed" if active else "works"),
        "triggers": {name: bool(raw.get(name, False)) for name in AUTHORITY_TRIGGERS},
        "active": active,
        "errors": errors,
    }


def _exit_code(controls: Mapping[str, Mapping[str, Any]]) -> int:
    states = {str(item.get("status")) for item in controls.values()}
    if "unusable" in states or "not_tested" in states:
        return INFRASTRUCTURE_ERROR
    if "broken" in states or "human_decision_needed" in states:
        return QUALITY_FAILURE
    return PASS


def evaluate_assurance(
    root: Path,
    project: Mapping[str, Any],
    risk: Mapping[str, Any],
    *,
    run_id: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Evaluate functional assurance without accepting prose-only approval files."""
    selected = str(risk.get("selected_risk_profile") or "standard")
    scope = _scope(root, project)
    controls: dict[str, dict[str, Any]] = {
        "behavior": _behavior_control(root, project, selected, run_id),
        "authority": _authority_control(risk.get("card", {})),
    }
    if selected in {"high_assurance", "critical"}:
        controls["functional_rehearsal"] = _rehearsal_control(root, project)
        controls["independent_verification"] = _independent_control(root, scope)
    code = _exit_code(controls)
    return code, {
        "schema_version": ASSURANCE_SCHEMA_VERSION,
        "kind": "aqg-functional-assurance",
        "scope": scope,
        "risk_profile": selected,
        "controls": controls,
        "status": "works" if code == PASS else "not_ready",
        "failures": [
            f"{name}: {error}"
            for name, item in controls.items()
            for error in item.get("errors", [])
        ],
    }
