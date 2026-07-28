"""Exclusive run directories and fresh gate-detail snapshots."""

from __future__ import annotations

import json
import os
import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .errors import ConfigurationError, InfrastructureError
from .evidence_manifest import (
    MANIFEST_NAME,
    validate_run_id,
    write_evidence_json,
)

_MTIME_TOLERANCE_SECONDS = 1.0


def create_exclusive_run_dir(root: Path, run_id: str) -> Path:
    """Create a new run directory and reject identity reuse."""
    run_id = validate_run_id(run_id)
    parent = root / ".aqg" / "runs"
    try:
        parent.mkdir(parents=True, exist_ok=True)
        run_dir = parent / run_id
        run_dir.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise ConfigurationError(f"run directory already exists: .aqg/runs/{run_id}") from exc
    except OSError as exc:
        raise InfrastructureError(f"cannot create run directory: {exc}") from exc
    return run_dir


def require_writable_run_dir(root: Path, run_id: str) -> Path:
    """Resolve an existing profile-owned run that is not finalized."""
    run_id = validate_run_id(run_id)
    run_dir = root / ".aqg" / "runs" / run_id
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ConfigurationError(f"profile gate has no safe owning run: {run_id}")
    if (run_dir / MANIFEST_NAME).exists():
        raise ConfigurationError(f"run is finalized; refusing further writes: {run_id}")
    return run_dir


def _adapter_gate(command: str) -> str | None:
    try:
        arguments = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return None
    for index, token in enumerate(arguments[:-1]):
        if token == "adapter":
            return arguments[index + 1]
    return None


def _report_candidates(root: Path, clean_paths: Sequence[str]) -> list[Path]:
    candidates: set[Path] = set()
    resolved_root = root.resolve()
    for configured in clean_paths:
        base = root / configured
        try:
            base.resolve().relative_to(resolved_root)
        except ValueError as exc:
            raise ConfigurationError(f"gate clean path escapes repository: {configured}") from exc
        if base.is_file() and base.name == "report.json":
            candidates.add(base)
        elif base.is_dir():
            candidates.update(path for path in base.rglob("report.json") if path.is_file())
    return sorted(candidates)


def _usable_report(
    path: Path,
    gate_name: str,
    started_at: float,
    expected_exit: int,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        modified_at = path.stat().st_mtime
    except OSError as exc:
        return None, f"cannot read detailed report {path}: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"malformed detailed report {path}: {exc}"
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        return None, f"malformed detailed report {path}: expected schema_version 2 object"
    if modified_at < started_at - _MTIME_TOLERANCE_SECONDS:
        return None, f"stale detailed report {path}: it predates gate execution"
    if payload.get("gate") != gate_name:
        return None, f"detailed report {path} does not identify gate {gate_name!r}"
    if payload.get("exit_code") != expected_exit:
        return None, (
            f"detailed report {path} exit {payload.get('exit_code')!r} "
            f"does not match command exit {expected_exit}"
        )
    return payload, None


def snapshot_gate_details(
    root: Path,
    *,
    run_dir: Path,
    gate_name: str,
    command: str,
    clean_paths: Sequence[str],
    started_at: float,
    expected_exit: int,
) -> tuple[Path | None, str | None]:
    """Snapshot the one fresh, matching adapter report into its owning run."""
    adapter_gate = _adapter_gate(command)
    if adapter_gate is None:
        return None, None
    if adapter_gate != gate_name:
        return None, f"adapter command names {adapter_gate!r}, expected {gate_name!r}"
    valid: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in _report_candidates(root, clean_paths):
        payload, error = _usable_report(path, gate_name, started_at, expected_exit)
        if payload is not None:
            valid.append(payload)
        elif error:
            errors.append(error)
    if len(valid) != 1:
        reason = (
            f"expected one fresh detailed report for adapter gate {gate_name!r}; found {len(valid)}"
        )
        if errors:
            reason += f"; {errors[0]}"
        return None, reason
    destination = run_dir / "gates" / f"{gate_name}.details.json"
    write_evidence_json(destination, valid[0])
    return destination, None
