# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-003 AQG-RETRO-004 AQG-RETRO-010
"""Contracts for debt proposals derived from immutable shadow evidence."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import Mock, call

import pytest

from aqg.cli import main
from aqg.constants import PASS
from aqg.debt import DebtError, compare, validate_baseline
from aqg.debt_store import (
    _measurement_values,
    _validate_shadow_scope,
    _verified_shadow_documents,
    load_current_debt_baseline,
    propose_debt_baseline,
    review_debt_proposal,
)
from aqg.errors import ConfigurationError, InfrastructureError
from aqg.evidence_manifest import write_evidence_json, write_run_manifest
from aqg.maintenance import create_maintenance_request
from aqg.scaffold import initialize_project
from aqg.util import change_fingerprint, control_fingerprint, git_revision


def _run(
    root: Path,
    run_id: str,
    *,
    mode: str = "shadow",
    revision: str = "a" * 40,
) -> Path:
    run_dir = root / ".aqg" / "runs" / run_id
    write_evidence_json(
        run_dir / "summary.json",
        {
            "schema_version": "2",
            "run_id": run_id,
            "profile": "fast",
            "mode": mode,
            "revision": revision,
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


def test_proposal_preserves_complete_manifested_measurement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    timestamps = iter(["2026-07-28T22:49:39+00:00", "2026-07-28T22:49:40+00:00"])
    monkeypatch.setattr("aqg.debt_store.utc_now", lambda: next(timestamps))
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
    assert report["document_fingerprint"].startswith("sha256:")
    assert report["schema_version"] == 1
    assert set(report) == {
        "schema_version",
        "proposal_id",
        "path",
        "document_fingerprint",
        "source_manifest_fingerprint",
        "baseline",
        "manifest_verification",
    }
    assert report["proposal_id"] == (
        "debt-20260728-shadow-" + report["source_manifest_fingerprint"][7:19]
    )
    assert Path(report["path"]).is_file()
    with pytest.raises(DebtError, match="reviewed"):
        compare(proposal["inventory"], proposal)

    with pytest.raises(ConfigurationError, match="overwrite"):
        propose_debt_baseline(tmp_path, "20260728-shadow")
    assert json.loads((run_dir / "manifest.json").read_text())["run_id"] == "20260728-shadow"


def test_verified_shadow_documents_preserves_diagnostics_and_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = Mock(side_effect=[{"summary": 1}, {"retrospective": 1}, {"manifest": 1}])
    monkeypatch.setattr("aqg.debt_store._object", reader)
    monkeypatch.setattr(
        "aqg.debt_store.verify_run_manifest",
        Mock(return_value={"ok": True, "errors": []}),
    )

    documents = _verified_shadow_documents(tmp_path, "run-1")

    assert documents == (
        {"ok": True, "errors": []},
        {"summary": 1},
        {"retrospective": 1},
        {"manifest": 1},
    )
    assert reader.call_args_list == [
        call(tmp_path / "summary.json", "run summary"),
        call(tmp_path / "retrospective.json", "retrospective evidence"),
        call(tmp_path / "manifest.json", "run manifest"),
    ]
    reader.reset_mock()
    monkeypatch.setattr(
        "aqg.debt_store.verify_run_manifest",
        Mock(return_value={"ok": False, "errors": ["first", "second"]}),
    )

    with pytest.raises(InfrastructureError) as error:
        _verified_shadow_documents(tmp_path, "run-1")

    assert str(error.value) == "shadow run run-1 failed manifest verification: first; second"
    reader.assert_not_called()


def test_shadow_scope_uses_exact_baseline_exclusion_and_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controls = Mock(
        side_effect=[
            "sha256:" + "1" * 64,
            "sha256:" + "2" * 64,
            "sha256:" + "1" * 64,
            "sha256:" + "2" * 64,
        ]
    )
    changes = Mock(return_value="sha256:" + "3" * 64)
    monkeypatch.setattr("aqg.debt_store.control_fingerprint", controls)
    monkeypatch.setattr("aqg.debt_store.change_fingerprint", changes)
    summary = {
        "run_id": "run-1",
        "mode": "shadow",
        "control_fingerprint": "sha256:" + "1" * 64,
        "change_fingerprint": "sha256:" + "3" * 64,
        "base_ref": "origin/main",
    }

    actual = _validate_shadow_scope(tmp_path, "run-1", summary)

    assert actual == ("sha256:" + "2" * 64, "sha256:" + "3" * 64)
    assert controls.call_args_list == [
        call(tmp_path),
        call(tmp_path, exclude_patterns=["quality/baselines/debt.json"]),
    ]
    changes.assert_called_once_with(tmp_path, "origin/main")
    changes.reset_mock()
    summary["base_ref"] = None

    with pytest.raises(ConfigurationError, match="review surface changed"):
        _validate_shadow_scope(tmp_path, "run-1", summary)

    changes.assert_not_called()


@pytest.mark.parametrize("revision", [None, "", "uncommitted"])
def test_measurement_rejects_each_invalid_revision(revision: object) -> None:
    with pytest.raises(ConfigurationError) as error:
        _measurement_values(
            "run-1",
            {"revision": revision, "profile": "fast"},
            {"schema_version": 1, "inventory": []},
            {"completed_at": "2026-07-28T00:00:00+00:00"},
        )

    assert str(error.value) == "a debt proposal requires a committed source revision"


@pytest.mark.parametrize(
    ("profile", "measured_at"),
    [(None, "2026-07-28T00:00:00+00:00"), ("fast", None)],
)
def test_measurement_rejects_each_incomplete_provenance(
    profile: object, measured_at: object
) -> None:
    with pytest.raises(InfrastructureError, match="incomplete measurement provenance"):
        _measurement_values(
            "run-1",
            {"revision": "a" * 40, "profile": profile},
            {"schema_version": 1, "inventory": []},
            {"completed_at": measured_at},
        )


def test_proposal_wires_resolved_run_identity_to_helpers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _policy(tmp_path)
    run_dir = _run(tmp_path, "wired-shadow")
    summary = json.loads((run_dir / "summary.json").read_text())
    retrospective = json.loads((run_dir / "retrospective.json").read_text())
    manifest = json.loads((run_dir / "manifest.json").read_text())
    documents = Mock(return_value=({"ok": True, "errors": []}, summary, retrospective, manifest))
    scope = Mock(return_value=("sha256:" + "4" * 64, summary["change_fingerprint"]))
    measurement = Mock(
        return_value=(
            retrospective["inventory"],
            summary["revision"],
            summary["profile"],
            manifest["completed_at"],
        )
    )
    monkeypatch.setattr("aqg.debt_store._verified_shadow_documents", documents)
    monkeypatch.setattr("aqg.debt_store._validate_shadow_scope", scope)
    monkeypatch.setattr("aqg.debt_store._measurement_values", measurement)

    propose_debt_baseline(tmp_path, "wired-shadow")

    documents.assert_called_once_with(run_dir, "wired-shadow")
    scope.assert_called_once_with(tmp_path, "wired-shadow", summary)
    measurement.assert_called_once_with("wired-shadow", summary, retrospective, manifest)


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


def _git(root: Path, *arguments: str) -> None:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_reviewed_baseline_install_and_freshness_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "debt@example.invalid")
    _git(tmp_path, "config", "user.name", "Debt Reviewer")
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "app.py")
    _git(tmp_path, "commit", "-qm", "seed")
    initialize_project(tmp_path, owner="@quality", install=False, ci=False, mode="adopt")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "install AQG")

    _run(tmp_path, "review-shadow", revision=git_revision(tmp_path))
    proposal = propose_debt_baseline(tmp_path, "review-shadow")
    request = create_maintenance_request(
        tmp_path,
        [{"path": "quality/baselines/debt.json", "operation": "add"}],
        reason="Install the reviewed inherited-debt inventory",
        requester="builder@example.test",
    )
    monkeypatch.setenv("AQG_POLICY_MAINTENANCE", "1")
    monkeypatch.setenv("AQG_MAINTENANCE_REQUEST", request["request_id"])
    reviewed = review_debt_proposal(
        tmp_path,
        proposal["proposal_id"],
        reviewer="owner@example.test",
    )
    baseline_path = Path(reviewed["path"])
    assert reviewed["baseline"]["state"] == "reviewed"
    assert load_current_debt_baseline(tmp_path, baseline_path)["reviewer"] == ("owner@example.test")

    policy = tmp_path / "quality" / "policy.toml"
    policy.write_text(policy.read_text() + "\n# stale control\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="policy fingerprint is stale"):
        load_current_debt_baseline(tmp_path, baseline_path)
