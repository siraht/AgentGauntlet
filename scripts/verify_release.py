#!/usr/bin/env python3
"""Verify an AQG release directory without trusting its filenames or manifest claims."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

EXPECTED_PORTABLE_FILES = {
    "LICENSE",
    "README.md",
    "aqg-runtime.cdx.json",
    "aqg.pyz",
    "aqg.pyz.sha256",
    "install-aqg.sh",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(raw: str) -> str:
    name = PurePosixPath(raw)
    if name.is_absolute() or not name.parts or ".." in name.parts or name.as_posix() != raw:
        raise ValueError(f"unsafe artifact name {raw!r}")
    return raw


def _checksums(root: Path) -> tuple[dict[str, str], list[str]]:
    path = root / "SHA256SUMS"
    errors: list[str] = []
    expected: dict[str, str] = {}
    if not path.is_file():
        return {}, ["missing SHA256SUMS"]
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        digest, separator, raw = line.partition("  ")
        try:
            name = _safe_name(raw)
        except ValueError as exc:
            errors.append(f"SHA256SUMS line {number}: {exc}")
            continue
        if (
            not separator
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            errors.append(f"SHA256SUMS line {number} is malformed")
        elif name in expected:
            errors.append(f"SHA256SUMS repeats {name}")
        else:
            expected[name] = digest
    return expected, errors


def _checksum_errors(root: Path, expected: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for name, digest in expected.items():
        path = root / name
        if not path.is_file() or path.is_symlink():
            errors.append(f"missing or unsafe checksummed artifact {name}")
        elif _sha256(path) != digest:
            errors.append(f"checksum mismatch for {name}")
    return errors


def _inventory_errors(root: Path, expected: dict[str, str]) -> list[str]:
    portable = [name for name in expected if name.endswith("-portable.zip")]
    allowed = {
        "SHA256SUMS",
        "aqg.pyz.sha256",
        *(f"{name}.sha256" for name in portable),
        *expected,
    }
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        return [f"cannot inspect release inventory: {exc}"]
    actual = {path.name for path in entries}
    errors = _inventory_difference_errors(actual, allowed)
    errors.extend(_unsafe_entry_errors(entries))
    return errors


def _inventory_difference_errors(actual: set[str], allowed: set[str]) -> list[str]:
    if actual != allowed:
        return [
            "release directory inventory differs: "
            f"missing={sorted(allowed - actual)}, unexpected={sorted(actual - allowed)}"
        ]
    return []


def _unsafe_entry_errors(entries: list[Path]) -> list[str]:
    unsafe = sorted(path.name for path in entries if not path.is_file() or path.is_symlink())
    return [f"release directory contains unsafe entries: {unsafe}"] if unsafe else []


def _sidecar_errors(root: Path, expected: dict[str, str]) -> list[str]:
    names = ["aqg.pyz", *(name for name in expected if name.endswith("-portable.zip"))]
    errors: list[str] = []
    for name in names:
        path = root / f"{name}.sha256"
        wanted = f"{expected.get(name, '')}  {name}\n"
        try:
            actual = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"cannot read checksum sidecar for {name}: {exc}")
            continue
        if not expected.get(name) or actual != wanted:
            errors.append(f"checksum sidecar does not exactly bind {name}")
    return errors


def _portable_errors(path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            unsafe = [name for name in names if _unsafe_archive_entry(name)]
            actual = set(names)
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"cannot read portable archive: {exc}"]
    errors = [f"unsafe portable archive entry {name}" for name in unsafe]
    if actual != EXPECTED_PORTABLE_FILES:
        errors.append(
            "portable archive inventory differs: "
            f"missing={sorted(EXPECTED_PORTABLE_FILES - actual)}, "
            f"unexpected={sorted(actual - EXPECTED_PORTABLE_FILES)}"
        )
    return errors


def _unsafe_archive_entry(raw: str) -> bool:
    name = PurePosixPath(raw)
    return name.is_absolute() or ".." in name.parts or name.as_posix() != raw


def _provenance_errors(root: Path, expected: dict[str, str]) -> list[str]:
    path = root / "provenance.intoto.json"
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot read provenance.intoto.json: {exc}"]
    if not isinstance(payload, dict):
        return ["provenance.intoto.json must contain an object"]
    subjects = payload.get("subject")
    if not isinstance(subjects, list):
        return ["provenance subject must be an array"]
    actual, subject_errors = _provenance_subjects(subjects)
    if subject_errors:
        return subject_errors
    missing = {
        name: digest
        for name, digest in expected.items()
        if name != "provenance.intoto.json" and actual.get(name) != digest
    }
    return [f"provenance does not bind checksummed subjects: {sorted(missing)}"] if missing else []


def _provenance_subjects(subjects: list[Any]) -> tuple[dict[str, str], list[str]]:
    actual: dict[str, str] = {}
    for item in subjects:
        if not isinstance(item, dict) or not isinstance(item.get("digest"), dict):
            return {}, ["provenance subject entry is malformed"]
        actual[str(item.get("name"))] = str(item["digest"].get("sha256"))
    return actual, []


def _smoke_errors(root: Path) -> list[str]:
    executable = root / "aqg.pyz"
    completed = subprocess.run(
        [sys.executable, str(executable), "--version"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode == 0 and completed.stdout.startswith("qg "):
        return []
    detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
    return [f"standalone executable smoke test failed: {detail}"]


def verify_release(root: Path, *, smoke: bool = True) -> dict[str, Any]:
    """Return a deterministic, machine-readable release verification result."""
    root = root.resolve()
    expected, errors = _checksums(root)
    errors.extend(_checksum_errors(root, expected))
    errors.extend(_inventory_errors(root, expected))
    errors.extend(_sidecar_errors(root, expected))
    portable = sorted(root.glob("agent-quality-gauntlet-*-portable.zip"))
    if len(portable) != 1:
        errors.append("release must contain exactly one versioned portable archive")
    else:
        errors.extend(_portable_errors(portable[0]))
    errors.extend(_provenance_errors(root, expected))
    if smoke and (root / "aqg.pyz").is_file():
        errors.extend(_smoke_errors(root))
    return {
        "schema_version": 1,
        "status": "verified" if not errors else "invalid",
        "directory": str(root),
        "artifacts": sorted(expected),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--no-smoke", action="store_true")
    args = parser.parse_args()
    result = verify_release(args.directory, smoke=not args.no_smoke)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
