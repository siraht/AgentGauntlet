# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-010
"""Contracts for run-evidence content manifests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aqg.errors import ConfigurationError
from aqg.evidence_manifest import (
    validate_run_id,
    verify_run_manifest,
    write_run_manifest,
)
from aqg.util import write_json


def _run(tmp_path: Path, run_id: str = "manifest-run") -> Path:
    run_dir = tmp_path / ".aqg" / "runs" / run_id
    (run_dir / "gates").mkdir(parents=True)
    write_json(run_dir / "gates" / "unit.json", {"gate": "unit", "status": "pass"})
    (run_dir / "gates" / "unit.log").write_text("log\n", encoding="utf-8")
    write_json(run_dir / "summary.json", {"run_id": run_id, "status": "pass"})
    return run_dir


@pytest.mark.parametrize(
    "value",
    ["", ".", "..", "a/b", "a\\b", "has space", "bad@id", "-leading", ".hidden", "line\n"],
)
def test_unsafe_run_ids_are_rejected(value: str) -> None:
    with pytest.raises(ConfigurationError):
        validate_run_id(value)


def test_manifest_is_deterministic_inventory_and_verifies(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    manifest = write_run_manifest(run_dir, "manifest-run")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert [item["path"] for item in payload["files"]] == [
        "gates/unit.json",
        "gates/unit.log",
        "summary.json",
    ]
    assert verify_run_manifest(run_dir) == {
        "ok": True,
        "run_id": "manifest-run",
        "errors": [],
        "modified": [],
        "deleted": [],
        "added": [],
        "unsafe_paths": [],
    }
    with pytest.raises(ConfigurationError, match="already finalized"):
        write_run_manifest(run_dir, "manifest-run")


@pytest.mark.parametrize("tamper", ["modified", "deleted", "added"])
def test_manifest_detects_evidence_tampering(tmp_path: Path, tamper: str) -> None:
    run_dir = _run(tmp_path)
    write_run_manifest(run_dir, "manifest-run")
    target = run_dir / "gates" / "unit.log"
    if tamper == "modified":
        target.write_text("changed\n", encoding="utf-8")
    elif tamper == "deleted":
        target.unlink()
    else:
        (run_dir / "gates" / "extra.log").write_text("extra\n", encoding="utf-8")
    result = verify_run_manifest(run_dir)
    assert result["ok"] is False
    assert result[tamper]


def test_manifest_rejects_malformed_identity_hash_size_and_timestamp(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    manifest = run_dir / "manifest.json"
    cases = [
        {"schema_version": 2, "run_id": "manifest-run", "completed_at": "2026-01-01Z", "files": []},
        {
            "schema_version": 1,
            "run_id": "../bad",
            "completed_at": "2026-01-01T00:00:00Z",
            "files": [],
        },
        {
            "schema_version": 1,
            "run_id": "other",
            "completed_at": "2026-01-01T00:00:00Z",
            "files": [],
        },
        {"schema_version": 1, "run_id": "manifest-run", "completed_at": "yesterday", "files": []},
        {
            "schema_version": 1,
            "run_id": "manifest-run",
            "completed_at": "2026-01-01T00:00:00Z",
            "files": [{"path": "summary.json", "sha256": "bad", "bytes": True}],
        },
    ]
    for payload in cases:
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        assert verify_run_manifest(run_dir)["ok"] is False


def test_manifest_rejects_unsafe_or_symlinked_evidence(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("secret", encoding="utf-8")
    (run_dir / "gates" / "link").symlink_to(outside)
    with pytest.raises(ConfigurationError, match="unsafe evidence path"):
        write_run_manifest(run_dir, "manifest-run")


def test_manifest_identity_must_match_directory(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    with pytest.raises(ConfigurationError, match="identity"):
        write_run_manifest(run_dir, "different")
