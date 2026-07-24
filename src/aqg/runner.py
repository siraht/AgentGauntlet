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
from .errors import ConfigurationError
from .policy import safe_remove, validate_policy
from .project import load_project
from .util import (
    change_fingerprint,
    control_fingerprint,
    git_revision,
    human_duration,
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


def _run_dir(root: Path, run_id: str) -> Path:
    path = root / ".aqg" / "runs" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_gate(
    root: Path, policy: dict[str, Any], gate_name: str, run_id: str, profile_name: str | None = None
) -> tuple[int, dict[str, Any]]:
    gate = policy.get("gates", {}).get(gate_name)
    if not isinstance(gate, dict):
        raise ConfigurationError(f"unknown gate {gate_name!r}")
    command = gate.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ConfigurationError(f"gate {gate_name!r} has no command")
    for path in gate.get("clean_paths", []):
        safe_remove(root, str(path))
    timeout = int(gate.get("timeout_seconds", 300))
    started = time.monotonic()
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
        **_provenance(root),
        "stdout": stdout,
        "stderr": stderr,
    }
    gate_dir = _run_dir(root, run_id) / "gates"
    write_json(gate_dir / f"{gate_name}.json", evidence)
    (gate_dir / f"{gate_name}.log").write_text(
        f"$ {command}\n\n--- stdout ---\n{stdout}\n\n--- stderr ---\n{stderr}\n",
        encoding="utf-8",
    )
    return code, evidence


def run_profile(
    root: Path,
    policy: dict[str, Any],
    profile_name: str,
    *,
    keep_going: bool = False,
    quiet: bool = False,
) -> tuple[int, dict[str, Any]]:
    errors = validate_policy(policy)
    if errors:
        raise ConfigurationError("; ".join(errors))
    profile = policy.get("profiles", {}).get(profile_name)
    if not isinstance(profile, dict):
        raise ConfigurationError(f"unknown execution profile {profile_name!r}")
    run_id = (
        os.environ.get("AQG_RUN_ID")
        or f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    )
    run_dir = _run_dir(root, run_id)
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
        code, evidence = run_gate(root, policy, str(gate_name), run_id, profile_name)
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
        write_json(run_dir / "gates" / "workspace_integrity.json", integrity)
        final = max(final, QUALITY_FAILURE)
        if not quiet:
            print(
                "  ✗ workspace_integrity [quality_failure] · a checker modified the review surface"
            )

    summary = {
        "schema_version": "2",
        "run_id": run_id,
        "profile": profile_name,
        "status": STATUS_NAMES[final],
        "exit_code": final,
        "started_at": utc_now(),
        "duration_ms": int((time.monotonic() - started) * 1000),
        **end_provenance,
        "workspace_mutated": workspace_mutated,
        "start_change_fingerprint": start_provenance["change_fingerprint"],
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
    write_json(run_dir / "summary.json", summary)
    write_json(root / ".aqg" / "latest.json", {"run_id": run_id, "path": str(run_dir), **summary})
    if not quiet:
        print(
            f"AQG {profile_name}: {STATUS_NAMES[final]} in {human_duration(int(str(summary['duration_ms'])))}"
        )
    return final, summary


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
