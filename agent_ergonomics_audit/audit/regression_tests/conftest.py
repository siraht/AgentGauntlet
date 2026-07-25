from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def run_qg(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROOT / "qg"), *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    marker = pytest.mark.mutation_incompatible
    for item in items:
        if Path(str(item.path)).is_relative_to(Path(__file__).parent):
            item.add_marker(marker)
