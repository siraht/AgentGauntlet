from __future__ import annotations

from conftest import run_qg


def test_conventional_verbs_teach_safe_canonical_commands() -> None:
    expected = {
        "docs": "qg robot-docs guide",
        "health": "qg doctor",
        "test": "qg check fast",
        "verify": "qg check-risk --keep-going",
    }
    for alias, correction in expected.items():
        result = run_qg(alias)
        assert result.returncode == 2
        assert correction in result.stderr
