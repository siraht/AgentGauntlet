"""Pure repeated performance-sampling aggregation."""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from .constants import INFRASTRUCTURE_ERROR, PASS, QUALITY_FAILURE
from .errors import ConfigurationError


def sampling_policy(thresholds: Mapping[str, Any]) -> dict[str, Any]:
    count = thresholds.get("sample_count", 3)
    warmups = thresholds.get("warmup_runs", 1)
    spread = thresholds.get("max_score_spread", 0.1)
    if (
        isinstance(count, bool)
        or not isinstance(count, int)
        or count < 3
        or count > 9
        or count % 2 == 0
    ):
        raise ConfigurationError("performance.sample_count must be an odd integer from 3 to 9")
    if isinstance(warmups, bool) or not isinstance(warmups, int) or warmups < 0 or warmups > 3:
        raise ConfigurationError("performance.warmup_runs must be an integer from 0 to 3")
    if (
        isinstance(spread, bool)
        or not isinstance(spread, (int, float))
        or not math.isfinite(float(spread))
        or not 0 <= float(spread) <= 1
    ):
        raise ConfigurationError("performance.max_score_spread must be a number from 0 to 1")
    return {
        "sample_count": count,
        "warmup_runs": warmups,
        "max_score_spread": float(spread),
    }


def aggregate_scores(
    samples: Sequence[Mapping[str, Any]],
    minimums: Mapping[str, float],
    *,
    expected_count: int,
    max_score_spread: float,
) -> tuple[int, dict[str, Any]]:
    """Aggregate complete samples and classify unstable evidence as unusable."""
    if len(samples) != expected_count:
        return INFRASTRUCTURE_ERROR, {
            "samples": list(samples),
            "metrics": {},
            "failures": [
                f"expected {expected_count} complete performance samples, got {len(samples)}"
            ],
            "unstable": [],
        }
    metrics: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    unstable: list[str] = []
    for name, minimum in minimums.items():
        values: list[float] = []
        for index, sample in enumerate(samples):
            value = sample.get(name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not 0 <= float(value) <= 1
            ):
                failures.append(f"sample {index + 1} has invalid {name} score")
                continue
            values.append(float(value))
        if len(values) != expected_count:
            continue
        median = float(statistics.median(values))
        low, high = min(values), max(values)
        spread = high - low
        metrics[name] = {
            "samples": values,
            "median": median,
            "minimum": low,
            "maximum": high,
            "spread": spread,
            "required": float(minimum),
        }
        if spread > max_score_spread:
            unstable.append(f"{name} spread {spread:.3f} exceeds {max_score_spread:.3f}")
        elif median < float(minimum):
            failures.append(f"{name} median {median:.2f} < {float(minimum):.2f}")
    if unstable or len(metrics) != len(minimums):
        code = INFRASTRUCTURE_ERROR
    elif failures:
        code = QUALITY_FAILURE
    else:
        code = PASS
    return code, {
        "samples": [dict(sample) for sample in samples],
        "metrics": metrics,
        "failures": failures,
        "unstable": unstable,
    }
