# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-003 AQG-RETRO-004 AQG-RETRO-010
"""Contracts for debt proposals derived from immutable shadow evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from aqg.cli import main
from aqg.constants import PASS
from aqg.debt import DebtError, compare, validate_baseline
from aqg.debt_store import propose_debt_baseline
from aqg.errors import ConfigurationError, InfrastructureError
from aqg.evidence_manifest import write_evidence_json, write_run_manifest
from aqg.util import change_fingerprint, control_fingerprint


def _run(root: Path, run_id: str, *, mode: str = "shadow") -> Path:
    run_dir = root / ".aqg" / "runs" / run_id
    write_evidence_json(
        run_dir / "summary.json",
        {
            "schema_version": "2",
            "run_id": run_id,
            "profile": "fast",
            "mode": mode,
            "revision": "a" * 40,
            "base_ref": "HEAD",
            "change_fingerprint": change_fingerprint(root, "HEAD"),
            "control_fingerprint": control_fingerprint(root),
        },
    )
    write_evidence_json(
        run_dir / "retrospective.json",
        {
            "schema_version": 1,
            "inventory": [
                {
                    "fingerprint": "structure:src/legacy.py:legacy",
                    "category": "structure",
                    "path": "src/legacy.py",
                    "location": "legacy",
                    "severity": "warning",
                    "value": 80,
                    "direction": "higher_is_worse",
                }
            ],
        },
    )
    write_run_manifest(run_dir, run_id)
    return run_dir


def _policy(root: Path) -> None:
    path = root / "quality" / "policy.toml"
    path.parent.mkdir(parents=True)
    path.write_text("version = 2\n", encoding="utf-8")


def test_proposal_preserves_complete_manifested_measurement(tmp_path: Path) -> None:
    _policy(tmp_path)
    run_dir = _run(tmp_path, "20260728-shadow")
    report = propose_debt_baseline(tmp_path, "20260728-shadow")
    proposal = validate_baseline(report["baseline"])

    assert proposal["state"] == "proposed"
    assert proposal["measurement"]["run_id"] == "20260728-shadow"
    assert proposal["source_revision"] == "a" * 40
    assert proposal["inventory"][0]["value"] == 80
    assert report["manifest_verification"]["ok"] is True
    assert report["source_manifest_fingerprint"].startswith("sha256:")
    assert Path(report["path"]).is_file()
    with pytest.raises(DebtError, match="reviewed"):
        compare(proposal["inventory"], proposal)

    with pytest.raises(ConfigurationError, match="overwrite"):
        propose_debt_baseline(tmp_path, "20260728-shadow")
    assert json.loads((run_dir / "manifest.json").read_text())["run_id"] == "20260728-shadow"


def test_latest_selects_newest_shadow_and_rejects_enforcement_run(tmp_path: Path) -> None:
    _policy(tmp_path)
    old = _run(tmp_path, "old-shadow")
    new = _run(tmp_path, "new-shadow")
    os.utime(old / "summary.json", ns=(1, 1))
    os.utime(new / "summary.json", ns=(2, 2))
    enforce = _run(tmp_path, "newer-enforce", mode="enforce")
    proposal = propose_debt_baseline(tmp_path)
    assert proposal["baseline"]["measurement"]["run_id"] == "new-shadow"
    with pytest.raises(ConfigurationError, match="not a shadow"):
        propose_debt_baseline(tmp_path, enforce.name)


def test_tampered_or_incomplete_shadow_evidence_fails_closed(tmp_path: Path) -> None:
    _policy(tmp_path)
    run_dir = _run(tmp_path, "tampered-shadow")
    (run_dir / "retrospective.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(InfrastructureError, match="manifest verification"):
        propose_debt_baseline(tmp_path, run_dir.name)

    empty = tmp_path / "empty"
    _policy(empty)
    with pytest.raises(ConfigurationError, match="no completed shadow"):
        propose_debt_baseline(empty)


def test_proposal_rejects_controls_changed_after_measurement(tmp_path: Path) -> None:
    _policy(tmp_path)
    run_dir = _run(tmp_path, "stale-shadow")
    (tmp_path / "quality" / "policy.toml").write_text("version = 2\nchanged = true\n")
    with pytest.raises(ConfigurationError, match="controls changed"):
        propose_debt_baseline(tmp_path, run_dir.name)


def test_cli_writes_non_authorizing_proposal_as_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _policy(tmp_path)
    _run(tmp_path, "cli-shadow")
    code = main(
        [
            "--root",
            str(tmp_path),
            "--json",
            "baseline",
            "debt",
            "propose",
            "--run-id",
            "cli-shadow",
        ]
    )
    assert code == PASS
    payload = json.loads(capsys.readouterr().out)
    assert payload["baseline"]["state"] == "proposed"
    assert payload["baseline"]["measurement"]["run_id"] == "cli-shadow"
