"""Manifested, externally anchored evidence for a base-controlled grader."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .evidence_manifest import verify_run_manifest, write_evidence_json, write_run_manifest
from .util import (
    change_fingerprint,
    control_fingerprint,
    git_revision,
    read_json,
    sha256_file,
)

TRUSTED_EVIDENCE_SCHEMA_VERSION = 1
TRUSTED_EVIDENCE_KIND = "aqg-trusted-verifier-evidence"
TRUSTED_EVIDENCE_FILE = "verifier.json"
TRUSTED_EVIDENCE_DIRECTORY_ENV = "AQG_TRUSTED_EVIDENCE_DIR"
TRUSTED_EVIDENCE_MANIFEST_ENV = "AQG_TRUSTED_EVIDENCE_MANIFEST_SHA256"
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_TRUSTED_PATH_ENVS = {
    "launcher": "AQG_TRUSTED_LAUNCHER",
    "policy": "AQG_TRUSTED_POLICY_PATH",
    "project": "AQG_TRUSTED_PROJECT_PATH",
    "root": "AQG_TRUSTED_TOOLCHAIN_ROOT",
}


def _digest(path: Path) -> str:
    return f"sha256:{sha256_file(path)}"


def _scope(root: Path, base_revision: str) -> dict[str, str]:
    return {
        "revision": git_revision(root),
        "base_revision": base_revision,
        "change_fingerprint": change_fingerprint(root, base_revision),
        "control_fingerprint": control_fingerprint(root),
    }


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _trusted_paths() -> tuple[dict[str, Path], list[str]]:
    paths: dict[str, Path] = {}
    errors: list[str] = []
    for name, variable in _TRUSTED_PATH_ENVS.items():
        raw = os.environ.get(variable, "")
        path = Path(raw)
        if not raw:
            errors.append(f"missing {variable}")
        elif not path.is_absolute():
            errors.append(f"{variable} must be absolute")
        elif not path.exists():
            errors.append(f"{variable} does not exist")
        else:
            paths[name] = path.resolve()
    if set(paths) == set(_TRUSTED_PATH_ENVS):
        root = paths["root"]
        for name in ("launcher", "policy", "project"):
            if not _inside(paths[name], root):
                errors.append(f"trusted {name} must be inside AQG_TRUSTED_TOOLCHAIN_ROOT")
    return paths, errors


def _grader_identity(paths: Mapping[str, Path]) -> dict[str, str]:
    return {
        "launcher_sha256": _digest(paths["launcher"]),
        "policy_sha256": _digest(paths["policy"]),
        "project_sha256": _digest(paths["project"]),
        "control_fingerprint": control_fingerprint(paths["root"]),
    }


def write_trusted_verifier_evidence(
    subject_root: Path,
    evidence_dir: Path,
    *,
    base_revision: str,
    trusted_root: Path,
    trusted_launcher: Path,
    trusted_policy: Path,
    trusted_project: Path,
) -> dict[str, Any]:
    """Finalize exact-candidate grader evidence for an external digest anchor."""
    subject = subject_root.resolve(strict=True)
    destination = evidence_dir.resolve()
    if _inside(destination, subject):
        raise ConfigurationError("trusted verifier evidence must be outside the candidate root")
    destination.mkdir(parents=True, exist_ok=False)
    paths = {
        "root": trusted_root.resolve(strict=True),
        "launcher": trusted_launcher.resolve(strict=True),
        "policy": trusted_policy.resolve(strict=True),
        "project": trusted_project.resolve(strict=True),
    }
    payload: dict[str, Any] = {
        "schema_version": TRUSTED_EVIDENCE_SCHEMA_VERSION,
        "kind": TRUSTED_EVIDENCE_KIND,
        "status": "bound",
        "scope": _scope(subject, base_revision),
        "grader": _grader_identity(paths),
    }
    write_evidence_json(destination / TRUSTED_EVIDENCE_FILE, payload)
    manifest = write_run_manifest(destination, destination.name)
    return {
        "evidence_dir": str(destination),
        "manifest_sha256": _digest(manifest),
        "evidence": payload,
    }


def _expected_scope(scope: Mapping[str, str]) -> dict[str, str]:
    return {
        "revision": str(scope.get("revision", "")),
        "base_revision": str(scope.get("base_revision") or scope.get("base_ref") or ""),
        "change_fingerprint": str(scope.get("change_fingerprint", "")),
        "control_fingerprint": str(scope.get("control_fingerprint", "")),
    }


def _payload_errors(
    payload: Any, expected_scope: Mapping[str, str], grader: Mapping[str, str]
) -> list[str]:
    if not isinstance(payload, dict):
        return ["trusted verifier evidence must be an object"]
    errors: list[str] = []
    if set(payload) != {"schema_version", "kind", "status", "scope", "grader"}:
        errors.append("trusted verifier evidence fields are incomplete or unknown")
    if payload.get("schema_version") != TRUSTED_EVIDENCE_SCHEMA_VERSION:
        errors.append("trusted verifier evidence schema_version must be 1")
    if payload.get("kind") != TRUSTED_EVIDENCE_KIND or payload.get("status") != "bound":
        errors.append("trusted verifier evidence kind or status is invalid")
    if payload.get("scope") != dict(expected_scope):
        errors.append("trusted verifier evidence does not match the exact candidate scope")
    if payload.get("grader") != dict(grader):
        errors.append("trusted verifier evidence does not match the current trusted grader")
    return errors


def _evidence_location(root: Path) -> tuple[Path | None, str, list[str]]:
    raw_dir = os.environ.get(TRUSTED_EVIDENCE_DIRECTORY_ENV, "")
    digest = os.environ.get(TRUSTED_EVIDENCE_MANIFEST_ENV, "")
    errors: list[str] = []
    if not raw_dir:
        errors.append(f"missing {TRUSTED_EVIDENCE_DIRECTORY_ENV}")
    if not _SHA256.fullmatch(digest):
        errors.append(f"{TRUSTED_EVIDENCE_MANIFEST_ENV} must be a sha256 fingerprint")
    if not raw_dir:
        return None, digest, errors
    evidence_dir = Path(raw_dir)
    if not evidence_dir.is_absolute():
        errors.append(f"{TRUSTED_EVIDENCE_DIRECTORY_ENV} must be absolute")
    else:
        evidence_dir = evidence_dir.resolve()
        if _inside(evidence_dir, root.resolve()):
            errors.append("trusted verifier evidence must be outside the candidate root")
    return evidence_dir, digest, errors


def _manifest_errors(evidence_dir: Path, digest: str) -> tuple[dict[str, Any], list[str]]:
    manifest = verify_run_manifest(evidence_dir)
    errors = [f"trusted verifier manifest: {error}" for error in manifest["errors"]]
    manifest_path = evidence_dir / "manifest.json"
    if manifest_path.is_file() and _digest(manifest_path) != digest:
        errors.append("trusted verifier manifest does not match its external digest anchor")
    return manifest, errors


def _read_payload(evidence_dir: Path) -> tuple[Any, list[str]]:
    try:
        return read_json(evidence_dir / TRUSTED_EVIDENCE_FILE), []
    except ConfigurationError as exc:
        return None, [str(exc)]


def _unusable(errors: list[str]) -> dict[str, Any]:
    return {
        "status": "unusable",
        "method": "base-controlled-trusted-grader",
        "errors": errors,
    }


def verify_trusted_verifier_evidence(root: Path, scope: Mapping[str, str]) -> dict[str, Any]:
    """Require manifested exact-candidate evidence plus an external manifest digest."""
    paths, errors = _trusted_paths()
    evidence_dir, digest, location_errors = _evidence_location(root)
    errors.extend(location_errors)
    if errors or evidence_dir is None:
        return _unusable(errors)
    manifest, manifest_errors = _manifest_errors(evidence_dir, digest)
    payload, payload_errors = _read_payload(evidence_dir)
    errors.extend(manifest_errors + payload_errors)
    errors.extend(_payload_errors(payload, _expected_scope(scope), _grader_identity(paths)))
    return {
        "status": "works" if not errors else "unusable",
        "method": "base-controlled-trusted-grader",
        "evidence_dir": str(evidence_dir),
        "manifest_sha256": digest,
        "manifest": manifest,
        "evidence": payload,
        "errors": errors,
    }
