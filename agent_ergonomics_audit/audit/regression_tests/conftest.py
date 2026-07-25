from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def run_qg(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROOT / "qg"), *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
