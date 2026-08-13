# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-011
"""Executable workflow contracts for externally anchored trusted evidence."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

from aqg.trusted_verification import verify_trusted_verifier_evidence

ROOT = Path(__file__).resolve().parents[1]


def _git(root: Path, *arguments: str) -> None:
    completed = subprocess.run(
        ["git", *arguments], cwd=root, text=True, capture_output=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


def test_trusted_workflow_generates_external_manifest_anchor_before_check() -> None:
    workflow = (ROOT / ".github" / "workflows" / "trusted-policy-evidence.yml").read_text(
        encoding="utf-8"
    )
    evidence = workflow.index("write_trusted_verifier_evidence.py")
    check = workflow.index("check-risk --keep-going --quiet")
    assert evidence < check
    assert '--output "${RUNNER_TEMP}/aqg-trusted-verifier-' in workflow
    assert '--github-env "${GITHUB_ENV}"' in workflow


def test_workflow_writer_emits_verifiable_environment_anchor(tmp_path: Path) -> None:
    subject = tmp_path / "subject"
    trusted = tmp_path / "trusted"
    subject.mkdir()
    _git(subject, "init", "-q")
    _git(subject, "config", "user.email", "workflow@example.invalid")
    _git(subject, "config", "user.name", "Workflow Test")
    (subject / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(subject, "add", "app.py")
    _git(subject, "commit", "-qm", "seed")
    quality = trusted / "quality"
    quality.mkdir(parents=True)
    (quality / "qg.py").write_text("print('trusted')\n", encoding="utf-8")
    (quality / "policy.toml").write_text("version = 2\n", encoding="utf-8")
    (quality / "project.json").write_text("{}\n", encoding="utf-8")
    runtime = trusted / "src" / "aqg" / "runtime.py"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("VALUE = 'trusted'\n", encoding="utf-8")
    github_env = tmp_path / "github.env"
    output = tmp_path / "verifier-evidence"
    completed = subprocess.run(
        [
            "python3",
            str(ROOT / "scripts" / "write_trusted_verifier_evidence.py"),
            "--subject",
            str(subject),
            "--trusted-root",
            str(trusted),
            "--base-revision",
            "HEAD",
            "--output",
            str(output),
            "--github-env",
            str(github_env),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    variables = dict(
        line.split("=", 1) for line in github_env.read_text(encoding="utf-8").splitlines()
    )
    environment = {
        "AQG_TRUSTED_MODE": "1",
        "AQG_TRUSTED_LAUNCHER": str((quality / "qg.py").resolve()),
        "AQG_TRUSTED_POLICY_PATH": str((quality / "policy.toml").resolve()),
        "AQG_TRUSTED_PROJECT_PATH": str((quality / "project.json").resolve()),
        "AQG_TRUSTED_TOOLCHAIN_ROOT": str(trusted.resolve()),
        **variables,
    }
    payload = json.loads((output / "verifier.json").read_text(encoding="utf-8"))
    with mock.patch.dict("os.environ", environment, clear=False):
        report = verify_trusted_verifier_evidence(subject, payload["scope"])
    assert report["status"] == "works"
