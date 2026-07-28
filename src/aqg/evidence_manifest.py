"""Content manifests for run-scoped evidence.

The manifest makes later changes detectable. It does not claim filesystem
append-only storage or protect against an attacker replacing both evidence and
its manifest; authoritative storage must supply that external trust boundary.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import ConfigurationError, InfrastructureError
from .util import utc_now

MANIFEST_NAME = "manifest.json"
MANIFEST_SCHEMA_VERSION = 1
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,126}$")
_SAFE_REL_RE = re.compile(r"^[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_run_id(run_id: str) -> str:
    """Return a conservative single-component run identifier."""
    if not isinstance(run_id, str) or run_id in {"", ".", ".."} or not _RUN_ID_RE.fullmatch(run_id):
        raise ConfigurationError(
            f"AQG_RUN_ID {run_id!r} must start alphanumeric and contain only "
            "letters, digits, dot, underscore, or hyphen"
        )
    return run_id


def _valid_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _exclusive_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise ConfigurationError(f"refusing to overwrite existing evidence: {path}") from exc
    except OSError as exc:
        raise InfrastructureError(f"cannot create evidence file {path}: {exc}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except OSError as exc:
        with contextlib.suppress(OSError):
            path.unlink()
        raise InfrastructureError(f"cannot write evidence file {path}: {exc}") from exc


def write_evidence_text(path: Path, content: str) -> None:
    """Write one evidence file without permitting replacement."""
    _exclusive_text(path, content)


def write_evidence_json(path: Path, payload: dict[str, Any]) -> None:
    """Write deterministic JSON evidence without permitting replacement."""
    _exclusive_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _safe_relative_file(run_dir: Path, path: Path) -> str:
    relative = path.relative_to(run_dir).as_posix()
    if relative == MANIFEST_NAME or not _SAFE_REL_RE.fullmatch(relative) or path.is_symlink():
        raise ConfigurationError(f"unsafe evidence path: {relative}")
    try:
        path.resolve(strict=True).relative_to(run_dir.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ConfigurationError(f"evidence path escapes run directory: {relative}") from exc
    return relative


def _evidence_files(run_dir: Path) -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    for path in sorted(run_dir.rglob("*")):
        if path.name == MANIFEST_NAME and path.parent == run_dir:
            continue
        if path.is_symlink() or path.is_file():
            files.append((_safe_relative_file(run_dir, path), path))
    return files


def write_run_manifest(run_dir: Path, run_id: str) -> Path:
    """Finalize a run with a deterministic inventory of its evidence bytes."""
    run_id = validate_run_id(run_id)
    run_dir = Path(run_dir)
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise ConfigurationError(f"run directory is missing or unsafe: {run_dir}")
    if run_dir.name != run_id:
        raise ConfigurationError("run manifest identity does not match its directory")
    manifest = run_dir / MANIFEST_NAME
    if manifest.exists():
        raise ConfigurationError(f"run is already finalized: {run_id}")
    entries: list[dict[str, Any]] = []
    try:
        for relative, path in _evidence_files(run_dir):
            data = path.read_bytes()
            entries.append(
                {
                    "path": relative,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                }
            )
    except OSError as exc:
        raise InfrastructureError(f"cannot read run evidence: {exc}") from exc
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_id": run_id,
        "completed_at": utc_now(),
        "files": entries,
    }
    _exclusive_text(manifest, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return manifest


def _empty_result() -> dict[str, Any]:
    return {
        "ok": False,
        "run_id": None,
        "errors": [],
        "modified": [],
        "deleted": [],
        "added": [],
        "unsafe_paths": [],
    }


def _manifest_entries(payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        result["errors"].append("malformed manifest: schema_version must be 1")
        return None
    run_id = payload.get("run_id")
    if not isinstance(run_id, str):
        result["errors"].append("malformed manifest: run_id must be a string")
        return None
    try:
        validate_run_id(run_id)
    except ConfigurationError as exc:
        result["errors"].append(f"malformed manifest: {exc}")
        return None
    result["run_id"] = run_id
    if not _valid_timestamp(payload.get("completed_at")):
        result["errors"].append(
            "malformed manifest: completed_at must be a timezone-aware timestamp"
        )
        return None
    files = payload.get("files")
    if not isinstance(files, list):
        result["errors"].append("malformed manifest: files must be an array")
        return None
    expected: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            result["errors"].append(f"malformed manifest: files[{index}] must be an object")
            return None
        relative = entry.get("path")
        digest = entry.get("sha256")
        size = entry.get("bytes")
        if not isinstance(relative, str):
            result["errors"].append(f"malformed manifest entry: {relative!r}")
            return None
        if not _SAFE_REL_RE.fullmatch(relative) or relative == MANIFEST_NAME:
            result["unsafe_paths"].append(str(relative))
            continue
        if (
            relative in expected
            or not isinstance(digest, str)
            or not _SHA256_RE.fullmatch(digest)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
        ):
            result["errors"].append(f"malformed manifest entry: {relative!r}")
            return None
        expected[relative] = {"sha256": digest, "bytes": size}
    if result["unsafe_paths"]:
        result["errors"].append("unsafe manifest paths are present")
    return expected


def verify_run_manifest(run_dir: Path) -> dict[str, Any]:
    """Verify a finalized run and classify byte changes and path changes."""
    result = _empty_result()
    run_dir = Path(run_dir)
    manifest = run_dir / MANIFEST_NAME
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except FileNotFoundError:
        result["errors"].append("missing manifest.json")
        return result
    except (OSError, json.JSONDecodeError) as exc:
        result["errors"].append(f"malformed manifest: {exc}")
        return result
    if not isinstance(payload, dict):
        result["errors"].append("malformed manifest: expected an object")
        return result
    expected = _manifest_entries(payload, result)
    if expected is None or result["run_id"] != run_dir.name:
        if expected is not None:
            result["errors"].append("manifest run_id does not match its directory")
        return result
    try:
        actual = dict(_evidence_files(run_dir))
        for relative, metadata in expected.items():
            path = actual.get(relative)
            if path is None:
                result["deleted"].append(relative)
                continue
            data = path.read_bytes()
            if (
                hashlib.sha256(data).hexdigest() != metadata["sha256"]
                or len(data) != metadata["bytes"]
            ):
                result["modified"].append(relative)
        result["added"] = sorted(set(actual) - set(expected))
    except (ConfigurationError, OSError) as exc:
        result["errors"].append(str(exc))
        return result
    for category in ("modified", "deleted", "added"):
        if result[category]:
            result["errors"].append(f"{category} evidence: {', '.join(result[category])}")
    result["ok"] = not result["errors"]
    return result
