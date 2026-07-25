from __future__ import annotations

import json

from conftest import run_qg


def test_help_first_order_supports_nested_paths_and_json() -> None:
    nested = run_qg("help", "onboarding", "refresh")
    structured = run_qg("help", "check", "--json")
    assert nested.returncode == structured.returncode == 0
    assert "usage: qg onboarding refresh" in nested.stdout
    assert json.loads(structured.stdout)["path"] == ["check"]
