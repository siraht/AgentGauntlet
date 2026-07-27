"""Shared status codes and product metadata."""

from __future__ import annotations

__version__ = "2.0.0"

PASS = 0
QUALITY_FAILURE = 1
CONFIGURATION_ERROR = 2
INFRASTRUCTURE_ERROR = 3

STATUS_NAMES = {
    PASS: "pass",
    QUALITY_FAILURE: "quality_failure",
    CONFIGURATION_ERROR: "configuration_error",
    INFRASTRUCTURE_ERROR: "infrastructure_error",
}

RISK_ORDER = ["experiment", "standard", "high_assurance", "critical"]
EXECUTION_ORDER = ["fast", "pr", "deep", "release"]
PLACEHOLDER = "__CONFIGURE__"

DEFAULT_EXCLUDES = [
    ".git/**",
    ".aqg/**",
    ".venv/**",
    "venv/**",
    ".tox/**",
    "node_modules/**",
    ".yarn/**",
    ".pnp.*",
    "aqg",
    "quality/qg.py",
    "quality/tools/**",
    "quality/_aqg/**",
    "dist/**",
    "build/**",
    "coverage/**",
    "htmlcov/**",
    ".pytest_cache/**",
    ".mypy_cache/**",
    ".ruff_cache/**",
    ".next/**",
    ".nuxt/**",
    ".svelte-kit/**",
    "playwright-report/**",
    "test-results/**",
    "mutants/**",
]
