"""Net comparison-diff helpers for Python mutation scope.

Parses one net git comparison so both added and deleted line numbers are
available for production-line budgets and changed-function selection.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .util import git_diff, git_output


def comparison_ref(root: Path, base: str) -> str | None:
    """Resolve a stable commit for net comparison against the worktree."""
    code, stdout, _ = git_output(root, ["merge-base", base, "HEAD"])
    if code == 0 and stdout.strip():
        return stdout.strip()
    code, stdout, _ = git_output(root, ["rev-parse", "--verify", f"{base}^{{commit}}"])
    return stdout.strip() if code == 0 and stdout.strip() else None


def net_diff(root: Path, base: str) -> tuple[str, str | None]:
    """Return one net unified-0 diff and the comparison commit used."""
    ref = comparison_ref(root, base)
    if ref is None:
        return git_diff(root, base, unified=0), None
    code, stdout, _ = git_output(
        root,
        ["diff", "--no-ext-diff", "--no-textconv", "--unified=0", ref, "--"],
    )
    if code == 0:
        return stdout, ref
    return git_diff(root, base, unified=0), ref


def untracked_targets(root: Path, changed: list[str]) -> set[str]:
    """Return untracked paths among the mutation targets."""
    if not changed:
        return set()
    code, stdout, _ = git_output(
        root,
        ["ls-files", "--others", "--exclude-standard", "-z", "--", *changed],
    )
    return {path for path in stdout.split("\0") if path} if code == 0 else set()


def _diff_path_header(
    line: str,
    state: dict[str, Any],
    changed: set[str],
    changes: dict[str, dict[str, Any]],
) -> bool:
    if state["in_hunk"]:
        return False
    if line.startswith("--- "):
        state["old_path"] = line[6:] if line.startswith("--- a/") else ""
        return True
    if not line.startswith("+++ "):
        return False
    candidate = line[6:] if line.startswith("+++ b/") else ""
    state["path"] = candidate if candidate in changed else ""
    if state["path"]:
        changes.setdefault(
            state["path"],
            {
                "added": set(),
                "deleted": set(),
                "old_path": state["old_path"] or state["path"],
            },
        )
    return True


def _diff_hunk_header(line: str, state: dict[str, Any]) -> bool:
    if not line.startswith("@@"):
        return False
    match = re.search(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
    state["old_line"] = int(match.group(1)) if match else 0
    state["new_line"] = int(match.group(2)) if match else 0
    state["in_hunk"] = match is not None
    return True


def _diff_header(
    line: str,
    state: dict[str, Any],
    changed: set[str],
    changes: dict[str, dict[str, Any]],
) -> bool:
    if line.startswith("diff --git "):
        state.update(old_path="", path="", in_hunk=False)
        return True
    if _diff_path_header(line, state, changed, changes):
        return True
    return _diff_hunk_header(line, state)


def _diff_body(line: str, state: dict[str, Any], changes: dict[str, dict[str, Any]]) -> None:
    path = state["path"]
    if not path:
        return
    if line.startswith("-"):
        changes[path]["deleted"].add(state["old_line"])
        state["old_line"] += 1
        return
    if line.startswith("+"):
        changes[path]["added"].add(state["new_line"])
        state["new_line"] += 1
        return
    state["old_line"] += 1
    state["new_line"] += 1


def parse_mutation_diff(diff: str, changed: list[str]) -> dict[str, dict[str, Any]]:
    """Parse unified-0 diff text into per-path added/deleted line numbers."""
    changes: dict[str, dict[str, Any]] = {}
    state: dict[str, Any] = {
        "old_path": "",
        "path": "",
        "old_line": 0,
        "new_line": 0,
        "in_hunk": False,
    }
    changed_set = set(changed)
    for line in diff.splitlines():
        if not _diff_header(line, state, changed_set, changes):
            _diff_body(line, state, changes)
    return changes


def add_untracked_lines(
    root: Path, changed: list[str], changes: dict[str, dict[str, Any]]
) -> None:
    """Treat fully untracked targets as pure additions of every current line."""
    for path in sorted(untracked_targets(root, changed)):
        if path in changes:
            continue
        source_path = root / path
        if not source_path.is_file():
            continue
        line_count = len(source_path.read_text(encoding="utf-8", errors="replace").splitlines())
        changes[path] = {
            "added": set(range(1, line_count + 1)),
            "deleted": set(),
            "old_path": path,
        }


def line_changes(
    root: Path, base: str, changed: list[str]
) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Return net added/deleted line numbers for the current mutation targets."""
    diff, ref = net_diff(root, base)
    changes = parse_mutation_diff(diff, changed)
    add_untracked_lines(root, changed, changes)
    return changes, ref


def old_source(
    root: Path, comparison: str | None, path: str
) -> tuple[str | None, str | None]:
    """Load a path's contents at the comparison commit."""
    if comparison is None:
        return None, "comparison source is unavailable"
    code, stdout, stderr = git_output(root, ["show", f"{comparison}:{path}"])
    if code != 0:
        return None, stderr.strip() or f"{path} is unavailable at {comparison}"
    return stdout, None


def deleted_file_line_counts(
    root: Path, comparison: str | None, paths: list[str]
) -> tuple[dict[str, int], dict[str, str]]:
    """Count lines in deleted production files from comparison evidence."""
    counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    for path in paths:
        source, error = old_source(root, comparison, path)
        if source is None:
            errors[path] = error or "comparison source is unavailable"
            continue
        counts[path] = len(source.splitlines())
    return counts, errors


def nontrivial_line_numbers(source: str, line_numbers: set[int]) -> set[int]:
    """Keep executable line numbers: non-blank and not full-line comments."""
    lines = source.splitlines()
    return {
        line_no
        for line_no in line_numbers
        if 0 < line_no <= len(lines)
        and (content := lines[line_no - 1].strip())
        and not content.startswith("#")
    }


def deleted_names(root: Path, base: str, *, suffixes: set[str]) -> list[str]:
    """List paths deleted relative to the comparison commit (name-only)."""
    ref = comparison_ref(root, base)
    if ref is None:
        return []
    code, stdout, _ = git_output(
        root, ["diff", "--diff-filter=D", "--name-only", "-z", ref, "--"]
    )
    if code != 0:
        return []
    return [
        path
        for path in stdout.split("\0")
        if path and Path(path).suffix.lower() in suffixes and not (root / path).exists()
    ]
