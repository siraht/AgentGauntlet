"""Map net Python production edits to surviving mutmut selectors."""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .python_mutation_diff import nontrivial_line_numbers, old_source

MutmutCandidates = Callable[[str, ast.Module], list[tuple[str, str, int, int]]]
_DELETED_UNMAPPED = (
    "deleted_lines_outside_mutable_functions",
    "deleted executable Python lines could not be mapped to surviving mutable functions",
)


def path_evidence(
    root: Path,
    comparison_ref: str | None,
    path: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Load current/old sources and nontrivial added/deleted line sets."""
    errors: dict[str, str] = {}
    try:
        source = (root / path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        source = ""
        errors[path] = str(exc)
    added_lines = nontrivial_line_numbers(source, evidence["added"])
    deleted_lines: set[int] = set()
    previous: str | None = None
    if evidence["deleted"]:
        previous, old_error = old_source(root, comparison_ref, str(evidence["old_path"]))
        if old_error is not None or previous is None:
            errors[f"{path}@base"] = old_error or "comparison source is unavailable"
        else:
            deleted_lines = nontrivial_line_numbers(previous, evidence["deleted"])
    return {
        "source": source,
        "old_source": previous,
        "added_lines": added_lines,
        "deleted_lines": deleted_lines,
        "errors": errors,
    }


def candidate_matches(
    candidates: list[tuple[str, str, int, int]],
    lines: set[int],
    allowed_selectors: set[str] | None = None,
) -> tuple[set[str], set[str], set[int]]:
    """Match line numbers to mutmut candidates, optionally filtering selectors."""
    selectors: set[str] = set()
    names: set[str] = set()
    mapped: set[int] = set()
    for selector, name, start, end in candidates:
        contained = {line_no for line_no in lines if start <= line_no <= end}
        if not contained or (allowed_selectors is not None and selector not in allowed_selectors):
            continue
        selectors.add(selector)
        names.add(name)
        mapped.update(contained)
    return selectors, names, mapped


def deleted_candidate_matches(
    path: str,
    previous: str | None,
    deleted_lines: set[int],
    current_selectors: set[str],
    candidates_for: MutmutCandidates,
) -> tuple[set[str], set[str], set[int], str | None]:
    """Map deleted lines via the comparison AST to selectors that still exist."""
    if not deleted_lines or previous is None:
        return set(), set(), set(), None
    try:
        old_tree = ast.parse(previous, filename=f"{path}@base")
    except (SyntaxError, UnicodeError) as exc:
        return set(), set(), set(), str(exc)
    selectors, names, mapped = candidate_matches(
        candidates_for(path, old_tree), deleted_lines, current_selectors
    )
    return selectors, names, mapped, None


def empty_path_selection(path: str, evidence: dict[str, Any]) -> dict[str, Any]:
    added_lines = evidence["added_lines"]
    deleted_lines = evidence["deleted_lines"]
    return {
        "path": path,
        "selectors": set(),
        "names": set(),
        "mapped_count": 0,
        "relevant_count": len(added_lines) + len(deleted_lines),
        "added_count": len(added_lines),
        "deleted_count": len(deleted_lines),
        "missing": set(added_lines),
        "missing_deleted": set(deleted_lines),
        "errors": dict(evidence["errors"]),
    }


def path_selection(
    root: Path,
    comparison_ref: str | None,
    path: str,
    evidence: dict[str, Any],
    candidates_for: MutmutCandidates,
) -> dict[str, Any]:
    """Select surviving mutmut selectors for one path's net line changes."""
    detail = path_evidence(root, comparison_ref, path, evidence)
    result = empty_path_selection(path, detail)
    if not result["relevant_count"]:
        return result
    try:
        tree = ast.parse(detail["source"], filename=path)
    except (SyntaxError, UnicodeError) as exc:
        result["errors"][path] = str(exc)
        return result
    candidates = candidates_for(path, tree)
    added = candidate_matches(candidates, detail["added_lines"])
    current_selectors = {selector for selector, _, _, _ in candidates}
    deleted = deleted_candidate_matches(
        path, detail["old_source"], detail["deleted_lines"], current_selectors, candidates_for
    )
    if deleted[3] is not None:
        result["errors"][f"{path}@base"] = deleted[3]
        return result
    result.update(
        selectors=added[0] | deleted[0],
        names=added[1] | deleted[1],
        mapped_count=len(added[2]) + len(deleted[2]),
        missing=detail["added_lines"] - added[2],
        missing_deleted=detail["deleted_lines"] - deleted[2],
    )
    return result


def nonempty_counts(results: list[dict[str, Any]], key: str) -> dict[str, int]:
    return {result["path"]: int(result[key]) for result in results if int(result[key])}


def nonempty_lines(results: list[dict[str, Any]], key: str) -> dict[str, list[int]]:
    return {result["path"]: sorted(result[key]) for result in results if result[key]}


def selection_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-path selection results into a mutation report section."""
    mapped_counts = nonempty_counts(results, "mapped_count")
    relevant_counts = nonempty_counts(results, "relevant_count")
    mapped_total = sum(mapped_counts.values())
    relevant_total = sum(relevant_counts.values())
    return {
        "selection_mode": "changed_functions",
        "mutant_selectors": sorted(
            {value for result in results for value in result["selectors"]}
        ),
        "selected_functions": {
            result["path"]: sorted(result["names"]) for result in results if result["names"]
        },
        "mapped_changed_lines": mapped_total,
        "mapped_changed_lines_by_file": mapped_counts,
        "nontrivial_changed_lines": relevant_total,
        "nontrivial_changed_lines_by_file": relevant_counts,
        "nontrivial_added_lines_by_file": nonempty_counts(results, "added_count"),
        "nontrivial_deleted_lines_by_file": nonempty_counts(results, "deleted_count"),
        "unmapped_changed_lines": nonempty_lines(results, "missing"),
        "unmapped_deleted_lines": nonempty_lines(results, "missing_deleted"),
        "unmapped_changed_lines_count": relevant_total - mapped_total,
        "selection_coverage": (
            round(mapped_total * 100 / relevant_total, 2) if relevant_total else 100.0
        ),
        "selection_complete": mapped_total == relevant_total,
        "selection_errors": {
            key: value for result in results for key, value in result["errors"].items()
        },
    }


def function_selection(
    root: Path,
    comparison_ref: str | None,
    changed: list[str],
    changes: dict[str, dict[str, Any]],
    candidates_for: MutmutCandidates,
) -> dict[str, Any]:
    """Map net additions and deletions to exact surviving mutmut selectors."""
    results = [
        path_selection(
            root,
            comparison_ref,
            path,
            changes.get(path, {"added": set(), "deleted": set(), "old_path": path}),
            candidates_for,
        )
        for path in sorted(changed)
    ]
    return selection_summary(results)


def selection_refusal(
    selection: dict[str, Any], minimum_coverage: float
) -> tuple[str, str] | None:
    """Return a fail-closed refusal when selection is incomplete or unmapped."""
    if selection["selection_errors"]:
        return (
            "mutation_selection_error",
            "changed Python production files could not be parsed into a mutmut selection",
        )
    unmapped_deleted = bool(selection.get("unmapped_deleted_lines"))
    if not selection["mutant_selectors"]:
        if unmapped_deleted and not selection["unmapped_changed_lines"]:
            return _DELETED_UNMAPPED
        return (
            "changed_lines_outside_mutable_functions",
            "no mutmut-selectable changed function or method could be established",
        )
    if unmapped_deleted and not selection["unmapped_changed_lines"]:
        return _DELETED_UNMAPPED
    if float(selection["selection_coverage"]) < minimum_coverage:
        return (
            "insufficient_function_selection_coverage",
            (
                f"changed-function selection coverage {selection['selection_coverage']}% is below "
                f"the protected minimum {minimum_coverage}%"
            ),
        )
    if unmapped_deleted:
        return _DELETED_UNMAPPED
    return None
