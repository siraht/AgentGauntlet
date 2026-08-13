# Feature-Spec: AgentQualityGauntlet AQG-CORE-019 AQG-CORE-020 AQG-CORE-021
"""Contracts for exact-tag, base-controlled release authority."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


VERIFY = _module(
    "aqg_test_verify_release_authority", ROOT / "scripts" / "verify_release_authority.py"
)


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=root, text=True, capture_output=True, check=True
    )
    return completed.stdout.strip()


def _repository(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / "subject"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "aqg@example.invalid")
    _git(root, "config", "user.name", "AQG Test")
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(root, "add", "app.py")
    _git(root, "commit", "-q", "-m", "base")
    base = _git(root, "rev-parse", "HEAD")
    (root / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    _git(root, "commit", "-q", "-am", "candidate")
    revision = _git(root, "rev-parse", "HEAD")
    _git(root, "tag", "v1.2.3")
    return root, base, revision


def _clear_report(root: Path, base: str, revision: str) -> dict[str, Any]:
    return {
        "tier": "high",
        "purpose": "candidate",
        "status": "advisory_clear",
        "complete": True,
        "blockers": [],
        "dissent": {"present": False},
        "incomplete_reasons": [],
        "covered_roles": sorted(VERIFY.ROLES),
        "provider_groups": ["grok", "codex", "opencode"],
        "scope": {
            "revision": revision,
            "base_revision": base,
            "change_fingerprint": VERIFY.change_fingerprint(root, base),
            "control_fingerprint": VERIFY.control_fingerprint(root),
        },
        "verification": {"manifest": {"manifest_sha256": "sha256:" + "a" * 64}},
    }


def test_exact_tag_high_council_authorizes_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, base, revision = _repository(tmp_path)
    monkeypatch.setattr(
        VERIFY, "report_council", lambda _root, _run: _clear_report(root, base, revision)
    )

    report = VERIFY.verify_release_authority(
        root, tag="v1.2.3", comparison_sha=base, council_run_id="council-exact"
    )

    assert report["status"] == "verified"
    assert report["revision"] == revision
    assert report["comparison_revision"] == base
    assert report["errors"] == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda report: report.update(tier="pr"), "not high tier"),
        (lambda report: report.update(status="advisory_blocked"), "advisory_clear"),
        (lambda report: report["dissent"].update(present=True), "contains dissent"),
        (lambda report: report["scope"].update(base_revision="wrong"), "scope does not match"),
    ],
)
def test_release_authority_rejects_weak_or_mismatched_council(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Any,
    expected: str,
) -> None:
    root, base, revision = _repository(tmp_path)
    council = _clear_report(root, base, revision)
    mutate(council)
    monkeypatch.setattr(VERIFY, "report_council", lambda _root, _run: council)

    report = VERIFY.verify_release_authority(
        root, tag="v1.2.3", comparison_sha=base, council_run_id="council-exact"
    )

    assert report["status"] == "invalid"
    assert any(expected in error for error in report["errors"])


def test_release_authority_rejects_head_as_comparison_and_non_tag_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, base, revision = _repository(tmp_path)
    monkeypatch.setattr(
        VERIFY, "report_council", lambda _root, _run: _clear_report(root, base, revision)
    )

    same = VERIFY.verify_release_authority(
        root, tag="v1.2.3", comparison_sha=revision, council_run_id="council-exact"
    )
    assert "comparison revision must predate the release candidate" in same["errors"]

    _git(root, "commit", "--allow-empty", "-q", "-m", "after-tag")
    wrong_head = VERIFY.verify_release_authority(
        root, tag="v1.2.3", comparison_sha=base, council_run_id="council-exact"
    )
    assert "subject HEAD does not match the exact release tag" in wrong_head["errors"]
