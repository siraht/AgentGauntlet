"""Deterministic profile runner and normalized evidence writer."""

from __future__ import annotations

import datetime as dt
import json
import os
import shlex
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from .constants import (
    CONFIGURATION_ERROR,
    INFRASTRUCTURE_ERROR,
    PASS,
    QUALITY_FAILURE,
    STATUS_NAMES,
)
from .debt_store import load_current_debt_baseline
from .errors import ConfigurationError
from .evidence import (
    create_exclusive_run_dir,
    require_writable_run_dir,
    snapshot_gate_details,
)
from .evidence_manifest import (
    validate_run_id,
    write_evidence_json,
    write_evidence_text,
    write_run_manifest,
)
from .policy import safe_remove, validate_policy
from .project import load_project
from .retrospective import build_retrospective, ratchet_exit_code
from .util import (
    change_fingerprint,
    control_fingerprint,
    git_revision,
    human_duration,
    read_json,
    utc_now,
    write_json,
)


def _classify(code: int, quality_codes: list[int]) -> int:
    if code == 0:
        return PASS
    if code in quality_codes:
        return QUALITY_FAILURE
    if code == CONFIGURATION_ERROR:
        return CONFIGURATION_ERROR
    return INFRASTRUCTURE_ERROR


def _base_ref(root: Path) -> str:
    override = os.environ.get("AQG_DIFF_BASE")
    if override:
        return override
    try:
        return str(load_project(root).get("enforcement", {}).get("base_ref", "HEAD"))
    except Exception:
        return "HEAD"


def _provenance(root: Path) -> dict[str, str]:
    base = _base_ref(root)
    return {
        "revision": git_revision(root),
        "base_ref": base,
        "change_fingerprint": change_fingerprint(root, base),
        "control_fingerprint": control_fingerprint(root),
    }


def _merge_settings(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = {
        key: value.copy() if isinstance(value, dict) else value for key, value in base.items()
    }
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_settings(merged[key], value)
        else:
            merged[key] = value
    return merged


def _retrospective_inputs(
    root: Path, run_dir: Path, project: dict[str, Any], profile_name: str
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any] | None,
    dict[str, Any] | None,
    str | None,
]:
    details: dict[str, Any] = {}
    for path in sorted((run_dir / "gates").glob("*.details.json")):
        payload = read_json(path)
        if isinstance(payload, dict) and isinstance(payload.get("gate"), str):
            details[str(payload["gate"])] = payload
    thresholds = _merge_settings(
        project.get("thresholds", {}),
        project.get("profile_thresholds", {}).get(profile_name, {}),
    )
    traceability = details.get("test_integrity", {}).get("traceability")
    enforcement = project.get("enforcement", {})
    baseline_path = root / str(enforcement.get("debt_baseline", "quality/baselines/debt.json"))
    baseline: dict[str, Any] | None = None
    baseline_error: str | None = None
    if baseline_path.is_file():
        try:
            baseline = load_current_debt_baseline(root, baseline_path)
        except ConfigurationError as exc:
            baseline_error = str(exc)
    return details, thresholds, traceability, baseline, baseline_error


