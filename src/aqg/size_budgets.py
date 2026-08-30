"""Deterministic source-file measurements and budget evaluation.

The module deliberately separates byte measurement and budget evaluation from
filesystem discovery.  Adapters can therefore supply an explicit governed file
inventory, while retrospective checks can evaluate saved measurements without
re-reading the candidate tree.
"""

from __future__ import annotations

import hashlib
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any


class SizeBudgetError(ValueError):
    """Raised when a file or budget cannot be measured authoritatively."""


_PRIMARY_CLASSIFICATIONS = ("production", "test", "css")
_EXCLUDED_CLASSIFICATIONS = ("generated", "vendor", "minified")
_CLASSIFICATION_ORDER = _PRIMARY_CLASSIFICATIONS + _EXCLUDED_CLASSIFICATIONS
_LIMIT_KEYS = (
    "warning_physical_lines",
    "hard_physical_lines",
    "warning_raw_bytes",
    "hard_raw_bytes",
)


def measure_source_bytes(content: bytes) -> dict[str, Any]:
    """Measure UTF-8 source content without depending on platform newlines."""
    if not isinstance(content, bytes):
        raise SizeBudgetError("source content must be bytes")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SizeBudgetError("source file is not valid UTF-8") from exc
    lines = text.splitlines()
    return {
        "physical_lines": len(lines),
        "nonblank_lines": sum(bool(line.strip()) for line in lines),
        "raw_bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _positive_or_zero_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SizeBudgetError(f"{name} must be a non-negative integer")
    return value


def _validate_limit_keys(limits: Mapping[str, Any]) -> None:
    unknown = sorted(set(limits) - set(_LIMIT_KEYS))
    missing = sorted(set(_LIMIT_KEYS) - set(limits))
    if unknown:
        raise SizeBudgetError(f"unknown size limit keys: {', '.join(unknown)}")
    if missing:
        raise SizeBudgetError(f"missing size limit keys: {', '.join(missing)}")


def _validate_limit_order(limits: Mapping[str, int]) -> None:
    for metric in ("physical_lines", "raw_bytes"):
        warning = limits[f"warning_{metric}"]
        hard = limits[f"hard_{metric}"]
        if warning > hard:
            raise SizeBudgetError(f"warning_{metric} must not exceed hard_{metric}")


def normalize_limits(limits: Mapping[str, Any]) -> dict[str, int]:
    """Validate one primary classification's warning and hard limits."""
    if not isinstance(limits, Mapping):
        raise SizeBudgetError("size limits must be a mapping")
    _validate_limit_keys(limits)
    normalized = {key: _positive_or_zero_integer(limits[key], key) for key in _LIMIT_KEYS}
    _validate_limit_order(normalized)
    return normalized


def normalize_thresholds(
    thresholds: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, int]]:
    """Validate every declared classification budget, including unused ones."""
    if not isinstance(thresholds, Mapping):
        raise SizeBudgetError("size thresholds must be a mapping")
    unknown = sorted(set(thresholds) - set(_PRIMARY_CLASSIFICATIONS))
    if unknown:
        raise SizeBudgetError(f"unknown threshold classifications: {', '.join(unknown)}")
    return {name: normalize_limits(limits) for name, limits in sorted(thresholds.items())}


