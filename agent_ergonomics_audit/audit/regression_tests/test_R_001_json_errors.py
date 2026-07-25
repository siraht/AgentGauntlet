from __future__ import annotations

import json

from conftest import run_qg


def test_json_failures_keep_data_and_diagnostics_separate() -> None:
    result = run_qg("golden", "--json")
    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["status"] == "error"
    assert payload["error"]["category"] == "configuration_error"
    assert "configuration error:" in result.stderr
