# Feature-Spec: AgentQualityGauntlet AQG-CORE-003 AQG-CORE-004 AQG-CORE-005 AQG-CORE-024
"""Executable contracts for public AQG JSON evidence schemas."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

from aqg.evidence_manifest import write_run_manifest
from aqg.runner import run_profile
from aqg.schema_contracts import validate_instance, validate_named_schema


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
        "enforcement": {"stage": "shadow"},
    }


def _policy(command: str) -> dict:
    return {
        "initialized": True,
        "gates": {
            "probe": {
                "command": command,
                "clean_paths": [".aqg/work/probe"],
                "quality_failure_exit_codes": [1],
                "timeout_seconds": 10,
            }
        },
        "profiles": {"fast": {"gates": ["probe"]}},
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


def test_real_profile_evidence_conforms_to_published_schemas(tmp_path: Path) -> None:
    schema_root = Path(__file__).resolve().parents[1]
    writer = tmp_path / "writer.py"
    writer.write_text(
        "import json,pathlib\n"
        "p=pathlib.Path('.aqg/work/probe/report.json')\n"
        "p.parent.mkdir(parents=True,exist_ok=True)\n"
        "p.write_text(json.dumps({'schema_version':2,'gate':'probe',"
        "'status':'pass','exit_code':0}),encoding='utf-8')\n",
        encoding="utf-8",
    )
    run_id = "schema-contract"
    with (
        mock.patch.dict(os.environ, {"AQG_RUN_ID": run_id}, clear=False),
        mock.patch("aqg.runner.load_project", return_value=_project()),
    ):
        code, _ = run_profile(
            tmp_path,
            _policy(f"python3 {writer.name} adapter probe"),
            "fast",
            quiet=True,
        )
    assert code == 0
    run = tmp_path / ".aqg" / "runs" / run_id
    contracts = {
        "gate-report": run / "gates" / "probe.json",
        "run-summary": run / "summary.json",
        "retrospective": run / "retrospective.json",
        "run-manifest": run / "manifest.json",
    }
    for name, path in contracts.items():
        assert validate_named_schema(schema_root, name, json.loads(path.read_text())) == []


def test_schema_validator_rejects_nested_contract_drift() -> None:
    schema = {
        "type": "object",
        "required": ["items"],
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["sha256"],
                    "properties": {"sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}},
                    "additionalProperties": False,
                },
            }
        },
        "additionalProperties": False,
    }
    errors = validate_instance({"items": [{"sha256": "not-a-digest", "extra": True}]}, schema)
    assert errors == [
        "$.items[0].sha256: string does not match '^[0-9a-f]{64}$'",
        "$.items[0]: unexpected property 'extra'",
    ]
    assert validate_instance(True, {"enum": [0, 1]}) == [
        "$: value True is not in the declared enum"
    ]


def test_risk_and_debt_documents_conform_to_public_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    risk = json.loads((root / "quality" / "change-risk.json").read_text())
    assert validate_named_schema(root, "change-risk", risk) == []
    baseline = {
        "schema_version": 1,
        "state": "reviewed",
        "source_revision": "a" * 40,
        "policy_fingerprint": "sha256:" + "1" * 64,
        "control_fingerprint": "sha256:" + "2" * 64,
        "created_at": "2026-07-28T00:00:00Z",
        "measurement": {
            "run_id": "shadow-1",
            "profile": "fast",
            "measured_at": "2026-07-28T00:01:00Z",
            "change_fingerprint": "sha256:" + "3" * 64,
            "manifest_fingerprint": "sha256:" + "4" * 64,
        },
        "inventory": [],
        "reviewer": "owner@example.test",
        "reviewed_at": "2026-07-28T00:02:00Z",
    }
    assert validate_named_schema(root, "debt-baseline", baseline) == []


def test_manifest_schema_rejects_post_contract_additions(tmp_path: Path) -> None:
    run = tmp_path / "manifest-contract"
    run.mkdir()
    (run / "summary.json").write_text("{}\n", encoding="utf-8")
    manifest = write_run_manifest(run, run.name)
    payload = json.loads(manifest.read_text())
    payload["unexpected"] = True
    root = Path(__file__).resolve().parents[1]
    assert validate_named_schema(root, "run-manifest", payload) == [
        "$: unexpected property 'unexpected'"
    ]
