# Feature-Spec: AgentQualityGauntlet AQG-CORE-023
# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-001 AQG-RETRO-002 AQG-RETRO-004 AQG-RETRO-005 AQG-RETRO-008
"""Unit tests for the pure retrospective report builder."""

from __future__ import annotations

import copy
import unittest

from aqg.debt import DebtError
from aqg.retrospective import TAXONOMY, build_retrospective, ratchet_exit_code

THRESHOLDS = {
    "structure": {
        "max_cyclomatic_complexity": 10,
        "max_function_lines": 50,
        "max_nesting_depth": 4,
        "max_crap": 15,
    },
    "coverage": {
        "lines": 85,
        "branches": 75,
        "functions": 80,
        "statements": 85,
        "changed_lines": 90,
    },
}


def _structure_detail(
    *,
    complexity: int = 20,
    lines: int = 80,
    nesting: int = 6,
    enforced: bool = False,
    path: str = "src/module.py",
    name: str = "legacy_fn",
    line: int = 12,
) -> dict:
    return {
        "gate": "structure",
        "python": {
            "functions": [
                {
                    "path": path,
                    "name": name,
                    "line": line,
                    "end_line": line + lines,
                    "complexity": complexity,
                    "lines": lines,
                    "nesting": nesting,
                    "enforced": enforced,
                }
            ],
            "failures": [],
            "limits": THRESHOLDS["structure"],
        },
    }


def _coverage_detail(
    *,
    py_lines: float = 60.0,
    py_branches: float = 50.0,
    js_lines: float = 70.0,
    js_branches: float = 60.0,
    js_functions: float = 55.0,
    js_statements: float = 65.0,
    changed_lines: float | None = 40.0,
    crap: float = 40.0,
    crap_enforced: bool = False,
) -> dict:
    return {
        "gate": "coverage",
        "metrics": {
            "python": {
                "lines": py_lines,
                "branches": py_branches,
                "changed_lines": changed_lines,
                "failures": (
                    [f"changed-line coverage {changed_lines:.1f}% < 90%"]
                    if changed_lines is not None
                    else []
                ),
                "crap": {
                    "maximum_allowed": 15,
                    "functions": [
                        {
                            "path": "src/hot.py",
                            "name": "risky",
                            "line": 3,
                            "crap": crap,
                            "complexity": 8,
                            "coverage": 10.0,
                            "enforced": crap_enforced,
                        }
                    ],
                    "failures": [],
                },
            },
            "javascript": {
                "lines": js_lines,
                "branches": js_branches,
                "functions": js_functions,
                "statements": js_statements,
                "changed_lines": changed_lines,
                "failures": [],
            },
        },
    }


def _integrity_detail() -> dict:
    return {
        "gate": "test_integrity",
        "integrity": {
            "findings": [
                {
                    "code": "skipped-test",
                    "severity": "warning",
                    "message": "Skipped test is committed.",
                    "path": "tests/test_app.py",
                    "line": 22,
                    "fingerprint": "skipped-test:tests/test_app.py:22:@pytest.mark.skip",
                },
                {
                    "code": "runtime-skip",
                    "severity": "baseline",
                    "message": "Runtime skip is baselined.",
                    "path": "tests/test_app.py",
                    "line": 40,
                    "fingerprint": "runtime-skip:tests/test_app.py:40:pytest.skip",
                },
                {
                    "code": "focused-test",
                    "severity": "error",
                    "message": "Focused test is committed.",
                    "path": "tests/test_app.py",
                    "line": 5,
                    "fingerprint": "focused-test:tests/test_app.py:5:it.only",
                },
            ]
        },
    }


def _secrets_detail() -> dict:
    return {
        "gate": "secrets",
        "findings": [{"code": "secret", "severity": "error", "path": "src/x.py"}],
        "failures": ["secret detected"],
    }


def _review_detail() -> dict:
    return {
        "gate": "review",
        "findings": [{"code": "behavior-change", "severity": "blocker"}],
    }


def _mutation_detail() -> dict:
    return {
        "gate": "mutation_changed",
        "survivors": [{"mutant": "1", "status": "survived"}],
        "failures": ["1 survived mutants"],
    }


