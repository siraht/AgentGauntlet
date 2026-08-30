# Feature-Spec: AgentQualityGauntlet AQG-CORE-022 AQG-CORE-029
"""Changed-function no-regression contracts for Python structure metrics."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aqg.errors import ConfigurationError
from aqg.python_structure_metrics import python_structure_evidence

LIMITS = {
    "max_cyclomatic_complexity": 1,
    "max_function_lines": 4,
    "max_nesting_depth": 0,
    "max_abc_score": 3,
}

BASE_LEGACY = """\
def legacy(flag):
    value = compute(flag)
    if flag:
        if value:
            return compute(value)
    return value
"""

UNCHANGED_DEBT = """\
def legacy(flag):
    value = compute(flag)
    if flag:
        if value:
            return compute(value)
    return value + 1
"""

REGRESSED_DEBT = """\
def legacy(flag):
    value = compute(flag)
    extra = compute(value)
    if flag:
        if value:
            if extra:
                return compute(extra)
    return value
"""

SAFE_SOURCE = """\
def safe():
    return 1
"""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)


def _initialize_repository(root: Path, source: str) -> Path:
    assert _git(root, "init", "-q").returncode == 0
    assert _git(root, "config", "user.name", "AQG Test").returncode == 0
    assert _git(root, "config", "user.email", "aqg@example.invalid").returncode == 0
    path = root / "module.py"
    path.write_text(source, encoding="utf-8")
    assert _git(root, "add", "module.py").returncode == 0
    assert _git(root, "commit", "-qm", "base").returncode == 0
    return path


def _block(*, endline: int, complexity: int, name: str = "legacy", lineno: int = 1) -> dict:
    return {
        "type": "function",
        "name": name,
        "lineno": lineno,
        "endline": endline,
        "complexity": complexity,
    }


def _evidence(
    root: Path,
    payload: list[dict],
    changed: set[int],
    base_ref: str = "HEAD",
    base_payload: list[dict] | None = None,
) -> dict:
    return python_structure_evidence(
        root,
        ["module.py"],
        {"module.py": payload},
        LIMITS,
        {"module.py": changed},
        adopt_mode=True,
        base_ref=base_ref,
        base_payload=None if base_payload is None else {"module.py": base_payload},
    )


def test_unchanged_inherited_overages_remain_visible_but_nonblocking(tmp_path: Path) -> None:
    path = _initialize_repository(tmp_path, BASE_LEGACY)
    path.write_text(UNCHANGED_DEBT, encoding="utf-8")

    block = _block(endline=6, complexity=3)
    evidence = _evidence(tmp_path, [block], {6}, base_payload=[block])
    function = evidence["functions"][0]

    assert function["enforced"] is True
    assert function["complexity"] > LIMITS["max_cyclomatic_complexity"]
    assert function["lines"] > LIMITS["max_function_lines"]
    assert function["nesting"] > LIMITS["max_nesting_depth"]
    assert function["abc_magnitude"] > LIMITS["max_abc_score"]
    assert evidence["failures"] == []


def test_worsened_inherited_structure_is_a_blocking_regression(tmp_path: Path) -> None:
    path = _initialize_repository(tmp_path, BASE_LEGACY)
    path.write_text(REGRESSED_DEBT, encoding="utf-8")

    evidence = _evidence(
        tmp_path,
        [_block(endline=8, complexity=4)],
        {2, 3, 6, 7},
        base_payload=[_block(endline=6, complexity=3)],
    )
    failures = "\n".join(evidence["failures"])

    assert "complexity" in failures
    assert "lines" in failures
    assert "nesting" in failures
    assert "abc_magnitude" in failures


def test_new_over_limit_function_is_blocking(tmp_path: Path) -> None:
    path = _initialize_repository(tmp_path, SAFE_SOURCE)
    path.write_text(SAFE_SOURCE + "\n" + BASE_LEGACY, encoding="utf-8")
    payload = [
        _block(name="safe", lineno=1, endline=2, complexity=1),
        _block(name="legacy", lineno=4, endline=9, complexity=3),
    ]

    evidence = _evidence(
        tmp_path,
        payload,
        set(range(4, 10)),
        base_payload=[_block(name="safe", endline=2, complexity=1)],
    )
    failures = "\n".join(evidence["failures"])

    assert "complexity" in failures
    assert "lines" in failures
    assert "nesting" in failures
    assert "abc_magnitude" in failures


def test_missing_comparison_revision_fails_closed(tmp_path: Path) -> None:
    _initialize_repository(tmp_path, SAFE_SOURCE)

    with pytest.raises(ConfigurationError, match="comparison base does not resolve"):
        _evidence(
            tmp_path,
            [_block(name="safe", endline=2, complexity=1)],
            {2},
            "missing",
            [_block(name="safe", endline=2, complexity=1)],
        )


def test_missing_base_complexity_payload_fails_closed(tmp_path: Path) -> None:
    _initialize_repository(tmp_path, SAFE_SOURCE)

    with pytest.raises(ConfigurationError, match="base Python complexity evidence is required"):
        _evidence(tmp_path, [_block(name="safe", endline=2, complexity=1)], {2})


def test_invalid_base_source_fails_closed(tmp_path: Path) -> None:
    path = _initialize_repository(tmp_path, "def broken(:\n")
    path.write_text(SAFE_SOURCE, encoding="utf-8")

    with pytest.raises(ConfigurationError, match="unable to measure base Python"):
        block = _block(name="safe", endline=2, complexity=1)
        _evidence(tmp_path, [block], {1, 2}, base_payload=[block])
