# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-003 AQG-RETRO-005
"""Stable test-integrity identity contracts."""

from __future__ import annotations

from pathlib import Path

from aqg.checks import scan_test_integrity

PROJECT = {"paths": {"exclude": [], "source": ["src"], "tests": ["tests"]}}


def _fingerprints(root: Path) -> list[str]:
    return [
        finding["fingerprint"]
        for finding in scan_test_integrity(root, PROJECT)["findings"]
        if finding["code"] in {"skipped-test", "runtime-skip"}
    ]


def test_python_skip_fingerprints_use_test_names_not_line_numbers(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    path = tests / "test_app.py"
    body = (
        "import pytest\n\n"
        "@pytest.mark.skip\n"
        "def test_first():\n    assert True\n\n"
        "def test_second():\n    pytest.skip('reason')\n"
    )
    path.write_text(body, encoding="utf-8")
    first = _fingerprints(tmp_path)
    path.write_text("\n\n" + body, encoding="utf-8")
    second = _fingerprints(tmp_path)
    assert first == second
    assert first == [
        "skipped-test:tests/test_app.py:test_first:@pytest.mark.skip",
        "runtime-skip:tests/test_app.py:test_second:pytest.skip(",
    ]


def test_distinct_skipped_tests_do_not_collapse(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "app.test.js").write_text(
        "test.skip('first behavior', () => {});\ntest.skip('second behavior', () => {});\n",
        encoding="utf-8",
    )
    fingerprints = _fingerprints(tmp_path)
    assert len(fingerprints) == 2
    assert fingerprints[0] != fingerprints[1]
    assert "first behavior" in fingerprints[0]
    assert "second behavior" in fingerprints[1]
