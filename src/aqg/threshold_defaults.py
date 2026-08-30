"""Protected starter thresholds shared by project scaffolding."""

from __future__ import annotations

from typing import Any


def default_thresholds() -> dict[str, Any]:
    """Return conservative default thresholds for routine changes."""
    return {
        "coverage": {
            "lines": 85,
            "branches": 75,
            "functions": 80,
            "statements": 85,
            "changed_lines": 90,
            "allow_missing": False,
        },
        "structure": {
            "max_function_lines": 50,
            "max_cyclomatic_complexity": 10,
            "max_crap": 15,
            "max_nesting_depth": 4,
            "warn_source_file_lines": 300,
            "max_source_file_lines": 500,
            "warn_css_file_lines": 300,
            "max_css_file_lines": 450,
            "warn_test_file_lines": 600,
            "max_test_file_lines": 800,
            "warn_source_file_bytes": 76800,
            "max_source_file_bytes": 102400,
            "max_abc_score": 20,
        },
        "mutation": {
            "minimum_score": 70,
            "maximum_survivors": 0,
            "minimum_selection_coverage": 80,
            "changed_only": True,
        },
        "security": {"audit_level": "high", "allow_unreviewed_ignores": False},
        "performance": {
            "lighthouse_performance": 0.8,
            "lighthouse_accessibility": 0.95,
            "sample_count": 3,
            "warmup_runs": 1,
            "max_score_spread": 0.1,
        },
        "resource_budget": _resource_budget_thresholds(),
    }


def _resource_budget_thresholds() -> dict[str, int | float]:
    return {
        "warning_ratio": 0.8,
        "max_javascript_file_raw_bytes": 1048576,
        "max_javascript_file_gzip_bytes": 256000,
        "max_javascript_total_raw_bytes": 1677722,
        "max_javascript_total_gzip_bytes": 409600,
        "max_css_file_raw_bytes": 307200,
        "max_css_file_gzip_bytes": 76800,
        "max_css_total_raw_bytes": 409600,
        "max_css_total_gzip_bytes": 102400,
    }


def assurance_thresholds() -> dict[str, Any]:
    """Return cumulative deep and release threshold overrides."""
    return {
        "fast": {},
        "pr": {},
        "deep": {
            "coverage": {
                "lines": 90,
                "branches": 85,
                "functions": 90,
                "statements": 90,
                "changed_lines": 95,
            },
            "structure": {
                "max_function_lines": 40,
                "max_cyclomatic_complexity": 8,
                "max_crap": 8,
                "max_nesting_depth": 4,
                "max_abc_score": 15,
            },
            "mutation": {
                "minimum_score": 85,
                "maximum_survivors": 0,
                "minimum_selection_coverage": 90,
            },
            "performance": {"lighthouse_performance": 0.9, "lighthouse_accessibility": 0.98},
        },
        "release": {
            "coverage": {
                "lines": 95,
                "branches": 90,
                "functions": 95,
                "statements": 95,
                "changed_lines": 95,
            },
            "structure": {
                "max_function_lines": 30,
                "max_cyclomatic_complexity": 5,
                "max_crap": 5,
                "max_nesting_depth": 3,
                "max_abc_score": 10,
            },
            "mutation": {
                "minimum_score": 90,
                "maximum_survivors": 0,
                "minimum_selection_coverage": 95,
            },
            "performance": {"lighthouse_performance": 0.95, "lighthouse_accessibility": 0.99},
        },
    }
