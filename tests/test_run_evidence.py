# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-010
"""Run ownership and detailed-evidence snapshot contracts."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest import mock

import pytest

from aqg.constants import CONFIGURATION_ERROR, INFRASTRUCTURE_ERROR, PASS
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


def _project() -> dict:
    return {
        "thresholds": {
            "structure": {
                "max_cyclomatic_complexity": 10,
                "max_function_lines": 50,
                "max_nesting_depth": 4,
                "max_crap": 15,
            },
            "coverage": {"lines": 85, "branches": 75, "functions": 80, "statements": 85},
        },
        "profile_thresholds": {},
        "enforcement": {},
    }


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


def test_trusted_gate_never_executes_candidate_controlled_grader(tmp_path: Path) -> None:
    candidate_launcher = tmp_path / "quality" / "qg.py"
    candidate_launcher.parent.mkdir(parents=True)
    candidate_launcher.write_text(
        "from pathlib import Path\nPath('candidate-grader-ran').write_text('unsafe')\n",
        encoding="utf-8",
    )
    trusted_launcher = tmp_path / "trusted-qg.py"
    trusted_launcher.write_text(
        "import json,pathlib,sys\n"
        "root=pathlib.Path(sys.argv[sys.argv.index('--root')+1])\n"
        "gate=sys.argv[-1]\n"
        "p=root/'.aqg'/'work'/gate/'report.json'\n"
        "p.parent.mkdir(parents=True,exist_ok=True)\n"
        "p.write_text(json.dumps({'schema_version':2,'gate':gate,"
        "'status':'pass','exit_code':0}),encoding='utf-8')\n",
        encoding="utf-8",
    )
    trusted_tools = tmp_path / "trusted-tools"
    trusted_tools.mkdir()
    environment = {
        "AQG_TRUSTED_MODE": "1",
        "AQG_TRUSTED_LAUNCHER": str(trusted_launcher.resolve()),
        "AQG_TRUSTED_TOOLCHAIN_ROOT": str(trusted_tools.resolve()),
    }
    with mock.patch.dict(os.environ, environment, clear=False):
        code, evidence = run_gate(
            tmp_path,
            _gate_policy("python3 quality/qg.py adapter probe", gate="probe"),
            "probe",
            "trusted-grader",
        )
    assert code == PASS
    assert str(trusted_launcher.resolve()) in evidence["command"]
    assert not (tmp_path / "candidate-grader-ran").exists()
    assert verify_run_manifest(tmp_path / ".aqg" / "runs" / "trusted-grader")["ok"] is True


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
        mock.patch("aqg.runner._provenance", return_value=provenance) as provenance_call,
        mock.patch("aqg.runner.load_project", return_value=_project()),
    ):
        code, summary = run_profile(tmp_path, _profile_policy(command), "fast", quiet=True)
    run_dir = tmp_path / ".aqg" / "runs" / "profile-run"
    assert code == PASS and summary["run_id"] == "profile-run"
    assert (run_dir / "gates" / "probe.details.json").is_file()
    assert verify_run_manifest(run_dir)["ok"] is True
    assert json.loads((tmp_path / ".aqg" / "latest.json").read_text())["run_id"] == "profile-run"
    assert provenance_call.call_count == 2


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
        mock.patch("aqg.runner.load_project", return_value=_project()),
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


def test_shadow_run_preserves_quality_observation_but_returns_non_blocking(tmp_path: Path) -> None:
    script = tmp_path / "failing_report.py"
    script.write_text(
        "import json,pathlib,sys\n"
        "p=pathlib.Path('.aqg/work/probe/report.json')\n"
        "p.parent.mkdir(parents=True,exist_ok=True)\n"
        "p.write_text(json.dumps({'schema_version':2,'gate':'probe',"
        "'status':'quality_failure','exit_code':1}),encoding='utf-8')\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    provenance = {
        "revision": "candidate",
        "base_ref": "main",
        "change_fingerprint": "sha256:change",
        "control_fingerprint": "sha256:control",
    }
    with (
        mock.patch.dict(os.environ, {"AQG_RUN_ID": "shadow-run"}, clear=False),
        mock.patch("aqg.runner._provenance", return_value=provenance),
        mock.patch("aqg.runner.load_project", return_value=_project()),
    ):
        code, summary = run_profile(
            tmp_path,
            _profile_policy(f"python3 {script.name} adapter probe"),
            "fast",
            keep_going=True,
            quiet=True,
            shadow=True,
        )
    report = json.loads(
        (tmp_path / ".aqg" / "runs" / "shadow-run" / "retrospective.json").read_text()
    )
    assert code == PASS
    assert summary["status"] == "quality_failure"
    assert summary["command_status"] == "pass"
    assert summary["observed_exit_code"] == 1
    assert summary["mode"] == "shadow"
    assert report["certification"] == "observations_only"
    assert report["counts"]["measured_failures"] == 1
    assert report["counts"]["blocking_failures"] == 1


def test_stale_debt_baseline_is_a_manifested_configuration_failure(tmp_path: Path) -> None:
    command = _writer_script(tmp_path)
    baseline = tmp_path / "quality" / "baselines" / "debt.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("{}\n", encoding="utf-8")
    project = _project()
    project["enforcement"]["debt_baseline"] = "quality/baselines/debt.json"
    provenance = {
        "revision": "candidate",
        "base_ref": "main",
        "change_fingerprint": "sha256:change",
        "control_fingerprint": "sha256:control",
    }
    with (
        mock.patch.dict(os.environ, {"AQG_RUN_ID": "stale-baseline"}, clear=False),
        mock.patch("aqg.runner._provenance", return_value=provenance),
        mock.patch("aqg.runner.load_project", return_value=project),
        mock.patch(
            "aqg.runner.load_current_debt_baseline",
            side_effect=ConfigurationError("debt baseline policy fingerprint is stale"),
        ),
    ):
        code, summary = run_profile(
            tmp_path,
            _profile_policy(command),
            "fast",
            quiet=True,
            shadow=True,
        )
    run_dir = tmp_path / ".aqg" / "runs" / "stale-baseline"
    report = json.loads((run_dir / "retrospective.json").read_text())
    assert code == CONFIGURATION_ERROR
    assert summary["status"] == "configuration_error"
    assert report["counts"]["configuration_errors"] == 1
    assert report["configuration_errors"][0]["gate"] == "debt_baseline"
    assert verify_run_manifest(run_dir)["ok"] is True


def _structure_failure_script(root: Path, lines: int) -> str:
    script = root / f"structure_{lines}.py"
    script.write_text(
        "import json,pathlib,sys\n"
        "p=pathlib.Path('.aqg/work/structure/report.json')\n"
        "p.parent.mkdir(parents=True,exist_ok=True)\n"
        "payload={'schema_version':2,'gate':'structure','status':'quality_failure',"
        "'exit_code':1,'python':{'functions':[{'path':'src/legacy.py',"
        f"'name':'legacy','line':1,'end_line':{lines},'lines':{lines},"
        "'complexity':1,'nesting':0,'enforced':False}],'failures':['legacy debt']}}\n"
        "p.write_text(json.dumps(payload),encoding='utf-8')\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    return f"python3 {script.name} adapter structure"


def _reviewed_structure_baseline(lines: int) -> dict:
    return {
        "schema_version": 1,
        "state": "reviewed",
        "source_revision": "candidate",
        "policy_fingerprint": "sha256:policy",
        "control_fingerprint": "sha256:control",
        "created_at": "2026-07-28T00:00:00Z",
        "measurement": {
            "run_id": "baseline-shadow",
            "profile": "fast",
            "measured_at": "2026-07-28T00:00:00Z",
            "change_fingerprint": "sha256:change",
            "manifest_fingerprint": "sha256:manifest",
        },
        "inventory": [
            {
                "fingerprint": "structure:lines:src/legacy.py:legacy",
                "category": "structure",
                "path": "src/legacy.py",
                "location": "line:1",
                "severity": "medium",
                "value": lines,
                "direction": "higher_is_worse",
            }
        ],
        "reviewer": "owner@example.test",
        "reviewed_at": "2026-07-28T00:01:00Z",
    }


def test_reviewed_ratchet_reports_inherited_debt_but_rejects_worsening(
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "quality" / "baselines" / "debt.json"
    baseline_path.parent.mkdir(parents=True)
    baseline_path.write_text("{}\n", encoding="utf-8")
    project = _project()
    project["enforcement"]["debt_baseline"] = "quality/baselines/debt.json"
    provenance = {
        "revision": "candidate",
        "base_ref": "main",
        "change_fingerprint": "sha256:change",
        "control_fingerprint": "sha256:control",
    }
    baseline = _reviewed_structure_baseline(80)
    with (
        mock.patch("aqg.runner._provenance", return_value=provenance),
        mock.patch("aqg.runner.load_project", return_value=project),
        mock.patch("aqg.runner.load_current_debt_baseline", return_value=baseline),
        mock.patch.dict(os.environ, {"AQG_RUN_ID": "inherited-debt"}, clear=False),
    ):
        inherited_code, inherited_summary = run_profile(
            tmp_path,
            _profile_policy(_structure_failure_script(tmp_path, 80), gate="structure"),
            "fast",
            quiet=True,
        )
    inherited = json.loads(
        (tmp_path / ".aqg" / "runs" / "inherited-debt" / "retrospective.json").read_text()
    )
    assert inherited_code == PASS
    assert inherited_summary["measured_gate_exit_code"] == 1
    assert inherited_summary["status"] == "pass"
    assert inherited["counts"]["inherited_debt"] == 1
    assert inherited["counts"]["regressions"] == 0

    with (
        mock.patch("aqg.runner._provenance", return_value=provenance),
        mock.patch("aqg.runner.load_project", return_value=project),
        mock.patch("aqg.runner.load_current_debt_baseline", return_value=baseline),
        mock.patch.dict(os.environ, {"AQG_RUN_ID": "worsened-debt"}, clear=False),
    ):
        regression_code, regression_summary = run_profile(
            tmp_path,
            _profile_policy(_structure_failure_script(tmp_path, 81), gate="structure"),
            "fast",
            quiet=True,
        )
    regression = json.loads(
        (tmp_path / ".aqg" / "runs" / "worsened-debt" / "retrospective.json").read_text()
    )
    assert regression_code == 1
    assert regression_summary["status"] == "quality_failure"
    assert regression["counts"]["regressions"] == 1
    assert verify_run_manifest(tmp_path / ".aqg" / "runs" / "worsened-debt")["ok"] is True
