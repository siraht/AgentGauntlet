# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-012
"""Contracts for legitimate, exact policy-maintenance approval."""

from __future__ import annotations

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


def test_protected_change_fails_until_exact_independent_approval(project: Path) -> None:
    policy_path = project / "quality" / "policy.toml"
    policy_path.write_text(policy_path.read_text() + "\n# reviewed candidate change\n")
    policy = load_policy(project)
    changes = protected_changes(project, policy, "HEAD")
    assert changes == [{"path": "quality/policy.toml", "operation": "modify"}]

    missing = validate_policy_maintenance(project, policy, "HEAD")
    assert missing["exit_code"] == QUALITY_FAILURE
    assert any("missing" in error for error in missing["errors"])

    _approve(project, changes)
    approved = validate_policy_maintenance(project, policy, "HEAD")
    assert approved["exit_code"] == PASS
    code, adapter = run_adapter(project, "policy_maintenance")
    assert code == PASS
    assert adapter["changes"] == changes


def test_approval_cannot_authorize_a_different_operation_or_path(project: Path) -> None:
    candidate = project / "quality" / "config" / "new-policy.txt"
    candidate.write_text("candidate\n", encoding="utf-8")
    policy = load_policy(project)
    actual = protected_changes(project, policy, "HEAD")
    assert actual == [{"path": "quality/config/new-policy.txt", "operation": "add"}]
    _approve(
        project,
        [{"path": "quality/config/new-policy.txt", "operation": "modify"}],
    )
    report = validate_policy_maintenance(project, policy, "HEAD")
    assert report["exit_code"] == QUALITY_FAILURE
    assert any("exactly match" in error for error in report["errors"])


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
