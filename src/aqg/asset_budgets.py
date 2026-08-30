"""Deterministic, fail-closed budgets for built JavaScript and CSS artifacts."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import zlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import ConfigurationError, InfrastructureError

_KINDS = {".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".css": "css"}
_METRICS = ("file_raw_bytes", "file_gzip_bytes", "total_raw_bytes", "total_gzip_bytes")
_LIMIT_KEYS = tuple(f"max_{kind}_{metric}" for kind in ("javascript", "css") for metric in _METRICS)
_DEFINITION = "aqg-built-asset-budget-v1"


def measure_asset_budgets(
    repository_root: Path,
    *,
    build_roots: Sequence[str | Path],
    limits: Mapping[str, int],
    warning_ratio: float = 0.8,
    fresh_after_ns: int | None = None,
) -> dict[str, Any]:
    """Measure explicit build roots and return complete, fingerprinted evidence."""
    root = _safe_repository_root(repository_root)
    normalized_limits = _validate_limits(limits)
    ratio = _validate_warning_ratio(warning_ratio)
    freshness = _validate_freshness(fresh_after_ns)
    roots = _resolve_build_roots(root, build_roots)
    artifacts = _measure_artifacts(root, roots, freshness)
    totals = _totals(artifacts, normalized_limits, ratio)
    findings = _findings(artifacts, totals)
    core = {
        "schema_version": 1,
        "metric_definition": _DEFINITION,
        "compression": {
            "algorithm": "gzip",
            "compresslevel": 9,
            "mtime": 0,
            "zlib_version": zlib.ZLIB_VERSION,
            "zlib_runtime_version": zlib.ZLIB_RUNTIME_VERSION,
        },
        "build_roots": [path.relative_to(root).as_posix() for path in roots],
        "fresh_after_ns": freshness,
        "warning_ratio": ratio,
        "limits": normalized_limits,
        "artifacts": artifacts,
        "totals": totals,
        "findings": findings,
        "summary": _summary(artifacts, findings),
    }
    return {**core, "evidence_sha256": _fingerprint(core)}


def _safe_repository_root(path: Path) -> Path:
    try:
        root = path.resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError(f"repository root is unavailable: {path}: {exc}") from exc
    if not root.is_dir():
        raise ConfigurationError(f"repository root is not a directory: {path}")
    return root


def _validate_limits(limits: Mapping[str, int]) -> dict[str, int]:
    if not isinstance(limits, Mapping):
        raise ConfigurationError("asset budgets must be a mapping")
    missing = sorted(set(_LIMIT_KEYS) - set(limits))
    unknown = sorted(set(limits) - set(_LIMIT_KEYS))
    if missing or unknown:
        parts = []
        if missing:
            parts.append(f"missing limits: {', '.join(missing)}")
        if unknown:
            parts.append(f"unknown limits: {', '.join(unknown)}")
        raise ConfigurationError("; ".join(parts))
    normalized: dict[str, int] = {}
    for key in _LIMIT_KEYS:
        value = limits[key]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigurationError(f"{key} must be a positive integer byte count")
        normalized[key] = value
    return normalized


def _validate_warning_ratio(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError("asset budget warning_ratio must be a number")
    ratio = float(value)
    if not math.isfinite(ratio) or not 0 < ratio < 1:
        raise ConfigurationError(
            "asset budget warning_ratio must be greater than 0 and less than 1"
        )
    return ratio


def _validate_freshness(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ConfigurationError("fresh_after_ns must be a non-negative integer timestamp")
    return value


def _resolve_build_roots(root: Path, configured: Sequence[str | Path]) -> list[Path]:
    if isinstance(configured, (str, bytes)) or not isinstance(configured, Sequence):
        raise ConfigurationError("build roots must be a non-empty sequence of paths")
    if not configured:
        raise ConfigurationError("at least one explicit build root is required")
    if any(not isinstance(item, (str, Path)) for item in configured):
        raise ConfigurationError("every build root must be a string or Path")
    resolved = [_resolve_build_root(root, item) for item in configured]
    ordered = sorted(resolved, key=lambda path: path.relative_to(root).as_posix())
    if len(set(ordered)) != len(ordered):
        raise ConfigurationError("build roots must be unique")
    for index, current in enumerate(ordered):
        for other in ordered[index + 1 :]:
            if other.is_relative_to(current):
                raise ConfigurationError("build roots must not overlap")
    return ordered


def _resolve_build_root(root: Path, configured: str | Path) -> Path:
    value = Path(configured)
    candidate = value if value.is_absolute() else root / value
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ConfigurationError(f"build root escapes repository: {configured}") from exc
    _reject_symlink_components(root, candidate)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except ValueError as exc:
        raise ConfigurationError(f"build root escapes repository: {configured}") from exc
    except OSError as exc:
        raise InfrastructureError(f"build root is unavailable: {configured}: {exc}") from exc
    if not resolved.is_dir():
        raise InfrastructureError(f"build root is not a directory: {configured}")
    return resolved


def _reject_symlink_components(root: Path, candidate: Path) -> None:
    try:
        relative = candidate.absolute().relative_to(root)
    except ValueError as exc:
        raise ConfigurationError(f"build root escapes repository: {candidate}") from exc
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ConfigurationError(f"build root traverses symlink: {cursor}")


def _measure_artifacts(
    root: Path, roots: Sequence[Path], fresh_after_ns: int | None
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for build_root in roots:
        for path in _walk_files(build_root):
            kind = _KINDS.get(path.suffix.lower())
            if kind:
                artifacts.append(_measure_file(root, build_root, path, kind, fresh_after_ns))
    if not artifacts:
        configured = ", ".join(path.relative_to(root).as_posix() for path in roots)
        raise InfrastructureError(
            f"build roots contain no JavaScript or CSS artifacts: {configured}"
        )
    return sorted(artifacts, key=lambda item: item["path"])


def _walk_files(build_root: Path) -> list[Path]:
    files: list[Path] = []

    def fail(error: OSError) -> None:
        raise InfrastructureError(f"cannot traverse build root {build_root}: {error}")

    for directory, names, filenames in os.walk(
        build_root, topdown=True, onerror=fail, followlinks=False
    ):
        base = Path(directory)
        for name in sorted(names):
            if (base / name).is_symlink():
                raise ConfigurationError(f"build root contains symlink directory: {base / name}")
        for name in sorted(filenames):
            path = base / name
            if path.is_symlink():
                raise ConfigurationError(f"build root contains symlink file: {path}")
            if not path.is_file():
                raise InfrastructureError(f"build root contains unreadable non-file entry: {path}")
            files.append(path)
    return files


def _measure_file(
    root: Path,
    build_root: Path,
    path: Path,
    kind: str,
    fresh_after_ns: int | None,
) -> dict[str, Any]:
    try:
        before = path.stat()
        content = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise InfrastructureError(f"cannot read built artifact {path}: {exc}") from exc
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    observed = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity != observed or len(content) != after.st_size:
        raise InfrastructureError(f"built artifact changed while it was measured: {path}")
    if fresh_after_ns is not None and after.st_mtime_ns < fresh_after_ns:
        raise InfrastructureError(f"built artifact is stale: {path}")
    return {
        "path": path.relative_to(root).as_posix(),
        "build_root": build_root.relative_to(root).as_posix(),
        "kind": kind,
        "raw_bytes": len(content),
        "gzip_bytes": len(gzip.compress(content, compresslevel=9, mtime=0)),
        "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
        "mtime_ns": after.st_mtime_ns,
    }


def _totals(
    artifacts: Sequence[dict[str, Any]], limits: Mapping[str, int], warning_ratio: float
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for kind in ("javascript", "css"):
        selected = [item for item in artifacts if item["kind"] == kind]
        result[kind] = {
            "artifact_count": len(selected),
            "raw_bytes": sum(item["raw_bytes"] for item in selected),
            "gzip_bytes": sum(item["gzip_bytes"] for item in selected),
        }
        _add_budget_states(selected, result[kind], kind, limits, warning_ratio)
    return result


def _add_budget_states(
    artifacts: Sequence[dict[str, Any]],
    total: dict[str, Any],
    kind: str,
    limits: Mapping[str, int],
    warning_ratio: float,
) -> None:
    for artifact in artifacts:
        artifact["budgets"] = {
            metric: _budget_state(
                artifact[metric], limits[f"max_{kind}_file_{metric}"], warning_ratio
            )
            for metric in ("raw_bytes", "gzip_bytes")
        }
    total["budgets"] = {
        metric: _budget_state(total[metric], limits[f"max_{kind}_total_{metric}"], warning_ratio)
        for metric in ("raw_bytes", "gzip_bytes")
    }


def _budget_state(observed: int, limit: int, warning_ratio: float) -> dict[str, Any]:
    warning_at = math.ceil(limit * warning_ratio)
    status = "failure" if observed > limit else "warning" if observed >= warning_at else "pass"
    return {
        "observed": observed,
        "limit": limit,
        "remaining": limit - observed,
        "warning_at": warning_at,
        "utilization": observed / limit,
        "status": status,
    }


def _findings(
    artifacts: Sequence[dict[str, Any]], totals: Mapping[str, Any]
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for artifact in artifacts:
        for metric, state in artifact["budgets"].items():
            if state["status"] != "pass":
                findings.append(
                    _finding(artifact["path"], artifact["kind"], f"file_{metric}", state)
                )
    for kind in ("javascript", "css"):
        for metric, state in totals[kind]["budgets"].items():
            if state["status"] != "pass":
                findings.append(_finding(f"{kind}:aggregate", kind, f"total_{metric}", state))
    return sorted(findings, key=lambda item: (item["status"], item["scope"], item["metric"]))


def _finding(scope: str, kind: str, metric: str, state: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "code": "asset-budget-exceeded"
        if state["status"] == "failure"
        else "asset-budget-headroom",
        "status": state["status"],
        "scope": scope,
        "kind": kind,
        "metric": metric,
        "observed": state["observed"],
        "limit": state["limit"],
        "remaining": state["remaining"],
    }


def _summary(
    artifacts: Sequence[dict[str, Any]], findings: Sequence[dict[str, Any]]
) -> dict[str, int | str]:
    failures = sum(item["status"] == "failure" for item in findings)
    warnings = sum(item["status"] == "warning" for item in findings)
    return {
        "status": "failure" if failures else "warning" if warnings else "pass",
        "artifact_count": len(artifacts),
        "failure_count": failures,
        "warning_count": warnings,
    }


def _fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
