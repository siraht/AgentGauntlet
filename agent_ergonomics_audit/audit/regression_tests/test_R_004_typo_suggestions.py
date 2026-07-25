from __future__ import annotations

from conftest import run_qg


def test_nearby_flag_and_nested_verb_typos_get_exact_corrections() -> None:
    flag = run_qg("capabilities", "--jsno")
    nested = run_qg("onboarding", "refrsh")
    assert flag.returncode == nested.returncode == 2
    assert "qg capabilities --json" in flag.stderr
    assert "qg onboarding refresh" in nested.stderr
