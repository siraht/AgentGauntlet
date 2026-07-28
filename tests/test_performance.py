# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-017
"""Repeatable performance-sampling and variance contracts."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from aqg.adapters import _performance
from aqg.constants import INFRASTRUCTURE_ERROR, PASS, QUALITY_FAILURE
from aqg.errors import ConfigurationError
from aqg.performance import aggregate_scores, sampling_policy
from aqg.util import CommandResult


def test_median_of_three_stable_samples_passes() -> None:
    code, report = aggregate_scores(
        [
            {"performance": 0.82, "accessibility": 0.97},
            {"performance": 0.84, "accessibility": 0.98},
            {"performance": 0.83, "accessibility": 0.96},
        ],
        {"performance": 0.8, "accessibility": 0.95},
        expected_count=3,
        max_score_spread=0.05,
    )
    assert code == PASS
    assert report["metrics"]["performance"]["median"] == 0.83
    assert report["metrics"]["performance"]["spread"] == pytest.approx(0.02)


def test_stable_product_shortfall_is_quality_failure() -> None:
    code, report = aggregate_scores(
        [
            {"performance": 0.7, "accessibility": 0.97},
            {"performance": 0.72, "accessibility": 0.97},
            {"performance": 0.71, "accessibility": 0.97},
        ],
        {"performance": 0.8, "accessibility": 0.95},
        expected_count=3,
        max_score_spread=0.05,
    )
    assert code == QUALITY_FAILURE
    assert report["failures"] == ["performance median 0.71 < 0.80"]


def test_unstable_or_incomplete_samples_are_unusable_infrastructure_evidence() -> None:
    unstable, unstable_report = aggregate_scores(
        [
            {"performance": 0.7, "accessibility": 0.97},
            {"performance": 0.9, "accessibility": 0.97},
            {"performance": 0.8, "accessibility": 0.97},
        ],
        {"performance": 0.8, "accessibility": 0.95},
        expected_count=3,
        max_score_spread=0.05,
    )
    incomplete, incomplete_report = aggregate_scores(
        [{"performance": 0.9, "accessibility": 0.99}],
        {"performance": 0.8, "accessibility": 0.95},
        expected_count=3,
        max_score_spread=0.05,
    )
    assert unstable == INFRASTRUCTURE_ERROR
    assert unstable_report["unstable"]
    assert incomplete == INFRASTRUCTURE_ERROR
    assert "expected 3" in incomplete_report["failures"][0]


@pytest.mark.parametrize(
    "thresholds",
    [
        {"sample_count": 1},
        {"sample_count": 4},
        {"warmup_runs": -1},
        {"max_score_spread": 2},
    ],
)
def test_sampling_policy_rejects_unstable_configuration(thresholds: dict) -> None:
    with pytest.raises(ConfigurationError):
        sampling_policy(thresholds)


def test_adapter_runs_warmup_plus_three_retained_samples(tmp_path) -> None:
    browser = tmp_path / "chromium"
    browser.write_text("", encoding="utf-8")
    command = CommandResult(
        command=["node"],
        cwd=str(tmp_path),
        code=0,
        status="pass",
        stdout=str(browser),
        stderr="",
        duration_ms=1,
        timed_out=False,
    )
    project = {
        "web": {"start_command": ["serve"], "base_url": "http://127.0.0.1:9999"},
        "thresholds": {
            "performance": {
                "lighthouse_performance": 0.8,
                "lighthouse_accessibility": 0.95,
                "sample_count": 3,
                "warmup_runs": 1,
                "max_score_spread": 0.05,
            }
        },
        "profile_thresholds": {},
    }
    sample = (
        {"code": 0, "status": "pass"},
        {"performance": 0.9, "accessibility": 0.99},
        None,
    )
    with (
        patch("aqg.adapters._start_web", return_value=(None, tmp_path / "server.log")),
        patch("aqg.adapters.run_command", return_value=command),
        patch("aqg.adapters._tool", return_value="lighthouse"),
        patch("aqg.adapters._lighthouse_sample", side_effect=[sample] * 4) as lighthouse,
    ):
        code, report = _performance(tmp_path, project)
    assert code == PASS
    assert lighthouse.call_count == 4
    assert report["sampling_policy"] == {
        "sample_count": 3,
        "warmup_runs": 1,
        "max_score_spread": 0.05,
    }
    assert len(report["samples"]) == 3