def _baseline(inventory: list[dict], *, state: str = "reviewed") -> dict:
    document: dict = {
        "schema_version": 1,
        "state": state,
        "source_revision": "abc123",
        "policy_fingerprint": "sha256:policy",
        "control_fingerprint": "sha256:control",
        "created_at": "2026-07-27T12:00:00+00:00",
        "measurement": {
            "run_id": "20260727-audit",
            "profile": "shadow",
            "measured_at": "2026-07-27T11:59:00Z",
            "change_fingerprint": "sha256:change",
            "manifest_fingerprint": "sha256:manifest",
        },
        "inventory": inventory,
    }
    if state == "reviewed":
        document["reviewer"] = "alice"
        document["reviewed_at"] = "2026-07-28T00:00:00+00:00"
    return document


def _full_details() -> dict:
    return {
        "structure": _structure_detail(),
        "coverage": _coverage_detail(),
        "test_integrity": _integrity_detail(),
        "secrets": _secrets_detail(),
        "review": _review_detail(),
        "mutation_changed": _mutation_detail(),
        "security_fast": {"gate": "security_fast", "failures": ["high advisory"]},
    }


class RetrospectiveTaxonomyTests(unittest.TestCase):
    def test_schema_and_every_taxonomy_bucket(self) -> None:
        gate_results = [
            {"gate": "unit", "exit_code": 1, "status": "quality_failure", "stderr": "1 failed"},
            {
                "gate": "mutation_changed",
                "exit_code": 2,
                "status": "configuration_error",
                "stderr": "selection refused",
            },
            {
                "gate": "performance",
                "exit_code": 3,
                "status": "infrastructure_error",
                "stderr": "chrome crashed",
            },
            {
                "gate": "coverage",
                "exit_code": 1,
                "status": "quality_failure",
                "detail_error": "coverage JSON was missing after pytest",
            },
            {"gate": "structure", "exit_code": 1, "status": "quality_failure"},
            {"gate": "format", "exit_code": 0, "status": "pass"},
        ]
        details = _full_details()
        details["coverage"] = {
            "gate": "coverage",
            "failures": ["coverage JSON was missing after pytest"],
            "metrics": {},
        }
        traceability = {
            "findings": [
                {
                    "code": "unmapped-active-spec",
                    "severity": "warning",
                    "message": "Active feature specification 'Billing' has no test reference.",
                    "path": "feature-spec/Billing.md",
                    "fingerprint": "unmapped-active-spec:Billing",
                }
            ]
        }
        # Reviewed baseline with a subset so comparison fills every debt bucket.
        current_like = build_retrospective([], details, THRESHOLDS)
        inventory = current_like["inventory"]
        keep = next(item for item in inventory if item["category"] == "structure")
        gone = {
            "fingerprint": "structure:lines:src/gone.py:retired",
            "category": "structure",
            "path": "src/gone.py",
            "severity": "medium",
            "location": "line:1",
            "value": 99,
            "direction": "higher_is_worse",
        }
        regressed_seed = {
            **keep,
            "value": keep["value"] - 1
            if keep["direction"] == "higher_is_worse"
            else keep["value"] + 1,
        }
        baseline = _baseline([regressed_seed, gone])
        # Force a worse current value for the kept fingerprint.
        if keep["direction"] == "higher_is_worse":
            # inventory already worse than seed
            pass
        report = build_retrospective(
            gate_results,
            details,
            THRESHOLDS,
            traceability=traceability,
            baseline=baseline,
        )
        self.assertEqual(report["schema_version"], 1)
        for name in TAXONOMY:
            self.assertIn(name, report)
            self.assertIn(name, report["counts"])
            self.assertEqual(report["counts"][name], len(report[name]))
        self.assertGreater(report["counts"]["measured_failures"], 0)
        self.assertGreater(report["counts"]["configuration_errors"], 0)
        self.assertGreater(report["counts"]["infrastructure_errors"], 0)
        self.assertGreater(report["counts"]["missing_evidence"], 0)
        self.assertGreater(report["counts"]["unknown_product_intent"], 0)
        self.assertGreater(report["counts"]["regressions"], 0)
        self.assertGreater(report["counts"]["resolved_debt"], 0)
        self.assertGreater(report["counts"]["new_debt"], 0)
        self.assertEqual(report["counts"]["unreviewed_debt"], 0)
        # Missing evidence is not also counted as an ordinary measured failure.
        missing_gates = {item["gate"] for item in report["missing_evidence"]}
        measured_gates = {item["gate"] for item in report["measured_failures"]}
        self.assertIn("coverage", missing_gates)
        self.assertNotIn("coverage", measured_gates)

    def test_lower_vs_higher_metrics_and_unenforced_structure(self) -> None:
        details = {
            "structure": _structure_detail(enforced=False, complexity=25, lines=90, nesting=7),
            "coverage": _coverage_detail(
                py_lines=50.0,
                py_branches=40.0,
                js_lines=90.0,
                js_branches=90.0,
                js_functions=90.0,
                js_statements=90.0,
                changed_lines=10.0,
                crap=50.0,
                crap_enforced=False,
            ),
            "test_integrity": _integrity_detail(),
        }
        report = build_retrospective(
            [{"gate": "structure", "exit_code": 0}],
            details,
            THRESHOLDS,
        )
        by_fp = {item["fingerprint"]: item for item in report["inventory"]}
        # Un-enforced structure debt is still inventoried.
        self.assertIn("structure:complexity:src/module.py:legacy_fn", by_fp)
        self.assertIn("structure:lines:src/module.py:legacy_fn", by_fp)
        self.assertIn("structure:nesting:src/module.py:legacy_fn", by_fp)
        for key in (
            "structure:complexity:src/module.py:legacy_fn",
            "structure:lines:src/module.py:legacy_fn",
            "structure:nesting:src/module.py:legacy_fn",
            "crap:src/hot.py:risky",
        ):
            self.assertEqual(by_fp[key]["direction"], "higher_is_worse")
            self.assertNotIn(str(by_fp[key]["fingerprint"]), "12")
            self.assertTrue(str(by_fp[key].get("location", "")).startswith("line:"))
        for key in ("coverage:python:lines", "coverage:python:branches"):
            self.assertEqual(by_fp[key]["direction"], "lower_is_worse")
        # Passing JS aggregates and changed-line shortfalls are not baselined.
        self.assertNotIn("coverage:javascript:lines", by_fp)
        self.assertFalse(any("changed" in fp for fp in by_fp))
        # Warning + baseline integrity findings only; errors excluded.
        integrity = [item for item in report["inventory"] if item["category"] == "test_integrity"]
        self.assertEqual(len(integrity), 2)
        self.assertTrue(all("22" not in item["fingerprint"] for item in integrity))
        self.assertTrue(all("40" not in item["fingerprint"] for item in integrity))

    def test_javascript_structure_functions_are_baseline_eligible(self) -> None:
        details = {
            "structure": {
                "gate": "structure",
                "javascript": {
                    "functions": [
                        {
                            "path": "src/app.js",
                            "name": "render",
                            "line": 12,
                            "complexity": 11,
                            "enforced": False,
                        }
                    ]
                },
            }
        }

        report = build_retrospective([], details, THRESHOLDS)

        self.assertIn(
            "structure:complexity:src/app.js:render",
            {item["fingerprint"] for item in report["inventory"]},
        )

    def test_non_baselinable_findings_excluded_from_inventory(self) -> None:
        details = _full_details()
        report = build_retrospective(
            [
                {"gate": "secrets", "exit_code": 1, "stderr": "secret detected"},
                {"gate": "security_fast", "exit_code": 1, "stderr": "advisory"},
                {"gate": "review", "exit_code": 1, "stderr": "blocker"},
                {"gate": "mutation_changed", "exit_code": 1, "stderr": "survivor"},
            ],
            details,
            THRESHOLDS,
        )
        categories = {item["category"] for item in report["inventory"]}
        self.assertTrue(categories <= {"structure", "coverage", "crap", "test_integrity"})
        self.assertFalse(any("secret" in item["fingerprint"] for item in report["inventory"]))
        self.assertFalse(any("survivor" in item["fingerprint"] for item in report["inventory"]))
        self.assertFalse(any(item["path"] == "review" for item in report["inventory"]))
        # Those gates still surface as measured failures.
        measured = {item["gate"] for item in report["measured_failures"]}
        self.assertEqual(measured, {"secrets", "security_fast", "review", "mutation_changed"})

    def test_no_baseline_is_unreviewed_observations_only(self) -> None:
        details = {"structure": _structure_detail(), "coverage": _coverage_detail()}
        report = build_retrospective([], details, THRESHOLDS)
        self.assertEqual(report["certification"], "observations_only")
        self.assertEqual(report["unreviewed_debt"], report["inventory"])
        self.assertGreater(len(report["unreviewed_debt"]), 0)
        for bucket in (
            "inherited_debt",
            "regressions",
            "new_debt",
            "resolved_debt",
            "invalid_debt",
        ):
            self.assertEqual(report[bucket], [])
            self.assertEqual(report["counts"][bucket], 0)

    def test_reviewed_baseline_classifies_inherited_and_regression_free(self) -> None:
        details = {"structure": _structure_detail(complexity=20, lines=80, nesting=6)}
        inventory = build_retrospective([], details, THRESHOLDS)["inventory"]
        baseline = _baseline(copy.deepcopy(inventory))
        report = build_retrospective(
            [{"gate": "structure", "exit_code": 1, "stderr": "structure debt"}],
            details,
            THRESHOLDS,
            baseline=baseline,
        )
        self.assertEqual(report["certification"], "regression_free")
        self.assertEqual(ratchet_exit_code(report), 0)
        self.assertEqual(report["counts"]["inherited_debt"], len(inventory))
        self.assertEqual(report["counts"]["new_debt"], 0)
        self.assertEqual(report["counts"]["regressions"], 0)
        self.assertEqual(report["counts"]["unreviewed_debt"], 0)
        # Measured gate failure is preserved and does not block regression_free.
        self.assertEqual(report["counts"]["measured_failures"], 1)

    def test_unmeasured_profile_debt_remains_inherited_not_resolved(self) -> None:
        full_details = {
            "structure": _structure_detail(complexity=20),
            "coverage": _coverage_detail(),
        }
        inventory = build_retrospective([], full_details, THRESHOLDS)["inventory"]
        baseline = _baseline(copy.deepcopy(inventory))

        fast_report = build_retrospective(
            [], {"structure": _structure_detail(complexity=20)}, THRESHOLDS, baseline=baseline
        )

        inherited_categories = {item["category"] for item in fast_report["inherited_debt"]}
        self.assertEqual(inherited_categories, {"coverage", "crap", "structure"})
        self.assertEqual(fast_report["resolved_debt"], [])
        self.assertEqual(fast_report["certification"], "regression_free")
        self.assertEqual(ratchet_exit_code(fast_report), 0)

    def test_new_or_regressed_debt_is_not_regression_free(self) -> None:
        details = {"structure": _structure_detail(complexity=20)}
        inventory = build_retrospective([], details, THRESHOLDS)["inventory"]
        baseline = _baseline(copy.deepcopy(inventory))
        worse = {
            "structure": _structure_detail(complexity=30, lines=80, nesting=6),
        }
        regressed = build_retrospective([], worse, THRESHOLDS, baseline=baseline)
        self.assertEqual(regressed["certification"], "not_regression_free")
        self.assertGreater(regressed["counts"]["regressions"], 0)

        empty_baseline = _baseline([])
        fresh = build_retrospective([], details, THRESHOLDS, baseline=empty_baseline)
        self.assertEqual(fresh["certification"], "not_regression_free")
        self.assertGreater(fresh["counts"]["new_debt"], 0)

    def test_non_baselinable_quality_failure_blocks_ratchet_certification(self) -> None:
        details = {"structure": _structure_detail()}
        baseline = _baseline(build_retrospective([], details, THRESHOLDS)["inventory"])
        unit = build_retrospective(
            [{"gate": "unit", "exit_code": 1, "stderr": "assertion failed"}],
            details,
            THRESHOLDS,
            baseline=baseline,
        )
        self.assertEqual(unit["certification"], "not_regression_free")
        self.assertEqual([item["gate"] for item in unit["blocking_failures"]], ["unit"])

        coverage = _coverage_detail(changed_lines=50.0)
        coverage_baseline = _baseline(
            build_retrospective([], {"coverage": coverage}, THRESHOLDS)["inventory"]
        )
        changed = build_retrospective(
            [{"gate": "coverage", "exit_code": 1}],
            {"coverage": coverage},
            THRESHOLDS,
            baseline=coverage_baseline,
        )
        self.assertEqual(changed["certification"], "not_regression_free")
        self.assertEqual([item["gate"] for item in changed["blocking_failures"]], ["coverage"])

    def test_proposed_and_invalid_baseline_rejected(self) -> None:
        details = {"structure": _structure_detail()}
        inventory = build_retrospective([], details, THRESHOLDS)["inventory"]
        proposed = _baseline(copy.deepcopy(inventory), state="proposed")
        with self.assertRaises(DebtError) as ctx:
            build_retrospective([], details, THRESHOLDS, baseline=proposed)
        self.assertIn("reviewed", str(ctx.exception).lower())
        invalid = _baseline(copy.deepcopy(inventory))
        invalid["reviewer"] = ""
        with self.assertRaises(DebtError):
            build_retrospective([], details, THRESHOLDS, baseline=invalid)

    def test_unknown_product_intent_not_inherited_debt(self) -> None:
        details = {"structure": _structure_detail()}
        inventory = build_retrospective([], details, THRESHOLDS)["inventory"]
        baseline = _baseline(copy.deepcopy(inventory))
        traceability = {
            "findings": [
                {
                    "code": "unmapped-active-spec",
                    "path": "feature-spec/Payments.md",
                    "fingerprint": "unmapped-active-spec:Payments",
                    "message": "no mapping",
                }
            ]
        }
        report = build_retrospective(
            [],
            details,
            THRESHOLDS,
            traceability=traceability,
            baseline=baseline,
        )
        self.assertEqual(report["counts"]["unknown_product_intent"], 1)
        self.assertEqual(report["certification"], "not_regression_free")
        self.assertTrue(
            all(item["category"] != "unknown_product_intent" for item in report["inherited_debt"])
        )
        self.assertTrue(
            all(
                item["fingerprint"].startswith("unknown_product_intent:")
                for item in report["unknown_product_intent"]
            )
        )

    def test_missing_config_infra_block_regression_free(self) -> None:
        details = {"structure": _structure_detail()}
        inventory = build_retrospective([], details, THRESHOLDS)["inventory"]
        baseline = _baseline(copy.deepcopy(inventory))
        for results, bucket in (
            (
                [{"gate": "coverage", "exit_code": 3, "detail_error": "artifact unavailable"}],
                "missing_evidence",
            ),
            (
                [{"gate": "doctor", "exit_code": 2, "stderr": "bad project.json"}],
                "configuration_errors",
            ),
            (
                [{"gate": "unit", "exit_code": 3, "stderr": "pytest worker crashed"}],
                "infrastructure_errors",
            ),
        ):
            report = build_retrospective(results, details, THRESHOLDS, baseline=baseline)
            self.assertEqual(report["certification"], "not_regression_free", bucket)
            self.assertEqual(report["counts"][bucket], 1, bucket)

    def test_deterministic_output_and_no_input_mutation(self) -> None:
        gate_results = [
            {"gate": "unit", "exit_code": 1, "stderr": "failed"},
            {"gate": "structure", "exit_code": 1, "stderr": "complex"},
        ]
        details = {
            "structure": _structure_detail(),
            "coverage": _coverage_detail(),
            "test_integrity": _integrity_detail(),
        }
        thresholds = copy.deepcopy(THRESHOLDS)
        original_results = copy.deepcopy(gate_results)
        original_details = copy.deepcopy(details)
        original_thresholds = copy.deepcopy(thresholds)
        first = build_retrospective(gate_results, details, thresholds)
        second = build_retrospective(
            list(reversed(gate_results)),
            {key: details[key] for key in reversed(list(details))},
            thresholds,
        )
        self.assertEqual(first, second)
        self.assertEqual(gate_results, original_results)
        self.assertEqual(details, original_details)
        self.assertEqual(thresholds, original_thresholds)
        # Inventory fingerprints are ordered.
        fingerprints = [item["fingerprint"] for item in first["inventory"]]
        self.assertEqual(fingerprints, sorted(fingerprints))

    def test_no_double_count_within_category(self) -> None:
        results = [
            {"gate": "unit", "exit_code": 1, "stderr": "failed"},
            {"gate": "unit", "exit_code": 1, "stderr": "failed again"},
        ]
        report = build_retrospective(results, {}, THRESHOLDS)
        self.assertEqual(report["counts"]["measured_failures"], 1)
        details = {
            "structure": {
                "gate": "structure",
                "python": {
                    "functions": [
                        {
                            "path": "src/a.py",
                            "name": "f",
                            "line": 1,
                            "complexity": 20,
                            "lines": 10,
                            "nesting": 1,
                            "enforced": False,
                        },
                        {
                            "path": "src/a.py",
                            "name": "f",
                            "line": 99,
                            "complexity": 21,
                            "lines": 10,
                            "nesting": 1,
                            "enforced": True,
                        },
                    ]
                },
            }
        }
        with self.assertRaises(DebtError):
            build_retrospective([], details, THRESHOLDS)


if __name__ == "__main__":
    unittest.main()
