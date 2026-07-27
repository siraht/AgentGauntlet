"""Report builders for Python mutation scope campaigns."""

from __future__ import annotations

from typing import Any

from .python_mutation_selection import selection_refusal


def deleted_files_report(
    *,
    changed: list[str],
    deleted_files: list[str],
    deleted_line_counts: dict[str, int],
    deletion_errors: dict[str, str],
) -> dict[str, Any]:
    """Build a configuration-failure report for deleted production modules."""
    return {
        "scope": "changed",
        "scope_refused": True,
        "campaign_complete": False,
        "mutated_files": changed,
        "deleted_production_files": deleted_files,
        "changed_production_lines": sum(deleted_line_counts.values()),
        "changed_production_lines_by_file": deleted_line_counts,
        "deletion_evidence_errors": deletion_errors,
        "incomplete_reason": "deleted_production_files",
        "reason": (
            "deleted Python production files cannot be mutation-tested; "
            "provide independent behavioral and human review evidence"
        ),
    }


def empty_mutation_report(changed_only: bool) -> dict[str, Any]:
    return {
        "scope": "changed" if changed_only else "full",
        "scope_refused": False,
        "campaign_complete": True,
        "mutated_files": [],
        "changed_production_lines": 0,
        "reason": "no changed Python production files",
    }


def mark_full_scope(scope: dict[str, Any]) -> None:
    scope.update(
        {
            "selection_mode": "full",
            "mutant_selectors": [],
            "selected_functions": {},
            "unmapped_changed_lines": {},
            "unmapped_deleted_lines": {},
            "selection_errors": {},
        }
    )


def apply_changed_selection(
    selection: dict[str, Any],
    scope: dict[str, Any],
    minimum_selection: float,
    *,
    pass_code: int,
    configuration_error: int,
) -> tuple[int | None, list[str]]:
    """Update scope from selection and return early exit code when finished."""
    selection["minimum_selection_coverage"] = minimum_selection
    scope.update(selection)
    if selection["nontrivial_changed_lines"] == 0:
        scope.update(
            {
                "campaign_complete": True,
                "reason": "no changed executable Python production lines",
            }
        )
        return pass_code, []
    refusal = selection_refusal(selection, minimum_selection)
    if refusal is not None:
        incomplete_reason, reason = refusal
        scope.update(
            {
                "scope_refused": True,
                "campaign_complete": False,
                "incomplete_reason": incomplete_reason,
                "reason": reason,
            }
        )
        return configuration_error, []
    return None, selection["mutant_selectors"]