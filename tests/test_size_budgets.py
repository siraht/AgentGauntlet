"""Focused contracts for deterministic source-file size budgets."""

from __future__ import annotations

from pathlib import Path

import pytest

from aqg.size_budgets import (
    SizeBudgetError,
    analyze_source_files,
    evaluate_measurement,
    measure_source_bytes,
    normalize_classifications,
    normalize_limits,
    normalize_thresholds,
)

LIMITS = {
    "production": {
        "warning_physical_lines": 2,
        "hard_physical_lines": 3,
        "warning_raw_bytes": 10,
        "hard_raw_bytes": 20,
    },
    "test": {
        "warning_physical_lines": 20,
        "hard_physical_lines": 30,
        "warning_raw_bytes": 100,
        "hard_raw_bytes": 200,
    },
    "css": {
        "warning_physical_lines": 10,
        "hard_physical_lines": 20,
        "warning_raw_bytes": 30,
        "hard_raw_bytes": 40,
    },
}


def _write(root: Path, path: str, content: bytes) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def test_measurement_handles_utf8_empty_and_blank_lines() -> None:
    assert measure_source_bytes(b"") == {
        "physical_lines": 0,
        "nonblank_lines": 0,
        "raw_bytes": 0,
        "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }
    measured = measure_source_bytes("é\n\nword\n".encode())
    assert measured["physical_lines"] == 3
    assert measured["nonblank_lines"] == 2
    assert measured["raw_bytes"] == 9


def test_invalid_utf8_fails_closed() -> None:
    with pytest.raises(SizeBudgetError, match="valid UTF-8"):
        measure_source_bytes(b"\xff")


@pytest.mark.parametrize(
    ("measurement", "expected", "level"),
    [
        ({"physical_lines": 1, "raw_bytes": 9}, "pass", None),
        ({"physical_lines": 2, "raw_bytes": 9}, "warning", "warning"),
        ({"physical_lines": 3, "raw_bytes": 9}, "hard_failure", "hard"),
        ({"physical_lines": 1, "raw_bytes": 10}, "warning", "warning"),
        ({"physical_lines": 1, "raw_bytes": 20}, "hard_failure", "hard"),
    ],
)
def test_exact_warning_and_hard_boundaries(
    measurement: dict, expected: str, level: str | None
) -> None:
    result = evaluate_measurement(measurement, ["production"], LIMITS)
    assert result["status"] == expected
    assert ({item["level"] for item in result["breaches"]} or {None}) == {level}


@pytest.mark.parametrize(
    "limits",
    [
        {},
        {**LIMITS["production"], "extra": 1},
        {**LIMITS["production"], "hard_raw_bytes": -1},
        {**LIMITS["production"], "warning_raw_bytes": 21},
        {**LIMITS["production"], "warning_physical_lines": True},
    ],
)
def test_invalid_limit_configuration_fails_closed(limits: dict) -> None:
    with pytest.raises(SizeBudgetError):
        normalize_limits(limits)


def test_unused_invalid_threshold_configuration_still_fails_closed(tmp_path: Path) -> None:
    invalid = {"production": LIMITS["production"], "css": {}}
    with pytest.raises(SizeBudgetError, match="missing size limit keys"):
        analyze_source_files(tmp_path, [], invalid)
    with pytest.raises(SizeBudgetError, match="unknown threshold classifications"):
        normalize_thresholds({"other": LIMITS["production"]})


def test_classification_is_canonical_and_ambiguous_inputs_fail() -> None:
    assert normalize_classifications(["minified", "css", "generated"]) == (
        "css",
        "generated",
        "minified",
    )
    for value in (["production", "test"], ["production", "production"], [], ["unknown"]):
        with pytest.raises(SizeBudgetError):
            normalize_classifications(value)


def test_excluded_files_are_measured_but_not_enforced(tmp_path: Path) -> None:
    _write(tmp_path, "dist/app.min.js", b"x" * 100)
    result = analyze_source_files(
        tmp_path,
        [{"path": "dist/app.min.js", "classifications": ["generated", "minified"]}],
        LIMITS,
    )
    item = result["files"][0]
    assert item["status"] == "excluded"
    assert item["raw_bytes"] == 100
    assert item["exclusion_reasons"] == ["generated", "minified"]
    assert result["totals"]["excluded_file_count"] == 1


def test_results_and_aggregate_totals_are_deterministic(tmp_path: Path) -> None:
    _write(tmp_path, "src/z.py", b"one\ntwo\nthree\n")
    _write(tmp_path, "tests/a.py", b"test\n")
    files = [
        {"path": "src/z.py", "classifications": ["production"]},
        {"path": "tests/a.py", "classifications": ["test"]},
    ]
    first = analyze_source_files(tmp_path, files, LIMITS)
    second = analyze_source_files(tmp_path, list(reversed(files)), LIMITS)
    assert first == second
    assert [item["path"] for item in first["files"]] == ["src/z.py", "tests/a.py"]
    assert first["status"] == "hard_failure"
    assert first["totals"] == {
        "file_count": 2,
        "physical_lines": 4,
        "nonblank_lines": 4,
        "raw_bytes": 19,
        "statuses": {"pass": 1, "warning": 0, "hard_failure": 1, "excluded": 0},
        "classifications": {
            "production": 1,
            "test": 1,
            "css": 0,
            "generated": 0,
            "vendor": 0,
            "minified": 0,
        },
        "enforced_file_count": 2,
        "excluded_file_count": 0,
    }


@pytest.mark.parametrize(
    "entry",
    [
        {"path": "../escape.py", "classifications": ["production"]},
        {"path": "/absolute.py", "classifications": ["production"]},
        {"path": "same.py", "classifications": ["production"], "extra": True},
    ],
)
def test_invalid_inventory_entries_fail_closed(tmp_path: Path, entry: dict) -> None:
    with pytest.raises(SizeBudgetError):
        analyze_source_files(tmp_path, [entry], LIMITS)


def test_duplicate_nonregular_and_missing_files_fail_closed(tmp_path: Path) -> None:
    _write(tmp_path, "same.py", b"ok\n")
    entry = {"path": "same.py", "classifications": ["production"]}
    with pytest.raises(SizeBudgetError, match="duplicate paths"):
        analyze_source_files(tmp_path, [entry, entry], LIMITS)
    (tmp_path / "folder").mkdir()
    with pytest.raises(SizeBudgetError, match="not a regular file"):
        analyze_source_files(
            tmp_path, [{"path": "folder", "classifications": ["production"]}], LIMITS
        )
    with pytest.raises(SizeBudgetError, match="cannot stat"):
        analyze_source_files(
            tmp_path, [{"path": "missing.py", "classifications": ["production"]}], LIMITS
        )
    (tmp_path / "link.py").symlink_to(tmp_path / "same.py")
    with pytest.raises(SizeBudgetError, match="not a regular file"):
        analyze_source_files(
            tmp_path, [{"path": "link.py", "classifications": ["production"]}], LIMITS
        )


def test_unreadable_file_and_missing_classification_limits_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "source.py", b"ok\n")
    original = Path.read_bytes

    def denied(path: Path) -> bytes:
        if path.name == "source.py":
            raise PermissionError("denied")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", denied)
    with pytest.raises(SizeBudgetError, match="cannot read"):
        analyze_source_files(
            tmp_path, [{"path": "source.py", "classifications": ["production"]}], LIMITS
        )
    with pytest.raises(SizeBudgetError, match="missing size limits"):
        evaluate_measurement({"physical_lines": 1, "raw_bytes": 1}, ["css"], {})
