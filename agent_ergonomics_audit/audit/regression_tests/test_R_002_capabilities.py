from __future__ import annotations

import json

from conftest import run_qg


def test_capabilities_is_complete_and_deterministic() -> None:
    first = run_qg("capabilities", "--json")
    second = run_qg("capabilities", "--json")
    payload = json.loads(first.stdout)
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    assert set(payload["exit_codes"]) == {"0", "1", "2", "3"}
    assert any(command["path"] == "capabilities" for command in payload["commands"])
