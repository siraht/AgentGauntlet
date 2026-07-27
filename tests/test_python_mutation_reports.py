"""Unit tests for Python mutation report builders."""

from __future__ import annotations

import unittest

from aqg.python_mutation_reports import (
    apply_changed_selection,
    deleted_files_report,
    empty_mutation_report,
    mark_full_scope,
)


class MutationReportTests(unittest.TestCase):
    def test_deleted_files_report_uses_exact_stable_keys_and_counts(self) -> None:
        report = deleted_files_report(
            changed=["src/kept.py"],
            deleted_files=["src/gone.py"],
            deleted_line_counts={"src/gone.py": 4},
            deletion_errors={},
        )
        self.assertEqual(
            report,
            {
                "scope": "changed",
                "scope_refused": True,
                "campaign_complete": False,
                "mutated_files": ["src/kept.py"],
                "deleted_production_files": ["src/gone.py"],
                "changed_production_lines": 4,
                "changed_production_lines_by_file": {"src/gone.py": 4},
                "deletion_evidence_errors": {},
                "incomplete_reason": "deleted_production_files",
                "reason": (
                    "deleted Python production files cannot be mutation-tested; "
                    "provide independent behavioral and human review evidence"
                ),
            },
        )

    def test_empty_mutation_report_distinguishes_changed_and_full_scope(self) -> None:
        self.assertEqual(
            empty_mutation_report(True),
            {
                "scope": "changed",
                "scope_refused": False,
                "campaign_complete": True,
                "mutated_files": [],
                "changed_production_lines": 0,
                "reason": "no changed Python production files",
            },
        )
        self.assertEqual(
            empty_mutation_report(False),
            {
                "scope": "full",
                "scope_refused": False,
                "campaign_complete": True,
                "mutated_files": [],
                "changed_production_lines": 0,
                "reason": "no changed Python production files",
            },
        )

    def test_mark_full_scope_writes_every_selection_field(self) -> None:
        scope: dict[str, object] = {"existing": 1}
        mark_full_scope(scope)
        self.assertEqual(
            scope,
            {
                "existing": 1,
                "selection_mode": "full",
                "mutant_selectors": [],
                "selected_functions": {},
                "unmapped_changed_lines": {},
                "unmapped_deleted_lines": {},
                "selection_errors": {},
            },
        )

    def test_apply_changed_selection_returns_pass_for_comment_only_selection(self) -> None:
        selection = {
            "nontrivial_changed_lines": 0,
            "mutant_selectors": [],
            "selection_errors": {},
            "unmapped_changed_lines": {},
            "unmapped_deleted_lines": {},
            "selection_coverage": 100.0,
        }
        scope: dict[str, object] = {}
        code, selectors = apply_changed_selection(
            selection, scope, 80.0, pass_code=0, configuration_error=2
        )
        self.assertEqual(code, 0)
        self.assertEqual(selectors, [])
        self.assertEqual(scope["minimum_selection_coverage"], 80.0)
        self.assertTrue(scope["campaign_complete"])
        self.assertEqual(scope["reason"], "no changed executable Python production lines")

    def test_apply_changed_selection_refuses_unmapped_deleted_lines(self) -> None:
        selection = {
            "nontrivial_changed_lines": 1,
            "mutant_selectors": [],
            "selection_errors": {},
            "unmapped_changed_lines": {},
            "unmapped_deleted_lines": {"src/a.py": [1]},
            "selection_coverage": 0.0,
        }
        scope: dict[str, object] = {}
        code, selectors = apply_changed_selection(
            selection, scope, 80.0, pass_code=0, configuration_error=2
        )
        self.assertEqual(code, 2)
        self.assertEqual(selectors, [])
        self.assertTrue(scope["scope_refused"])
        self.assertEqual(scope["incomplete_reason"], "deleted_lines_outside_mutable_functions")


if __name__ == "__main__":
    unittest.main()
