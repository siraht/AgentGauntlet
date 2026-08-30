# Feature-Spec: AgentQualityGauntlet AQG-CORE-029 AQG-CORE-030
"""Focused contracts for adapter-facing source, ABC, and resource budgets."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from aqg.budget_integration import (
    JS_ABC_PREFIX,
    collect_javascript_abc,
    measure_resource_budget,
    source_budget_evidence,
)
from aqg.constants import PASS, QUALITY_FAILURE
from aqg.errors import ConfigurationError


def _run_git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        check=True,
        text=True,
    )


def _committed_repository(tmp_path: Path, files: dict[str, str]) -> Path:
    _run_git(tmp_path, "init", "--quiet")
    _run_git(tmp_path, "config", "user.email", "tests@example.invalid")
    _run_git(tmp_path, "config", "user.name", "AQG Tests")
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _run_git(tmp_path, "add", ".")
    _run_git(tmp_path, "commit", "--quiet", "-m", "baseline")
    return tmp_path


def _source_thresholds() -> dict[str, int]:
    return {
        "warn_source_file_lines": 2,
        "max_source_file_lines": 3,
        "warn_css_file_lines": 2,
        "max_css_file_lines": 3,
        "warn_test_file_lines": 4,
        "max_test_file_lines": 5,
        "warn_source_file_bytes": 1_000,
        "max_source_file_bytes": 2_000,
    }


def _source_evidence(root: Path, path: str, *, base_ref: str = "HEAD") -> dict[str, Any]:
    return source_budget_evidence(
        root,
        {},
        [path],
        thresholds=_source_thresholds(),
        base_ref=base_ref,
        adopt_mode=True,
        is_test_path=lambda _path: False,
    )


@pytest.mark.parametrize(
    "current",
    [
        "first\nsecond\nthird\n",
        "a\nb\nc\n",
    ],
    ids=["unchanged", "modified-but-not-growing"],
)
def test_inherited_over_limit_source_is_visible_but_nonblocking(
    tmp_path: Path, current: str
) -> None:
    path = "src/inherited.py"
    root = _committed_repository(tmp_path, {path: "first\nsecond\nthird\n"})
    (root / path).write_text(current, encoding="utf-8")

    evidence = _source_evidence(root, path)
    item = evidence["files"][0]

    assert evidence["scope"] == "changed-files"
    assert evidence["status"] == "hard_failure"
    assert evidence["failures"] == []
    assert item["status"] == "hard_failure"
    assert item["debt_origin"] == "inherited_git_base"
    assert item["enforced"] is False
    assert item["regressed_metrics"] == []
    assert item["base"]["status"] == "hard_failure"


def test_growth_of_inherited_over_limit_source_is_blocking(tmp_path: Path) -> None:
    path = "src/growing.py"
    root = _committed_repository(tmp_path, {path: "one\ntwo\nthree\n"})
    (root / path).write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    evidence = _source_evidence(root, path)
    item = evidence["files"][0]

    assert item["debt_origin"] == "regression"
    assert item["enforced"] is True
    assert item["regressed_metrics"] == ["physical_lines"]
    assert evidence["failures"] == [
        "src/growing.py exceeds source-file budget: physical_lines 4 >= 3"
    ]


def test_new_oversized_source_file_is_blocking(tmp_path: Path) -> None:
    root = _committed_repository(tmp_path, {"README.md": "baseline\n"})
    path = "src/new.py"
    (root / "src").mkdir()
    (root / path).write_text("one\ntwo\nthree\n", encoding="utf-8")

    evidence = _source_evidence(root, path)
    item = evidence["files"][0]

    assert item["debt_origin"] == "new_file"
    assert item["enforced"] is True
    assert evidence["failures"] == ["src/new.py exceeds source-file budget: physical_lines 3 >= 3"]


def test_unresolvable_source_budget_base_fails_closed(tmp_path: Path) -> None:
    path = "src/large.py"
    root = _committed_repository(tmp_path, {path: "one\ntwo\nthree\n"})

    with pytest.raises(ConfigurationError, match="comparison base does not resolve"):
        _source_evidence(root, path, base_ref="missing-aqg-base")


def _abc_message(**overrides: Any) -> dict[str, Any]:
    measurement: dict[str, Any] = {
        "definition": "aqg-javascript-abc-v1",
        "function": "calculate",
        "function_kind": "ArrowFunctionExpression",
        "async": True,
        "generator": False,
        "vector": {"assignments": 3, "branches": 4, "conditions": 0},
        "vector_text": "<3,4,0>",
        "magnitude_squared": 25,
        "magnitude": 5,
        "location": {"line": 4, "column": 7, "end_line": 8, "end_column": 2},
    }
    measurement.update(overrides)
    return {
        "ruleId": "aqg-abc/report",
        "severity": 1,
        "message": JS_ABC_PREFIX + json.dumps(measurement, sort_keys=True),
        "line": 4,
        "column": 7,
        "endLine": 8,
        "endColumn": 2,
    }


def test_javascript_abc_is_normalized_and_enforced_only_for_changed_function() -> None:
    path = "src/calculate.ts"
    limits = {"max_abc_score": 4}

    inherited, inherited_failure = collect_javascript_abc(
        path, _abc_message(), {}, limits, adopt_mode=True
    )
    changed, changed_failure = collect_javascript_abc(
        path, _abc_message(), {path: {6}}, limits, adopt_mode=True
    )

    assert inherited["enforced"] is False
    assert inherited_failure is None
    assert changed == {
        "path": path,
        "name": "calculate",
        "line": 4,
        "end_line": 8,
        "assignments": 3,
        "branches": 4,
        "conditions": 0,
        "abc_magnitude": 5.0,
        "abc_magnitude_squared": 25,
        "abc_definition": "aqg-javascript-abc-v1",
        "enforced": True,
    }
    assert changed_failure == "src/calculate.ts:4 calculate ABC 5.000000 > 4"


def test_malformed_javascript_abc_evidence_fails_closed() -> None:
    with pytest.raises(ConfigurationError, match="invalid JSON"):
        collect_javascript_abc(
            "src/broken.js",
            {"message": JS_ABC_PREFIX + "{"},
            {},
            {"max_abc_score": 20},
            adopt_mode=False,
        )


def _resource_thresholds(value: int = 10_000) -> dict[str, int | float]:
    limits: dict[str, int | float] = {
        f"max_{kind}_{scope}_{encoding}_bytes": value
        for kind in ("javascript", "css")
        for scope in ("file", "total")
        for encoding in ("raw", "gzip")
    }
    limits["warning_ratio"] = 0.8
    return limits


def test_source_static_resource_budget_passes_without_running_build(tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "app.js").write_text("export default 1;\n", encoding="utf-8")
    (static / "app.css").write_text("body { color: red; }\n", encoding="utf-8")

    code, payload = measure_resource_budget(
        tmp_path,
        {"mode": "source_static", "roots": ["static"], "build_command": None},
        _resource_thresholds(),
    )

    assert code == PASS
    assert payload["mode"] == "source_static"
    assert payload["commands"] == []
    assert payload["failures"] == []
    assert payload["metrics"]["summary"]["status"] == "pass"
    assert [item["path"] for item in payload["metrics"]["artifacts"]] == [
        "static/app.css",
        "static/app.js",
    ]


def test_source_static_resource_budget_returns_quality_failure(tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "app.js").write_bytes(b"12345")
    limits = _resource_thresholds()
    limits["max_javascript_file_raw_bytes"] = 4

    code, payload = measure_resource_budget(
        tmp_path,
        {"mode": "source_static", "roots": ["static"], "build_command": None},
        limits,
    )

    assert code == QUALITY_FAILURE
    assert payload["commands"] == []
    assert payload["metrics"]["summary"]["status"] == "failure"
    assert payload["failures"] == ["static/app.js file_raw_bytes 5 > 4"]
    assert any(
        finding["scope"] == "static/app.js"
        and finding["metric"] == "file_raw_bytes"
        and finding["status"] == "failure"
        for finding in payload["findings"]
    )
