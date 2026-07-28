from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def run_qg(
    *arguments: str,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process_environment = os.environ.copy()
    if environment:
        process_environment.update(environment)
    return subprocess.run(
        [str(ROOT / "qg"), *arguments],
        cwd=ROOT,
        env=process_environment,
        text=True,
        capture_output=True,
        check=False,
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    marker = pytest.mark.mutation_incompatible
    for item in items:
        if Path(str(item.path)).is_relative_to(Path(__file__).parent):
            item.add_marker(marker)
