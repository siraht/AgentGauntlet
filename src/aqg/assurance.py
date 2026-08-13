"""Artifact-backed assurance for exact-candidate functional evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .constants import INFRASTRUCTURE_ERROR, PASS, QUALITY_FAILURE
from .council import ROLES
from .council_service import report_council
from .errors import ConfigurationError
from .project import gate_applicable
from .trusted_verification import verify_trusted_verifier_evidence
from .util import (
    change_fingerprint,
    control_fingerprint,
    git_output,
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
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
_REHEARSAL_KEYS = {
    "schema_version",
    "evidence_type",
    "status",
    "candidate",
    "result_identity",
    "durations_ms",
    "cleanup",
    "cold_start",
    "setup",
    "functional_qa",
    "rollback",
    "cleanup_verified",
}
_QA_CHECKS = {"cold_start", "setup", "review", "conformance", "dashboard", "tui"}


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


def _exact_keys(value: Mapping[str, Any], expected: set[str], location: str) -> list[str]:
    if set(value) == expected:
        return []
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    return [f"{location} keys differ: missing={missing!r}, unknown={unknown!r}"]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _expected_result_identity(payload: Mapping[str, Any]) -> str:
    stable = dict(payload)
    stable.pop("result_identity", None)
    stable.pop("durations_ms", None)
    return "sha256:" + hashlib.sha256(_canonical(stable)).hexdigest()


def _validate_rehearsal_payload(
    payload: Any, *, revision: str | None = None, dirty: bool | None = None
) -> list[str]:
    if not isinstance(payload, dict):
        return ["functional rehearsal output must be a JSON object"]
    errors = _exact_keys(payload, _REHEARSAL_KEYS, "functional rehearsal")
    errors.extend(_rehearsal_identity_errors(payload, revision))
    errors.extend(_candidate_errors(payload.get("candidate"), revision, dirty))
    errors.extend(_duration_errors(payload.get("durations_ms")))
    errors.extend(_cleanup_errors(payload.get("cleanup"), payload.get("cleanup_verified")))
    errors.extend(_functional_qa_errors(payload.get("functional_qa")))
    errors.extend(_rollback_errors(payload.get("rollback")))
    errors.extend(_alias_errors(payload))
    return errors


def _rehearsal_identity_errors(payload: Mapping[str, Any], revision: str | None) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != 2:
        errors.append("functional rehearsal schema_version must be 2")
    if payload.get("evidence_type") != "aqg.functional-rehearsal":
        errors.append("functional rehearsal evidence_type is invalid")
    if payload.get("status") != "pass":
        errors.append("functional rehearsal status must be pass")
    identity = payload.get("result_identity")
    if not isinstance(identity, str) or not _SHA256.fullmatch(identity):
        errors.append("functional rehearsal result_identity must be a SHA-256 digest")
    elif identity != _expected_result_identity(payload):
        errors.append("functional rehearsal result_identity does not match its content")
    return errors


def _candidate_errors(candidate: Any, revision: str | None, dirty: bool | None) -> list[str]:
    if not isinstance(candidate, Mapping):
        return ["functional rehearsal candidate must be an object"]
    errors = _exact_keys(
        candidate, {"revision", "dirty", "source_tree_sha256", "material_count"}, "candidate"
    )
    candidate_revision = candidate.get("revision")
    checks = (
        (
            isinstance(candidate_revision, str) and bool(_REVISION.fullmatch(candidate_revision)),
            "candidate revision must be a Git object identity",
        ),
        (
            revision is None or candidate_revision == revision,
            "candidate revision does not match the current candidate",
        ),
        (isinstance(candidate.get("dirty"), bool), "candidate dirty must be boolean"),
        (
            dirty is None or candidate.get("dirty") is dirty,
            "candidate dirty state does not match the current candidate",
        ),
        (
            isinstance(candidate.get("source_tree_sha256"), str)
            and bool(_HEX_SHA256.fullmatch(candidate["source_tree_sha256"])),
            "candidate source_tree_sha256 must be a SHA-256 digest",
        ),
        (
            isinstance(candidate.get("material_count"), int)
            and not isinstance(candidate.get("material_count"), bool)
            and candidate["material_count"] > 0,
            "candidate material_count must be a positive integer",
        ),
    )
    return errors + [message for passed, message in checks if not passed]


def _duration_errors(durations: Any) -> list[str]:
    expected = {"total", "cold_start", "setup", "commands", "dashboard", "tui", "rollback"}
    if not isinstance(durations, Mapping):
        return ["durations_ms must be an object"]
    errors = _exact_keys(durations, expected, "durations_ms")
    if any(not _nonnegative_integer(value) for value in durations.values()):
        errors.append("durations_ms values must be non-negative integers")
    return errors + _duration_order_errors(durations)


def _nonnegative_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _duration_order_errors(durations: Mapping[str, Any]) -> list[str]:
    total = durations.get("total")
    phases = [value for key, value in durations.items() if key != "total"]
    comparable = _nonnegative_integer(total) and all(
        _nonnegative_integer(value) for value in phases
    )
    return (
        ["total duration cannot be shorter than a phase"]
        if comparable and any(total < value for value in phases)
        else []
    )


def _cleanup_errors(cleanup: Any, verified: Any) -> list[str]:
    expected = {"method": "TemporaryDirectory", "temporary_workspace_removed": True}
    errors = [] if cleanup == expected else ["disposable workspace cleanup was not verified"]
    if verified is not True:
        errors.append("functional rehearsal must prove cleanup_verified")
    return errors


def _functional_qa_errors(qa: Any) -> list[str]:
    if not isinstance(qa, Mapping):
        return ["functional_qa must be an object"]
    errors = _exact_keys(qa, {"status", "procedure", "checks", "evidence"}, "functional_qa")
    if qa.get("status") != "pass":
        errors.append("functional_qa.status must be pass")
    errors.extend(_qa_procedure_errors(qa.get("procedure")))
    return errors + _qa_checks_errors(qa)


def _qa_procedure_errors(procedure: Any) -> list[str]:
    expected = {
        "id": "QA-AQG-CONTROL-SURFACES-001",
        "path": "qa/procedures/control-surface-rehearsal.md",
        "execution_mode": "agent-operated executable procedure",
        "executor": "aqg deterministic rehearsal",
    }
    return [] if procedure == expected else ["functional_qa procedure identity is invalid"]


def _qa_checks_errors(qa: Mapping[str, Any]) -> list[str]:
    checks = qa.get("checks")
    if not _named_checks(checks):
        return ["functional_qa.checks must contain named executed checks"]
    assert isinstance(checks, list)
    errors: list[str] = []
    if set(checks) != _QA_CHECKS:
        errors.append("functional_qa.checks must cover every required public control surface")
    if len(checks) != len(set(checks)):
        errors.append("functional_qa.checks must be unique")
    return errors + _qa_evidence_errors(checks, qa.get("evidence"))


def _named_checks(checks: Any) -> bool:
    return (
        isinstance(checks, list)
        and bool(checks)
        and all(isinstance(item, str) and bool(item) for item in checks)
    )


def _qa_evidence_errors(checks: list[Any], evidence: Any) -> list[str]:
    if not isinstance(evidence, Mapping) or set(evidence) != set(checks):
        return ["functional_qa.evidence must match every named check"]
    if any(not isinstance(item, Mapping) or not item for item in evidence.values()):
        return ["every functional QA check must contain non-empty evidence"]
    return []


def _rollback_errors(rollback: Any) -> list[str]:
    if not isinstance(rollback, Mapping):
        return ["rollback must be an object"]
    expected = {
        "status",
        "mechanism",
        "before_identity",
        "candidate_identity",
        "restored_identity",
        "candidate_changed",
        "restored_matches_before",
        "operation_outputs_equal",
    }
    errors = _exact_keys(rollback, expected, "rollback")
    if rollback.get("status") != "pass":
        errors.append("rollback.status must be pass")
    if not isinstance(rollback.get("mechanism"), str) or not rollback["mechanism"].strip():
        errors.append("rollback mechanism must be non-empty")
    errors.extend(_rollback_digest_errors(rollback))
    errors.extend(_rollback_proof_errors(rollback))
    return errors


def _rollback_digest_errors(rollback: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for name in ("before_identity", "candidate_identity", "restored_identity"):
        if not isinstance(rollback.get(name), str) or not _SHA256.fullmatch(rollback[name]):
            errors.append(f"rollback {name} must be a SHA-256 digest")
    return errors


def _rollback_proof_errors(rollback: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    proof = ("candidate_changed", "restored_matches_before", "operation_outputs_equal")
    if any(rollback.get(name) is not True for name in proof):
        errors.append("rollback must prove changed candidate, exact restoration, and equal output")
    if rollback.get("before_identity") != rollback.get("restored_identity"):
        errors.append("rollback restored identity does not match before identity")
    if rollback.get("candidate_identity") == rollback.get("before_identity"):
        errors.append("rollback candidate identity does not demonstrate a changed installation")
    return errors


def _alias_errors(payload: Mapping[str, Any]) -> list[str]:
    qa = payload.get("functional_qa")
    evidence = qa.get("evidence") if isinstance(qa, Mapping) else None
    if not isinstance(evidence, Mapping):
        return []
    errors: list[str] = []
    if payload.get("cold_start") != evidence.get("cold_start"):
        errors.append("cold_start alias does not match functional QA evidence")
    if payload.get("setup") != evidence.get("setup"):
        errors.append("setup alias does not match functional QA evidence")
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
    errors = _validate_rehearsal_payload(
        payload,
        revision=git_revision(root),
        dirty=_candidate_dirty(root),
    )
    return {
        "status": "works" if not errors else "broken",
        "command": result.as_dict(),
        "artifact": str(output.relative_to(root)),
        "result": payload,
        "errors": errors,
    }


def _manual_qa_control(rehearsal: Mapping[str, Any]) -> dict[str, Any]:
    result = rehearsal.get("result")
    qa = result.get("functional_qa") if isinstance(result, Mapping) else None
    procedure = qa.get("procedure") if isinstance(qa, Mapping) else None
    errors = _manual_qa_errors(rehearsal, procedure)
    return {
        "status": "works" if not errors else "broken",
        "method": "agent-operated executable procedure",
        "procedure": dict(procedure) if isinstance(procedure, Mapping) else None,
        "artifact": rehearsal.get("artifact"),
        "errors": errors,
    }


def _manual_qa_errors(rehearsal: Mapping[str, Any], procedure: Any) -> list[str]:
    errors = list(rehearsal.get("errors", []))
    if rehearsal.get("status") != "works":
        errors.append("the executed functional QA procedure is not green")
    if not isinstance(procedure, Mapping):
        errors.append("executed functional QA procedure identity is missing")
    return errors


def _candidate_dirty(root: Path) -> bool:
    code, stdout, _ = git_output(
        root,
        [
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "qg",
            "src/aqg",
            "scripts/dogfood_control_surfaces.py",
        ],
    )
    return code != 0 or bool(stdout.strip())


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
    return errors + _council_quality_errors(report) + _council_integrity_errors(report)


def _council_quality_errors(report: Mapping[str, Any]) -> list[str]:
    checks = (
        (
            report.get("purpose", "candidate") == "candidate",
            "independent agent verification requires candidate-purpose council evidence",
        ),
        (
            report.get("tier") == "high",
            "independent agent verification requires the high council tier",
        ),
        (
            report.get("status") == "advisory_clear" and report.get("complete") is True,
            "independent agent verification is not complete and clear",
        ),
        (
            set(report.get("covered_roles", [])) == set(ROLES),
            "independent agent verification does not cover every required role",
        ),
        (
            len(set(report.get("provider_groups", []))) >= 3,
            "independent agent verification needs at least three provider groups",
        ),
    )
    return [message for passed, message in checks if not passed]


def _council_integrity_errors(report: Mapping[str, Any]) -> list[str]:
    dissent = report.get("dissent")
    verification = report.get("verification")
    checks = (
        (
            isinstance(dissent, Mapping) and dissent.get("present") is False,
            "independent agent verification contains or cannot classify dissent",
        ),
        (
            not report.get("blockers") and not report.get("incomplete_reasons"),
            "independent agent verification contains blockers or incomplete evidence",
        ),
        (
            isinstance(verification, Mapping) and verification.get("ok") is True,
            "independent agent verification manifest is invalid",
        ),
    )
    return [message for passed, message in checks if not passed]


def _independent_control(root: Path, scope: Mapping[str, str]) -> dict[str, Any]:
    if os.environ.get("AQG_TRUSTED_MODE") == "1":
        return verify_trusted_verifier_evidence(root, scope)
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
    invalid, active = _authority_sets(raw)
    errors = [f"authority trigger {name} must be boolean" for name in invalid]
    return {
        "status": "unusable" if errors else ("human_decision_needed" if active else "works"),
        "triggers": {name: bool(raw.get(name, False)) for name in AUTHORITY_TRIGGERS},
        "active": active,
        "errors": errors,
    }


def _authority_sets(raw: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    invalid = [name for name in AUTHORITY_TRIGGERS if not isinstance(raw.get(name, False), bool)]
    active = [name for name in AUTHORITY_TRIGGERS if raw.get(name) is True]
    return invalid, active


def _exit_code(controls: Mapping[str, Mapping[str, Any]]) -> int:
    states = {str(item.get("status")) for item in controls.values()}
    if "unusable" in states or "not_tested" in states:
        return INFRASTRUCTURE_ERROR
    if "broken" in states or "human_decision_needed" in states:
        return QUALITY_FAILURE
    return PASS


def _add_high_assurance_controls(
    controls: dict[str, dict[str, Any]],
    root: Path,
    project: Mapping[str, Any],
    risk: Mapping[str, Any],
    scope: Mapping[str, str],
) -> None:
    rehearsal = _rehearsal_control(root, project)
    controls["functional_rehearsal"] = rehearsal
    if risk.get("required_controls", {}).get("requires_manual_qa") is True:
        controls["manual_qa"] = _manual_qa_control(rehearsal)
    controls["independent_verification"] = _independent_control(root, scope)


def _assurance_result(
    controls: Mapping[str, Mapping[str, Any]], scope: Mapping[str, str], selected: str
) -> tuple[int, dict[str, Any]]:
    code = _exit_code(controls)
    failures = [
        f"{name}: {error}" for name, item in controls.items() for error in item.get("errors", [])
    ]
    return code, {
        "schema_version": ASSURANCE_SCHEMA_VERSION,
        "kind": "aqg-functional-assurance",
        "scope": dict(scope),
        "risk_profile": selected,
        "controls": dict(controls),
        "status": "works" if code == PASS else "not_ready",
        "failures": failures,
    }


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
        _add_high_assurance_controls(controls, root, project, risk, scope)
    return _assurance_result(controls, scope, selected)
