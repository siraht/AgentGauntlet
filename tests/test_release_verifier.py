# Feature-Spec: AgentQualityGauntlet AQG-CORE-023
"""End-to-end contracts for independently verifiable portable releases."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_BUILD = _module("aqg_test_build_release", ROOT / "scripts" / "build_release.py")
_VERIFY = _module("aqg_test_verify_release", ROOT / "scripts" / "verify_release.py")
build = _BUILD.build
verify_release = _VERIFY.verify_release


def test_built_release_verifies_and_byte_tampering_is_rejected() -> None:
    with tempfile.TemporaryDirectory(prefix="aqg-release-verifier-") as temporary:
        output = Path(temporary)
        result = build(output)

        verified = verify_release(output)
        assert verified["status"] == "verified", verified["errors"]
        assert Path(result["portable"]).name in verified["artifacts"]
        assert "provenance.intoto.json" in verified["artifacts"]

        executable = output / "aqg.pyz"
        executable.write_bytes(executable.read_bytes() + b"tampered")
        rejected = verify_release(output, smoke=False)
        assert rejected["status"] == "invalid"
        assert "checksum mismatch for aqg.pyz" in rejected["errors"]


def test_release_verifier_rejects_unlisted_archive_content() -> None:
    with tempfile.TemporaryDirectory(prefix="aqg-release-verifier-") as temporary:
        output = Path(temporary)
        result = build(output)
        portable = Path(result["portable"])
        data = portable.read_bytes()
        portable.write_bytes(data + b"not-a-valid-central-directory")

        rejected = verify_release(output, smoke=False)
        assert rejected["status"] == "invalid"
        assert any("checksum mismatch" in error for error in rejected["errors"])


def test_release_verifier_rejects_unchecksummed_files_and_sidecar_tampering() -> None:
    with tempfile.TemporaryDirectory(prefix="aqg-release-verifier-") as temporary:
        output = Path(temporary)
        build(output)
        (output / "unreviewed.bin").write_bytes(b"candidate-controlled extra")

        rejected = verify_release(output, smoke=False)

        assert rejected["status"] == "invalid"
        assert any("unexpected=['unreviewed.bin']" in error for error in rejected["errors"])

        (output / "unreviewed.bin").unlink()
        (output / "aqg.pyz.sha256").write_text("0" * 64 + "  aqg.pyz\n", encoding="utf-8")
        rejected_sidecar = verify_release(output, smoke=False)
        assert rejected_sidecar["status"] == "invalid"
        assert "checksum sidecar does not exactly bind aqg.pyz" in rejected_sidecar["errors"]


def test_publish_workflow_requires_exact_tag_risk_selected_evidence() -> None:
    # Feature-Spec: AgentQualityGauntlet AQG-CORE-020 AQG-CORE-025 AQG-CORE-028
    workflow = (ROOT / ".github" / "workflows" / "publish-release.yml").read_text(encoding="utf-8")

    authority = workflow.index("name: Verify authority before candidate execution")
    quality = workflow.index("name: Prove risk-selected and release profiles with trusted grader")
    publish = workflow.index("name: Publish immutable artifacts")
    assert authority < quality
    assert quality < publish
    assert "AQG_DIFF_BASE: ${{ inputs.comparison_sha }}" in workflow
    assert "HEAD^" not in workflow
    assert "python3 quality/qg.py tools install --ci --browsers" in workflow
    assert "../trusted/quality/qg.py --root . check-risk" in workflow
    assert "../trusted/quality/qg.py --root . evidence verify --run-id latest" in workflow
