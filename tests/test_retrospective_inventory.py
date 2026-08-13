# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-003 AQG-RETRO-005 AQG-RETRO-008
"""Baseline-eligible retrospective inventory contracts."""

from __future__ import annotations

import pytest

from aqg.debt import DebtError
from aqg.retrospective_inventory import debt_inventory

LIMITS = {
    "structure": {
        "max_cyclomatic_complexity": 10,
        "max_function_lines": 50,
        "max_nesting_depth": 4,
        "max_crap": 15,
    },
    "coverage": {"lines": 85, "branches": 75, "functions": 80, "statements": 85},
}


def _details() -> dict:
    return {
        "structure": {
            "gate": "structure",
            "python": {
                "functions": [
                    {
                        "path": "src/legacy.py",
                        "name": "legacy",
                        "line": 12,
                        "complexity": 20,
                        "lines": 80,
                        "nesting": 6,
                        "enforced": False,
                    }
                ]
            },
        },
        "coverage": {
            "gate": "coverage",
            "metrics": {
                "python": {
                    "lines": 60.0,
                    "branches": 50.0,
                    "changed_lines": 40.0,
                    "crap": {
                        "functions": [
                            {
                                "path": "src/legacy.py",
                                "name": "legacy",
                                "line": 12,
                                "crap": 30.0,
                                "enforced": False,
                            }
                        ]
                    },
                },
                "javascript": {
                    "lines": 95.0,
                    "branches": 95.0,
                    "functions": 95.0,
                    "statements": 95.0,
                    "changed_lines": 1.0,
                },
            },
        },
        "test_integrity": {
            "gate": "test_integrity",
            "integrity": {
                "findings": [
                    {
                        "code": "skipped-test",
                        "path": "tests/test_app.py",
                        "line": 22,
                        "severity": "warning",
                        "fingerprint": "skipped-test:tests/test_app.py:22:@pytest.mark.skip",
                    },
                    {
                        "code": "focused-test",
                        "path": "tests/test_app.py",
                        "line": 2,
                        "severity": "error",
                        "fingerprint": "focused-test:tests/test_app.py:2:it.only",
                    },
                ]
            },
        },
        "secrets": {"gate": "secrets", "findings": [{"severity": "error"}]},
        "mutation_changed": {"gate": "mutation_changed", "survivors": [1]},
        "review": {"gate": "review", "findings": [{"severity": "blocker"}]},
    }


def test_inventory_includes_whole_tree_debt_even_when_not_currently_enforced() -> None:
    inventory = debt_inventory(_details(), LIMITS)
    by_fingerprint = {item["fingerprint"]: item for item in inventory}
    for metric in ("complexity", "lines", "nesting"):
        item = by_fingerprint[f"structure:{metric}:src/legacy.py:legacy"]
        assert item["direction"] == "higher_is_worse"
        assert item["location"] == "line:12"
    assert by_fingerprint["crap:src/legacy.py:legacy"]["direction"] == "higher_is_worse"
    assert by_fingerprint["coverage:python:lines"]["direction"] == "lower_is_worse"
    assert by_fingerprint["coverage:python:branches"]["direction"] == "lower_is_worse"
    assert "coverage:python:changed_lines" not in by_fingerprint


def test_changed_scope_inventory_excludes_untouched_functions() -> None:
    details = _details()
    details["structure"]["python"]["scope"] = "changed-functions"
    details["coverage"]["metrics"]["python"]["crap"]["scope"] = "changed-functions"
    inventory = debt_inventory(details, LIMITS)

    assert not any(item["category"] in {"structure", "crap"} for item in inventory)


def test_only_reviewable_quality_debt_is_baseline_eligible() -> None:
    inventory = debt_inventory(_details(), LIMITS)
    categories = {item["category"] for item in inventory}
    assert categories == {"structure", "coverage", "crap", "test_integrity"}
    integrity = [item for item in inventory if item["category"] == "test_integrity"]
    assert [item["fingerprint"] for item in integrity] == [
        "test_integrity:skipped-test:tests/test_app.py:@pytest.mark.skip"
    ]
    assert "22" not in integrity[0]["fingerprint"]


def test_inventory_is_deterministic_and_threshold_aware() -> None:
    details = _details()
    first = debt_inventory(details, LIMITS)
    second = debt_inventory(dict(reversed(list(details.items()))), LIMITS)
    assert first == second
    assert [item["fingerprint"] for item in first] == sorted(item["fingerprint"] for item in first)
    relaxed = {
        "structure": {
            "max_cyclomatic_complexity": 99,
            "max_function_lines": 999,
            "max_nesting_depth": 99,
            "max_crap": 999,
        },
        "coverage": {"lines": 0, "branches": 0, "functions": 0, "statements": 0},
    }
    assert [
        item for item in debt_inventory(details, relaxed) if item["category"] != "test_integrity"
    ] == []


def test_ambiguous_stable_identity_fails_closed() -> None:
    details = _details()
    duplicate = dict(details["structure"]["python"]["functions"][0])
    duplicate["line"] = 99
    duplicate["complexity"] = 25
    details["structure"]["python"]["functions"].append(duplicate)
    with pytest.raises(DebtError, match="ambiguous"):
        debt_inventory(details, LIMITS)


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_non_finite_metric_fails_closed(value: float) -> None:
    details = _details()
    details["coverage"]["metrics"]["python"]["lines"] = value
    with pytest.raises(DebtError, match="finite"):
        debt_inventory(details, LIMITS)
