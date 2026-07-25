from __future__ import annotations

import json

from conftest import run_qg


def test_robot_docs_contains_copy_pasteable_safe_workflows() -> None:
    result = run_qg("robot-docs", "guide", "--json")
    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert "qg check-risk --keep-going" in payload["workflows"]["high_assurance"]
    assert any("Do not weaken policy" in rule for rule in payload["safety_rules"])
