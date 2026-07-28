# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-007
"""Strict-readiness measurement contracts."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "scripts.measure_strict_readiness",
    Path(__file__).resolve().parents[1] / "scripts" / "measure_strict_readiness.py",
)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_complexity_payload_accepts_normalized_gate_evidence() -> None:
    report = {
        "schema_version": 2,
        "python": {
            "functions": [
                {
                    "path": "src/app.py",
                    "name": "dispatch",
                    "line": 4,
                    "complexity": 12,
                }
            ]
        },
    }
    assert _MODULE._complexity_payload(report) == [
        {
            "path": "src/app.py",
            "name": "dispatch",
            "line": 4,
            "complexity": 12,
            "rank": "C",
        }
    ]


def test_complexity_payload_retains_legacy_radon_compatibility() -> None:
    report = {
        "src/app.py": [
            {
                "type": "function",
                "name": "dispatch",
                "lineno": 4,
                "complexity": 9,
                "rank": "B",
            }
        ]
    }
    assert _MODULE._complexity_payload(report)[0]["rank"] == "B"


def test_normalized_report_requires_function_inventory() -> None:
    with pytest.raises(ValueError, match="python.functions"):
        _MODULE._complexity_payload({"python": {"failures": []}})
    with pytest.raises(ValueError, match="malformed function"):
        _MODULE._complexity_payload({"python": {"functions": ["not an object"]}})