def _classification_sequence(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SizeBudgetError("classifications must be a sequence of strings")
    if any(not isinstance(item, str) or not item for item in value):
        raise SizeBudgetError("classifications must contain non-empty strings")
    items = list(value)
    if len(set(items)) != len(items):
        raise SizeBudgetError("classifications must not contain duplicates")
    return items


def _validate_classification_scope(items: Sequence[str]) -> None:
    unknown = sorted(set(items) - set(_CLASSIFICATION_ORDER))
    if unknown:
        raise SizeBudgetError(f"unknown classifications: {', '.join(unknown)}")
    primary = [item for item in items if item in _PRIMARY_CLASSIFICATIONS]
    excluded = [item for item in items if item in _EXCLUDED_CLASSIFICATIONS]
    if len(primary) > 1 or (not primary and not excluded):
        raise SizeBudgetError("exactly one primary classification is required for governed source")


def normalize_classifications(value: Any) -> tuple[str, ...]:
    """Return stable classifications and reject ambiguous enforcement scopes."""
    items = _classification_sequence(value)
    _validate_classification_scope(items)
    return tuple(item for item in _CLASSIFICATION_ORDER if item in items)


def _breaches(measurement: Mapping[str, Any], limits: Mapping[str, int]) -> list[dict[str, Any]]:
    breaches: list[dict[str, Any]] = []
    for metric in ("physical_lines", "raw_bytes"):
        value = measurement.get(metric)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SizeBudgetError(f"measurement {metric} must be a non-negative integer")
        hard = limits[f"hard_{metric}"]
        warning = limits[f"warning_{metric}"]
        level = "hard" if value >= hard else "warning" if value >= warning else "pass"
        if level != "pass":
            breaches.append(
                {
                    "metric": metric,
                    "level": level,
                    "value": value,
                    "limit": hard if level == "hard" else warning,
                }
            )
    return breaches


def evaluate_measurement(
    measurement: Mapping[str, Any],
    classifications: Sequence[str],
    thresholds: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Classify a saved measurement against an explicit budget configuration."""
    normalized_classes = normalize_classifications(classifications)
    excluded = [item for item in normalized_classes if item in _EXCLUDED_CLASSIFICATIONS]
    if excluded:
        return {"status": "excluded", "exclusion_reasons": excluded, "breaches": []}
    primary = next(item for item in normalized_classes if item in _PRIMARY_CLASSIFICATIONS)
    if primary not in thresholds:
        raise SizeBudgetError(f"missing size limits for classification: {primary}")
    limits = normalize_limits(thresholds[primary])
    breaches = _breaches(measurement, limits)
    levels = {item["level"] for item in breaches}
    status = "hard_failure" if "hard" in levels else "warning" if levels else "pass"
    return {
        "status": status,
        "exclusion_reasons": [],
        "breaches": breaches,
        "limits": limits,
    }


def _relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise SizeBudgetError("source path must be a non-empty portable relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or path == PurePosixPath(".") or ".." in path.parts:
        raise SizeBudgetError(f"source path must remain within the project: {value}")
    return path.as_posix()


def _read_regular_file(root: Path, relative_path: str) -> bytes:
    path = root.joinpath(*PurePosixPath(relative_path).parts)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SizeBudgetError(f"cannot stat source file: {relative_path}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise SizeBudgetError(f"source path is not a regular file: {relative_path}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise SizeBudgetError(f"cannot read source file: {relative_path}") from exc


def _normalize_input(item: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    if not isinstance(item, Mapping):
        raise SizeBudgetError("source file inventory entries must be mappings")
    unknown = sorted(set(item) - {"path", "classifications"})
    if unknown:
        raise SizeBudgetError(f"unknown source inventory keys: {', '.join(unknown)}")
    path = _relative_path(item.get("path"))
    return path, normalize_classifications(item.get("classifications"))


def _reject_duplicate_paths(normalized: Sequence[tuple[str, tuple[str, ...]]]) -> None:
    paths = [path for path, _ in normalized]
    if len(paths) != len(set(paths)):
        raise SizeBudgetError("source file inventory contains duplicate paths")


def _normalize_inputs(files: Any) -> list[tuple[str, tuple[str, ...]]]:
    if not isinstance(files, Sequence) or isinstance(files, (str, bytes)):
        raise SizeBudgetError("source file inventory must be a sequence")
    normalized = [_normalize_input(item) for item in files]
    _reject_duplicate_paths(normalized)
    return sorted(normalized, key=lambda item: item[0])


def _aggregate(files: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    totals: dict[str, Any] = {
        "file_count": len(files),
        "physical_lines": sum(item["physical_lines"] for item in files),
        "nonblank_lines": sum(item["nonblank_lines"] for item in files),
        "raw_bytes": sum(item["raw_bytes"] for item in files),
        "statuses": dict.fromkeys(("pass", "warning", "hard_failure", "excluded"), 0),
        "classifications": dict.fromkeys(_CLASSIFICATION_ORDER, 0),
    }
    for item in files:
        totals["statuses"][item["status"]] += 1
        for classification in item["classifications"]:
            totals["classifications"][classification] += 1
    totals["enforced_file_count"] = len(files) - totals["statuses"]["excluded"]
    totals["excluded_file_count"] = totals["statuses"]["excluded"]
    return totals


def _analyze_file(
    root: Path,
    path: str,
    classifications: tuple[str, ...],
    thresholds: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    measurement = measure_source_bytes(_read_regular_file(root, path))
    evaluation = evaluate_measurement(measurement, classifications, thresholds)
    return {"path": path, "classifications": list(classifications), **measurement, **evaluation}


def _overall_status(results: Sequence[Mapping[str, Any]]) -> str:
    statuses = {item["status"] for item in results}
    if "hard_failure" in statuses:
        return "hard_failure"
    if "warning" in statuses:
        return "warning"
    return "pass"


def analyze_source_files(
    root: str | Path,
    files: Sequence[Mapping[str, Any]],
    thresholds: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Measure an explicit inventory and return stable file and aggregate evidence."""
    root_path = Path(root)
    if not root_path.is_dir():
        raise SizeBudgetError("source root must be an existing directory")
    if not isinstance(thresholds, Mapping):
        raise SizeBudgetError("size thresholds must be a mapping")
    normalized_thresholds = normalize_thresholds(thresholds)
    results = [
        _analyze_file(root_path, path, classifications, normalized_thresholds)
        for path, classifications in _normalize_inputs(files)
    ]
    return {"status": _overall_status(results), "files": results, "totals": _aggregate(results)}
