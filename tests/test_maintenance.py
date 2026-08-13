# Feature-Spec: AgentQualityGauntlet AQG-CORE-026
# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-012
"""Contracts for legitimate, exact policy-maintenance approval."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from aqg.adapters import run_adapter
from aqg.approvals import template
from aqg.constants import PASS, QUALITY_FAILURE
from aqg.errors import ConfigurationError
from aqg.maintenance import (
    create_maintenance_request,
    load_maintenance_request,
    parse_change_spec,
    protected_changes,
    validate_policy_maintenance,
)
from aqg.policy import load_policy
from aqg.scaffold import initialize_project
from aqg.util import write_json


def _git(root: Path, *arguments: str) -> None:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.fixture
def project(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "maintainer@example.invalid")
    _git(tmp_path, "config", "user.name", "AQG Maintainer")
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "app.py")
    _git(tmp_path, "commit", "-qm", "seed")
    initialize_project(tmp_path, owner="@quality", install=False, ci=False, mode="adopt")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "install gauntlet")
    return tmp_path


def _approve(root: Path, changes: list[dict[str, str]]) -> None:
    payload = template(root, "policy-maintenance", reviewer="owner@example.test")
    payload.update(
        {
            "result": "pass",
            "scope": [item["path"] for item in changes],
            "procedure": ["Reviewed the exact protected diff and conformance impact"],
            "evidence": ["policy diff and maintenance gate report"],
            "independence": {
                "reviewer_did_not_author_change": True,
                "reviewer_did_not_modify_evidence": True,
            },
            "maintenance": {
                "reason": "Apply a reviewed policy contract change",
                "authorized_changes": changes,
            },
        }
    )
    write_json(root / "quality" / "approvals" / "policy-maintenance.json", payload)


def test_source_only_change_needs_no_policy_approval(project: Path) -> None:
    (project / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    report = validate_policy_maintenance(project, load_policy(project), "HEAD")
    assert report == {
        "required": False,
        "changes": [],
        "authorized_changes": [],
        "errors": [],
        "exit_code": PASS,
    }


def _request(root: Path, changes: list[dict[str, str]], monkeypatch: pytest.MonkeyPatch) -> str:
    report = create_maintenance_request(
        root,
        changes,
        reason="Apply an exact no-weakening maintenance change",
        requester="builder@example.test",
    )
    monkeypatch.setenv("AQG_MAINTENANCE_REQUEST", report["request_id"])
    return str(report["request_id"])


def test_comment_only_policy_change_passes_with_exact_request(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changes = [{"path": "quality/policy.toml", "operation": "modify"}]
    _request(project, changes, monkeypatch)
    policy_path = project / "quality" / "policy.toml"
    policy_path.write_text(policy_path.read_text() + "\n# reviewed candidate change\n")
    policy = load_policy(project)
    assert protected_changes(project, policy, "HEAD") == changes

    approved = validate_policy_maintenance(project, policy, "HEAD")
    assert approved["exit_code"] == PASS
    assert approved["human_authority_required"] is False
    assert approved["classifications"][0]["classification"] == "neutral"
    code, adapter = run_adapter(project, "policy_maintenance")
    assert code == PASS
    assert adapter["changes"] == changes


def test_request_cannot_authorize_a_different_operation_or_path(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = project / "quality" / "config" / "new-policy.txt"
    _request(
        project,
        [{"path": "quality/config/new-policy.txt", "operation": "modify"}],
        monkeypatch,
    )
    candidate.write_text("candidate\n", encoding="utf-8")
    policy = load_policy(project)
    actual = protected_changes(project, policy, "HEAD")
    assert actual == [{"path": "quality/config/new-policy.txt", "operation": "add"}]
    report = validate_policy_maintenance(project, policy, "HEAD")
    assert report["exit_code"] == QUALITY_FAILURE
    assert any("exactly match" in error for error in report["errors"])


def test_stronger_threshold_passes_without_human_authority(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changes = [{"path": "quality/project.json", "operation": "modify"}]
    _request(project, changes, monkeypatch)
    path = project / "quality" / "project.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["thresholds"]["structure"]["max_cyclomatic_complexity"] -= 1
    write_json(path, payload)
    report = validate_policy_maintenance(project, load_policy(project), "HEAD")
    assert report["exit_code"] == PASS
    assert report["classifications"][0]["classification"] == "strengthening"


def test_weaker_threshold_requires_real_human_authority(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changes = [{"path": "quality/project.json", "operation": "modify"}]
    _request(project, changes, monkeypatch)
    path = project / "quality" / "project.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["thresholds"]["coverage"]["lines"] -= 1
    write_json(path, payload)

    rejected = validate_policy_maintenance(project, load_policy(project), "HEAD")
    assert rejected["exit_code"] == QUALITY_FAILURE
    assert rejected["human_authority_required"] is True
    assert rejected["classifications"][0]["classification"] == "weakening"
    assert any("missing" in error for error in rejected["human_authority_errors"])

    _approve(project, changes)
    accepted = validate_policy_maintenance(project, load_policy(project), "HEAD")
    assert accepted["exit_code"] == PASS


def test_removing_required_gate_or_protected_path_is_weakening(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changes = [{"path": "quality/policy.toml", "operation": "modify"}]
    _request(project, changes, monkeypatch)
    path = project / "quality" / "policy.toml"
    text = path.read_text(encoding="utf-8")
    text = text.replace('gates = ["format", "lint", "typecheck"]', 'gates = ["format", "lint"]')
    text = text.replace('  "CLAUDE.md",\n', "")
    path.write_text(text, encoding="utf-8")
    report = validate_policy_maintenance(project, load_policy(project), "HEAD")
    assert report["exit_code"] == QUALITY_FAILURE
    assert report["classifications"][0]["classification"] == "weakening"
    assert any(
        "profiles.inner.gates: weakening" in reason
        for reason in report["classifications"][0]["reasons"]
    )


def test_local_request_is_scoped_and_explicitly_non_authorizing(project: Path) -> None:
    change = parse_change_spec("modify:quality/policy.toml")
    report = create_maintenance_request(
        project,
        [change],
        reason="Prepare a reviewed policy adjustment",
        requester="builder@example.test",
    )
    request = load_maintenance_request(project, report["request_id"])
    assert request["authorized_changes"] == [change]
    assert request["authority"] == "none"
    assert request["state"] == "proposed"
    assert not (project / "quality" / "approvals" / "policy-maintenance.json").exists()

    with pytest.raises(ConfigurationError, match="not a protected"):
        create_maintenance_request(
            project,
            [{"path": "app.py", "operation": "modify"}],
            reason="invalid broad request",
        )


def test_pre_edit_request_remains_valid_after_candidate_commit(project: Path) -> None:
    change = parse_change_spec("modify:quality/policy.toml")
    created = create_maintenance_request(
        project,
        [change],
        reason="Prepare a comment-only policy clarification",
    )
    policy_path = project / "quality" / "policy.toml"
    policy_path.write_text(policy_path.read_text() + "\n# clarified\n", encoding="utf-8")
    _git(project, "add", "quality/policy.toml")
    _git(project, "commit", "-qm", "clarify policy")
    loaded = load_maintenance_request(project, created["request_id"])
    assert (
        loaded["source_revision"]
        != subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=project, text=True, capture_output=True, check=True
        ).stdout.strip()
    )
