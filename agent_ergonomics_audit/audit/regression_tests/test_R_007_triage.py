from __future__ import annotations

import json

from conftest import run_qg


def test_triage_returns_orientation_and_exact_next_commands() -> None:
    result = run_qg("triage", "--json")
    payload = json.loads(result.stdout)
    assert result.returncode in {0, 2}
    assert {"project", "readiness", "risk", "latest", "commands"} <= payload.keys()
    assert "qg doctor" in payload["commands"]
    assert "qg check-risk --keep-going" in payload["commands"]
