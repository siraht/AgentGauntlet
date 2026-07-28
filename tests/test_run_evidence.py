# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-010
"""Run ownership and detailed-evidence snapshot contracts."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest import mock

import pytest

from aqg.constants import INFRASTRUCTURE_ERROR, PASS
from aqg.errors import ConfigurationError, InfrastructureError
from aqg.evidence import (
    create_exclusive_run_dir,
    require_writable_run_dir,
    snapshot_gate_details,
)
from aqg.evidence_manifest import verify_run_manifest, write_run_manifest
from aqg.runner import run_gate, run_profile
from aqg.util import write_json


def _report(root: Path, directory: str = "unit", **changes: object) -> Path:
    path = root / ".aqg" / "work" / directory / "report.json"
    payload: dict[str, object] = {
        "schema_version": 2,
        "gate": directory,
        "status": "pass",
        "exit_code": 0,
        "marker": "fresh",
    }
    payload.update(changes)
    write_json(path, payload)
    return path


def _gate_policy(command: str, gate: str = "unit") -> dict:
    return {
        "gates": {
            gate: {
                "command": command,
                "clean_paths": [f".aqg/work/{gate}"],
                "quality_failure_exit_codes": [1],
                "timeout_seconds": 10,
            }
        }
    }


def _profile_policy(command: str, gate: str = "probe") -> dict:
    policy = _gate_policy(command, gate)
    policy.update(
        {
            "initialized": True,
            "profiles": {"fast": {"gates": [gate]}},
            "policy": {
                "protected_paths": [],
                "human_review_paths": [],
                "blocked_command_regex": [],
            },
            "risk_profiles": {
                name: {"required_execution_profiles": ["fast"]}
                for name in ("experiment", "standard", "high_assurance", "critical")
            },
        }
    )
    return policy


def _writer_script(root: Path, gate: str = "probe") -> str:
    script = root / "write_report.py"
    script.write_text(
        "import json,pathlib\n"
        f"p=pathlib.Path('.aqg/work/{gate}/report.json')\n"
        "p.parent.mkdir(parents=True,exist_ok=True)\n"
        f"p.write_text(json.dumps({{'schema_version':2,'gate':'{gate}',"
        "'status':'pass','exit_code':0}),encoding='utf-8')\n",
        encoding="utf-8",
    )
    return f"python3 {script.name} adapter {gate}"


def test_run_directories_are_exclusive_and_finalized_runs_are_closed(tmp_path: Path) -> None:
    run_dir = create_exclusive_run_dir(tmp_path, "owned")
    assert require_writable_run_dir(tmp_path, "owned") == run_dir
    with pytest.raises(ConfigurationError, match="already exists"):
        create_exclusive_run_dir(tmp_path, "owned")
    write_run_manifest(run_dir, "owned")
    with pytest.raises(ConfigurationError, match="finalized"):
        require_writable_run_dir(tmp_path, "owned")


def test_detail_snapshot_is_independent_of_mutable_work_report(tmp_path: Path) -> None:
    run_dir = create_exclusive_run_dir(tmp_path, "detail")
    report = _report(tmp_path)
    destination, error = snapshot_gate_details(
        tmp_path,
        run_dir=run_dir,
        gate_name="unit",
        command="python3 quality/qg.py adapter unit",
        clean_paths=[".aqg/work/unit"],
        started_at=time.time(),
        expected_exit=0,
    )
    assert error is None and destination is not None
    report.write_text('{"changed":true}', encoding="utf-8")
    report.unlink()
    assert json.loads(destination.read_text(encoding="utf-8"))["marker"] == "fresh"


@pytest.mark.parametrize(
    ("changes", "prepare", "message"),
    [
        ({}, "missing", "found 0"),
        ({}, "malformed", "schema_version"),
        ({"gate": "lint"}, "report", "does not identify"),
        ({"exit_code": 1}, "report", "does not match"),
        ({}, "stale", "stale"),
    ],
)
def test_unusable_adapter_detail_fails_closed(
    tmp_path: Path,
    changes: dict[str, object],
    prepare: str,
    message: str,
) -> None:
    run_dir = create_exclusive_run_dir(tmp_path, f"bad-{prepare}")
    if prepare == "malformed":
        report = _report(tmp_path)
        report.write_text("[]", encoding="utf-8")
    elif prepare != "missing":
        report = _report(tmp_path, **changes)
        if prepare == "stale":
            old = time.time() - 120
            os.utime(report, (old, old))
    destination, error = snapshot_gate_details(
        tmp_path,
        run_dir=run_dir,
        gate_name="unit",
        command="python3 quality/qg.py adapter unit",
        clean_paths=[".aqg/work/unit"],
        started_at=time.time(),
        expected_exit=0,
    )
    assert destination is None
    assert error is not None and message in error


def test_multiple_matching_reports_are_ambiguous(tmp_path: Path) -> None:
    run_dir = create_exclusive_run_dir(tmp_path, "ambiguous")
    _report(tmp_path)
    nested = tmp_path / ".aqg" / "work" / "unit" / "nested" / "report.json"
    write_json(
        nested,
        {"schema_version": 2, "gate": "unit", "status": "pass", "exit_code": 0},
    )
    _, error = snapshot_gate_details(
        tmp_path,
        run_dir=run_dir,
        gate_name="unit",
        command="python3 quality/qg.py adapter unit",
        clean_paths=[".aqg/work/unit"],
        started_at=time.time(),
        expected_exit=0,
    )
    assert error is not None and "found 2" in error


def test_standalone_gate_finalizes_and_missing_adapter_detail_is_infrastructure(
    tmp_path: Path,
) -> None:
    script = tmp_path / "fake.py"
    script.write_text("print('no detail')\n", encoding="utf-8")
    code, evidence = run_gate(
        tmp_path,
        _gate_policy(f"python3 {script.name} adapter unit"),
        "unit",
        "standalone",
    )
    run_dir = tmp_path / ".aqg" / "runs" / "standalone"
    assert code == INFRASTRUCTURE_ERROR
    assert "expected one fresh detailed report" in evidence["stderr"]
    assert verify_run_manifest(run_dir)["ok"] is True
    with pytest.raises(ConfigurationError, match="already exists"):
        run_gate(tmp_path, _gate_policy("python3 -c \"print('ok')\""), "unit", "standalone")


def test_profile_snapshots_details_then_manifests_before_latest(tmp_path: Path) -> None:
    command = _writer_script(tmp_path)
    provenance = {
        "revision": "candidate",
        "base_ref": "main",
        "change_fingerprint": "sha256:change",
        "control_fingerprint": "sha256:control",
    }
    with (
        mock.patch.dict(os.environ, {"AQG_RUN_ID": "profile-run"}, clear=False),
        mock.patch("aqg.runner._provenance", return_value=provenance),
    ):
        code, summary = run_profile(tmp_path, _profile_policy(command), "fast", quiet=True)
    run_dir = tmp_path / ".aqg" / "runs" / "profile-run"
    assert code == PASS and summary["run_id"] == "profile-run"
    assert (run_dir / "gates" / "probe.details.json").is_file()
    assert verify_run_manifest(run_dir)["ok"] is True
    assert json.loads((tmp_path / ".aqg" / "latest.json").read_text())["run_id"] == "profile-run"


def test_latest_is_not_updated_when_manifest_finalization_fails(tmp_path: Path) -> None:
    provenance = {
        "revision": "candidate",
        "base_ref": "main",
        "change_fingerprint": "sha256:change",
        "control_fingerprint": "sha256:control",
    }
    with (
        mock.patch.dict(os.environ, {"AQG_RUN_ID": "broken-manifest"}, clear=False),
        mock.patch("aqg.runner._provenance", return_value=provenance),
        mock.patch(
            "aqg.runner.write_run_manifest",
            side_effect=InfrastructureError("storage unavailable"),
        ),
        pytest.raises(InfrastructureError, match="storage unavailable"),
    ):
        run_profile(
            tmp_path,
            _profile_policy("python3 -c \"print('ok')\""),
            "fast",
            quiet=True,
        )
    assert not (tmp_path / ".aqg" / "latest.json").exists()
