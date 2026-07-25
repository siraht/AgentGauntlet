from __future__ import annotations

from conftest import run_qg


def test_help_is_stable_and_hides_managed_runtime_commands() -> None:
    result = run_qg("--help")
    assert result.returncode == 0
    assert "\ncommands:\n" in result.stdout
    assert "capabilities" in result.stdout
    assert "adapter" not in result.stdout
    assert "hook-pretool" not in result.stdout
    assert "==SUPPRESS==" not in result.stdout