def run_gate(
    root: Path,
    policy: dict[str, Any],
    gate_name: str,
    run_id: str,
    profile_name: str | None = None,
    *,
    owned_run: bool = False,
    provenance: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    gate = policy.get("gates", {}).get(gate_name)
    if not isinstance(gate, dict):
        raise ConfigurationError(f"unknown gate {gate_name!r}")
    command = gate.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ConfigurationError(f"gate {gate_name!r} has no command")
    run_id = validate_run_id(run_id)
    if owned_run:
        run_dir = require_writable_run_dir(root, run_id)
    else:
        run_dir = create_exclusive_run_dir(root, run_id)

    clean_paths = [str(path) for path in gate.get("clean_paths", [])]
    for path in clean_paths:
        safe_remove(root, path)
    timeout = int(gate.get("timeout_seconds", 300))
    started = time.monotonic()
    started_at = time.time()
    env = os.environ.copy()
    env.update({"AQG_RUN_ID": run_id, "AQG_GATE": gate_name, "AQG_ROOT": str(root)})
    if profile_name:
        env["AQG_PROFILE"] = profile_name
    try:
        argv = shlex.split(command, posix=os.name != "nt")
        if not argv:
            raise ConfigurationError(f"gate {gate_name!r} has an empty command")
        completed = subprocess.run(
            argv,
            cwd=root,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        code = _classify(
            completed.returncode, [int(v) for v in gate.get("quality_failure_exit_codes", [1])]
        )
        stdout = completed.stdout
        stderr = completed.stderr
        raw_code = completed.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        code = INFRASTRUCTURE_ERROR
        raw_code = INFRASTRUCTURE_ERROR
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
        stderr = (stderr + f"\nGate timed out after {timeout}s").strip()
        timed_out = True
    duration = int((time.monotonic() - started) * 1000)

    details_path, detail_error = snapshot_gate_details(
        root,
        run_dir=run_dir,
        gate_name=gate_name,
        command=command,
        clean_paths=clean_paths,
        started_at=started_at,
        expected_exit=raw_code,
    )
    if detail_error:
        code = INFRASTRUCTURE_ERROR
        stderr = (stderr + "\n" + detail_error).strip() if stderr else detail_error

    evidence = {
        "schema_version": "2",
        "run_id": run_id,
        "gate": gate_name,
        "profile": profile_name,
        "status": STATUS_NAMES[code],
        "exit_code": code,
        "raw_exit_code": raw_code,
        "command": command,
        "started_at": utc_now(),
        "duration_ms": duration,
        "timed_out": timed_out,
        **(provenance or _provenance(root)),
        "stdout": stdout,
        "stderr": stderr,
    }
    if details_path is not None:
        evidence["details_path"] = str(details_path.relative_to(run_dir).as_posix())
    if detail_error:
        evidence["detail_error"] = detail_error
    gate_dir = run_dir / "gates"
    write_evidence_json(gate_dir / f"{gate_name}.json", evidence)
    write_evidence_text(
        gate_dir / f"{gate_name}.log",
        f"$ {command}\n\n--- stdout ---\n{stdout}\n\n--- stderr ---\n{stderr}\n",
    )
    if not owned_run:
        write_run_manifest(run_dir, run_id)
    return code, evidence


def run_profile(
    root: Path,
    policy: dict[str, Any],
    profile_name: str,
    *,
    keep_going: bool = False,
    quiet: bool = False,
    shadow: bool = False,
) -> tuple[int, dict[str, Any]]:
    errors = validate_policy(policy)
    if errors:
        raise ConfigurationError("; ".join(errors))
    profile = policy.get("profiles", {}).get(profile_name)
    if not isinstance(profile, dict):
        raise ConfigurationError(f"unknown execution profile {profile_name!r}")
    raw_run_id = (
        os.environ.get("AQG_RUN_ID")
        or f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    )
    run_id = validate_run_id(raw_run_id)
    run_dir = create_exclusive_run_dir(root, run_id)
    started = time.monotonic()
    start_provenance = _provenance(root)
    results: list[dict[str, Any]] = []
    final = PASS
    if not quiet:
        print(f"AQG {profile_name} · run {run_id}")
    for gate_name in profile.get("gates", []):
        gate_started = time.monotonic()
        if not quiet:
            print(f"  → {gate_name}", flush=True)
        code, evidence = run_gate(
            root,
            policy,
            str(gate_name),
            run_id,
            profile_name,
            owned_run=True,
            provenance=start_provenance,
        )
        results.append(evidence)
        if code > final:
            final = code
        if not quiet:
            marker = "✓" if code == PASS else "✗"
            detail = evidence.get("stderr", "").strip().splitlines()
            tail = f" · {detail[-1][:140]}" if code != PASS and detail else ""
            print(
                f"  {marker} {gate_name} [{STATUS_NAMES[code]}] {human_duration(int((time.monotonic() - gate_started) * 1000))}{tail}"
            )
        if code != PASS and not keep_going:
            break
    end_provenance = _provenance(root)
    workspace_mutated = (
        start_provenance["change_fingerprint"] != end_provenance["change_fingerprint"]
    )
    if workspace_mutated:
        integrity = {
            "schema_version": "2",
            "run_id": run_id,
            "gate": "workspace_integrity",
            "status": STATUS_NAMES[QUALITY_FAILURE],
            "exit_code": QUALITY_FAILURE,
            "raw_exit_code": QUALITY_FAILURE,
            "command": "AQG internal workspace fingerprint comparison",
            "started_at": utc_now(),
            "duration_ms": 0,
            "timed_out": False,
            **end_provenance,
            "stdout": "",
            "stderr": "A required gate changed the tracked or untracked review surface. Tests and checkers must be observational unless an explicit update command is used.",
            "before_change_fingerprint": start_provenance["change_fingerprint"],
        }
        results.append(integrity)
        write_evidence_json(run_dir / "gates" / "workspace_integrity.json", integrity)
        final = max(final, QUALITY_FAILURE)
        if not quiet:
            print(
                "  ✗ workspace_integrity [quality_failure] · a checker modified the review surface"
            )

    measured_gate_exit = final
    project = load_project(root)
    details, thresholds, traceability, baseline, baseline_error = _retrospective_inputs(
        root, run_dir, project, profile_name
    )
    retrospective = build_retrospective(
        results,
        details,
        thresholds,
        traceability=traceability,
        baseline=baseline,
        baseline_error=baseline_error,
    )
    write_evidence_json(run_dir / "retrospective.json", retrospective)
    if baseline_error:
        final = max(final, CONFIGURATION_ERROR)
    elif baseline is not None:
        final = ratchet_exit_code(retrospective)
    command_exit = PASS if shadow and final == QUALITY_FAILURE else final
    summary = {
        "schema_version": "2",
        "run_id": run_id,
        "profile": profile_name,
        "mode": "shadow" if shadow else "enforce",
        "status": STATUS_NAMES[final],
        "exit_code": command_exit,
        "observed_exit_code": final,
        "measured_gate_exit_code": measured_gate_exit,
        "command_status": STATUS_NAMES[command_exit],
        "started_at": utc_now(),
        "duration_ms": int((time.monotonic() - started) * 1000),
        **end_provenance,
        "workspace_mutated": workspace_mutated,
        "start_change_fingerprint": start_provenance["change_fingerprint"],
        "retrospective": {
            "certification": retrospective["certification"],
            "counts": retrospective["counts"],
        },
        "gates": [
            {
                "name": item["gate"],
                "status": item["status"],
                "exit_code": item["exit_code"],
                "duration_ms": item["duration_ms"],
            }
            for item in results
        ],
    }
    write_evidence_json(run_dir / "summary.json", summary)
    write_run_manifest(run_dir, run_id)
    write_json(root / ".aqg" / "latest.json", {"run_id": run_id, "path": str(run_dir), **summary})
    if not quiet:
        print(
            f"AQG {profile_name}: {STATUS_NAMES[final]}"
            + (
                " (shadow observations; non-blocking)"
                if shadow and final == QUALITY_FAILURE
                else ""
            )
            + f" in {human_duration(int(str(summary['duration_ms'])))}"
        )
    return command_exit, summary


def list_runs(root: Path, limit: int = 50) -> list[dict[str, Any]]:
    runs_dir = root / ".aqg" / "runs"
    if not runs_dir.exists():
        return []
    summaries: list[dict[str, Any]] = []
    for path in sorted(runs_dir.glob("*/summary.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payload["path"] = str(path.parent)
        summaries.append(payload)
        if len(summaries) >= limit:
            break
    return summaries
