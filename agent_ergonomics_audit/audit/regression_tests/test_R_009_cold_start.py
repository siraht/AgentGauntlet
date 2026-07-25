from __future__ import annotations

import json

from conftest import run_qg


def test_empty_human_and_machine_invocations_are_self_describing() -> None:
    human = run_qg()
    machine = run_qg("--json")
    assert human.returncode == machine.returncode == 0
    assert "Constraint-first quality control" in human.stdout
    payload = json.loads(machine.stdout)
    assert payload["contract_version"] == "1.0"
    assert payload["commands"]
