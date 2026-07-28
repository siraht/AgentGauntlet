# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-011
"""Contracts for base-controlled authoritative grading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aqg.adapters import _bin, _control_path
from aqg.errors import ConfigurationError
from aqg.policy import load_policy
from aqg.project import load_project
from aqg.scaffold import initialize_project


def test_trusted_mode_ignores_candidate_policy_project_and_tool_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted = tmp_path / "trusted"
    subject = tmp_path / "subject"
    trusted.mkdir()
    subject.mkdir()
    (trusted / "trusted.py").write_text("VALUE = 1\n", encoding="utf-8")
    (subject / "candidate.py").write_text("VALUE = 2\n", encoding="utf-8")
    initialize_project(trusted, owner="@trusted-owner", install=False, ci=False)
    initialize_project(subject, owner="@candidate-owner", install=False, ci=False)

    candidate_policy = subject / "quality" / "policy.toml"
    candidate_policy.write_text("version = 999\ninitialized = false\n", encoding="utf-8")
    candidate_project = subject / "quality" / "project.json"
    payload = json.loads(candidate_project.read_text())
    payload["name"] = "candidate-neutered"
    candidate_project.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setenv("AQG_TRUSTED_MODE", "1")
    monkeypatch.setenv(
        "AQG_TRUSTED_POLICY_PATH",
        str((trusted / "quality" / "policy.toml").resolve()),
    )
    monkeypatch.setenv(
        "AQG_TRUSTED_PROJECT_PATH",
        str((trusted / "quality" / "project.json").resolve()),
    )
    monkeypatch.setenv("AQG_TRUSTED_TOOLCHAIN_ROOT", str(trusted.resolve()))

    assert load_policy(subject)["policy"]["owner"] == "@trusted-owner"
    assert load_project(subject)["name"] == trusted.name
    assert _bin(subject, "ruff", "python").is_relative_to(trusted)
    assert _control_path(subject, "quality/config/python/ruff.toml").startswith(str(trusted))


def test_trusted_policy_path_must_be_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AQG_TRUSTED_MODE", "1")
    monkeypatch.setenv("AQG_TRUSTED_POLICY_PATH", "candidate/quality/policy.toml")
    with pytest.raises(ConfigurationError, match="must be absolute"):
        load_policy(tmp_path)
