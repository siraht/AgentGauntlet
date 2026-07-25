from __future__ import annotations

import json
import subprocess
import tempfile

from conftest import ROOT


def test_embedded_guidance_is_searchable_without_a_project() -> None:
    with tempfile.TemporaryDirectory(prefix="aqg-cold-guidance-") as cwd:
        completed = subprocess.run(
            [str(ROOT / "qg"), "guidance", "mutation", "testing", "--json"],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
    assert completed.returncode == 0
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    assert any(item["topic"] == "mutation-testing" for item in payload)
