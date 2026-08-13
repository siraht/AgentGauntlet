# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-011
"""Adversarial contracts for manifested base-controlled verifier evidence."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from aqg.trusted_verification import (
    verify_trusted_verifier_evidence,
    write_trusted_verifier_evidence,
)
from aqg.util import change_fingerprint, control_fingerprint, git_revision


@dataclass(frozen=True)
class TrustFixture:
    subject: Path
    trusted: Path
    launcher: Path
    runtime: Path
    evidence_dir: Path
    scope: dict[str, str]
    manifest_sha256: str


def _git(root: Path, *arguments: str) -> None:
    completed = subprocess.run(
        ["git", *arguments], cwd=root, text=True, capture_output=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


@pytest.fixture
def trust_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TrustFixture:
    subject = tmp_path / "subject"
    trusted = tmp_path / "trusted"
    subject.mkdir()
    (subject / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(subject, "init", "-q")
    _git(subject, "config", "user.email", "trust@example.invalid")
    _git(subject, "config", "user.name", "Trust Test")
    _git(subject, "add", "app.py")
    _git(subject, "commit", "-qm", "seed")
    quality = trusted / "quality"
    quality.mkdir(parents=True)
    launcher = quality / "qg.py"
    policy = quality / "policy.toml"
    project = quality / "project.json"
    launcher.write_text("print('trusted')\n", encoding="utf-8")
    policy.write_text("version = 2\n", encoding="utf-8")
    project.write_text("{}\n", encoding="utf-8")
    runtime = trusted / "src" / "aqg" / "runtime.py"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("VALUE = 'trusted'\n", encoding="utf-8")
    base = "HEAD"
    evidence_dir = tmp_path / "trusted-verifier"
    created = write_trusted_verifier_evidence(
        subject,
        evidence_dir,
        base_revision=base,
        trusted_root=trusted,
        trusted_launcher=launcher,
        trusted_policy=policy,
        trusted_project=project,
    )
    environment = {
        "AQG_TRUSTED_MODE": "1",
        "AQG_TRUSTED_LAUNCHER": str(launcher.resolve()),
        "AQG_TRUSTED_POLICY_PATH": str(policy.resolve()),
        "AQG_TRUSTED_PROJECT_PATH": str(project.resolve()),
        "AQG_TRUSTED_TOOLCHAIN_ROOT": str(trusted.resolve()),
        "AQG_TRUSTED_EVIDENCE_DIR": str(evidence_dir.resolve()),
        "AQG_TRUSTED_EVIDENCE_MANIFEST_SHA256": str(created["manifest_sha256"]),
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    scope = {
        "revision": git_revision(subject),
        "base_ref": base,
        "change_fingerprint": change_fingerprint(subject, base),
        "control_fingerprint": control_fingerprint(subject),
    }
    return TrustFixture(
        subject=subject,
        trusted=trusted,
        launcher=launcher,
        runtime=runtime,
        evidence_dir=evidence_dir,
        scope=scope,
        manifest_sha256=str(created["manifest_sha256"]),
    )


def test_manifested_exact_candidate_trusted_evidence_passes(
    trust_fixture: TrustFixture,
) -> None:
    report = verify_trusted_verifier_evidence(trust_fixture.subject, trust_fixture.scope)
    assert report["status"] == "works"
    assert report["manifest"]["ok"] is True
    assert report["manifest_sha256"] == trust_fixture.manifest_sha256


def test_trusted_environment_without_manifested_evidence_is_unusable(
    trust_fixture: TrustFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AQG_TRUSTED_EVIDENCE_DIR")
    monkeypatch.delenv("AQG_TRUSTED_EVIDENCE_MANIFEST_SHA256")
    report = verify_trusted_verifier_evidence(trust_fixture.subject, trust_fixture.scope)
    assert report["status"] == "unusable"
    assert any("AQG_TRUSTED_EVIDENCE_DIR" in error for error in report["errors"])


def test_stale_candidate_scope_is_rejected(trust_fixture: TrustFixture) -> None:
    stale = {**trust_fixture.scope, "revision": "different"}
    report = verify_trusted_verifier_evidence(trust_fixture.subject, stale)
    assert report["status"] == "unusable"
    assert any("exact candidate scope" in error for error in report["errors"])


def test_tampered_evidence_and_replaced_manifest_are_rejected(
    trust_fixture: TrustFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_dir = trust_fixture.evidence_dir
    statement = evidence_dir / "verifier.json"
    statement.write_text(statement.read_text() + " ", encoding="utf-8")
    report = verify_trusted_verifier_evidence(trust_fixture.subject, trust_fixture.scope)
    assert report["status"] == "unusable"
    assert any("modified evidence" in error for error in report["errors"])

    manifest = evidence_dir / "manifest.json"
    manifest.write_text(manifest.read_text().replace("0", "1", 1), encoding="utf-8")
    monkeypatch.setenv("AQG_TRUSTED_EVIDENCE_MANIFEST_SHA256", "sha256:" + "0" * 64)
    report = verify_trusted_verifier_evidence(trust_fixture.subject, trust_fixture.scope)
    assert any("external digest anchor" in error for error in report["errors"])


def test_candidate_controlled_evidence_location_is_rejected(
    trust_fixture: TrustFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject = trust_fixture.subject
    monkeypatch.setenv("AQG_TRUSTED_EVIDENCE_DIR", str(subject))
    report = verify_trusted_verifier_evidence(subject, trust_fixture.scope)
    assert report["status"] == "unusable"
    assert any("outside the candidate root" in error for error in report["errors"])


def test_trusted_grader_mutation_after_attestation_is_rejected(
    trust_fixture: TrustFixture,
) -> None:
    trust_fixture.launcher.write_text("print('candidate changed grader')\n", encoding="utf-8")
    report = verify_trusted_verifier_evidence(trust_fixture.subject, trust_fixture.scope)
    assert report["status"] == "unusable"
    assert any("current trusted grader" in error for error in report["errors"])


def test_imported_trusted_runtime_mutation_after_attestation_is_rejected(
    trust_fixture: TrustFixture,
) -> None:
    trust_fixture.runtime.write_text("VALUE = 'candidate replacement'\n", encoding="utf-8")
    report = verify_trusted_verifier_evidence(trust_fixture.subject, trust_fixture.scope)
    assert report["status"] == "unusable"
    assert any("current trusted grader" in error for error in report["errors"])
