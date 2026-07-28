# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-016
"""Semantic acceptance-mutation and boundary-trace contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from aqg.acceptance import _execute, discover_mutations, semantic_rules
from aqg.errors import ConfigurationError

FEATURE_PATH = "features/Product.Setup.feature"
SCENARIO = "setup selects scope"


def _feature() -> dict:
    return {
        "scenarios": [
            {
                "name": SCENARIO,
                "examples": [
                    {"history": "none", "scope": "full"},
                    {"history": "present", "scope": "changed"},
                ],
            }
        ]
    }


def _config() -> dict:
    return {
        "semantic_mutations": [
            {
                "id": "history",
                "feature": FEATURE_PATH,
                "scenario": SCENARIO,
                "key": "history",
                "mapping": {"none": "present", "present": "none"},
            },
            {
                "id": "scope",
                "feature": FEATURE_PATH,
                "scenario": SCENARIO,
                "key": "scope",
                "mapping": {"full": "changed", "changed": "full"},
            },
        ]
    }


def test_every_declared_example_cell_gets_a_domain_valid_mutation() -> None:
    mutations = discover_mutations(
        _feature(),
        FEATURE_PATH,
        rules=semantic_rules(_config()),
        semantic_required=True,
    )
    assert len(mutations) == 4
    assert {mutation["strategy"] for mutation in mutations} == {"semantic"}
    assert all(mutation["domain_valid"] for mutation in mutations)
    assert {(item["original"], item["mutated"]) for item in mutations} == {
        ("none", "present"),
        ("present", "none"),
        ("full", "changed"),
        ("changed", "full"),
    }


def test_semantic_required_rejects_unmapped_or_unknown_domain_values() -> None:
    missing_rule = semantic_rules({"semantic_mutations": [_config()["semantic_mutations"][0]]})
    with pytest.raises(ConfigurationError, match="no semantic mutation rule"):
        discover_mutations(
            _feature(),
            FEATURE_PATH,
            rules=missing_rule,
            semantic_required=True,
        )
    feature = _feature()
    feature["scenarios"][0]["examples"][0]["history"] = "unknown"
    with pytest.raises(ConfigurationError, match="has no mapping"):
        discover_mutations(
            feature,
            FEATURE_PATH,
            rules=semantic_rules(_config()),
            semantic_required=True,
        )


def test_execution_records_that_failure_happened_after_application_boundary(
    tmp_path: Path,
) -> None:
    feature_json = tmp_path / "feature.json"
    feature_json.write_text("{}\n", encoding="utf-8")
    trace = tmp_path / "trace.json"
    script = tmp_path / "runner.py"
    script.write_text(
        "import json,os,pathlib,sys\n"
        "pathlib.Path(os.environ['AQG_ACCEPTANCE_TRACE']).write_text("
        "json.dumps({'reached_application_boundary':True,'stage':'public_api'}))\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    execution = _execute(
        [sys.executable, str(script)],
        tmp_path,
        feature_json,
        10,
        trace,
    )
    assert execution["outcome"] == "test_failure"
    assert execution["boundary_trace"] == {
        "reached_application_boundary": True,
        "stage": "public_api",
    }
    assert json.loads(trace.read_text())["stage"] == "public_api"
