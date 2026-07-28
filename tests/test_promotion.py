# Feature-Spec: AgentQualityGauntlet AQG-CORE-022
# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-007
"""Monotonic enforcement-stage promotion contracts."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aqg.errors import ConfigurationError
from aqg.evidence_manifest import write_evidence_json, write_run_manifest
from aqg.promotion import promotion_status, propose_promotion
from aqg.scaffold import initialize_project
from aqg.util import change_fingerprint, control_fingerprint


def _project(root: Path, *, mode: str = "adopt") -> None:
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    initialize_project(root, owner="@quality", install=False, ci=False, mode=mode)


def _set_stage(root: Path, stage: str) -> None:
    path = root / "quality" / "project.json"
    project = json.loads(path.read_text())
    project["enforcement"]["stage"] = stage
    if stage == "strict":
        project["enforcement"]["scope"] = "full"
    path.write_text(json.dumps(project), encoding="utf-8")


def _deep_pass(root: Path) -> None:
    run_id = "deep-ready"
    run_dir = root / ".aqg" / "runs" / run_id
    write_evidence_json(
        run_dir / "summary.json",
        {
            "schema_version": "2",
            "run_id": run_id,
            "profile": "deep",
            "mode": "enforce",
            "status": "pass",
            "enforcement_stage": "ratchet",
            "control_fingerprint": control_fingerprint(root),
            "change_fingerprint": change_fingerprint(root),
        },
    )
    names = (
        "inherited_debt",
        "regressions",
        "new_debt",
        "invalid_debt",
        "missing_evidence",
        "configuration_errors",
        "infrastructure_errors",
        "unknown_product_intent",
        "unreviewed_debt",
    )
    write_evidence_json(
        run_dir / "retrospective.json",
        {"schema_version": 1, "counts": dict.fromkeys(names, 0)},
    )
    write_run_manifest(run_dir, run_id)


def test_existing_and_greenfield_projects_start_at_safe_stages(tmp_path: Path) -> None:
    adopt = tmp_path / "adopt"
    strict = tmp_path / "strict"
    adopt.mkdir()
    strict.mkdir()
    _project(adopt, mode="adopt")
    _project(strict, mode="greenfield")
    assert promotion_status(adopt)["stage"] == "shadow"
    assert promotion_status(strict)["stage"] == "strict"


def test_ratchet_promotion_requires_reviewed_baseline_and_never_self_applies(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    with pytest.raises(ConfigurationError, match="reviewed debt baseline"):
        propose_promotion(tmp_path, "ratchet")
    baseline = tmp_path / "quality" / "baselines" / "debt.json"
    baseline.write_text("{}\n", encoding="utf-8")
    with patch("aqg.promotion.load_current_debt_baseline", return_value={"state": "reviewed"}):
        proposal = propose_promotion(tmp_path, "ratchet")
    assert proposal["proposal"]["authority"] == "none"
    assert proposal["proposal"]["required_project_changes"] == {"enforcement.stage": "ratchet"}
    project = json.loads((tmp_path / "quality" / "project.json").read_text())
    assert project["enforcement"]["stage"] == "shadow"


def test_strict_promotion_requires_debt_free_manifested_deep_pass(tmp_path: Path) -> None:
    _project(tmp_path)
    _set_stage(tmp_path, "ratchet")
    baseline = tmp_path / "quality" / "baselines" / "debt.json"
    baseline.write_text("{}\n", encoding="utf-8")
    with patch("aqg.promotion.load_current_debt_baseline", return_value={"state": "reviewed"}):
        with pytest.raises(ConfigurationError, match="deep run is missing"):
            propose_promotion(tmp_path, "strict")
        _deep_pass(tmp_path)
        proposal = propose_promotion(tmp_path, "strict")
    assert proposal["proposal"]["required_project_changes"] == {
        "enforcement.stage": "strict",
        "enforcement.scope": "full",
    }
    with pytest.raises(ConfigurationError, match="monotonic"):
        propose_promotion(tmp_path, "shadow")


def test_strict_promotion_rejects_stale_deep_evidence(tmp_path: Path) -> None:
    _project(tmp_path)
    _set_stage(tmp_path, "ratchet")
    baseline = tmp_path / "quality" / "baselines" / "debt.json"
    baseline.write_text("{}\n", encoding="utf-8")
    _deep_pass(tmp_path)
    (tmp_path / "QUALITY.md").write_text("changed controls\n", encoding="utf-8")
    with (
        patch("aqg.promotion.load_current_debt_baseline", return_value={"state": "reviewed"}),
        pytest.raises(ConfigurationError, match="different controls"),
    ):
        propose_promotion(tmp_path, "strict")
