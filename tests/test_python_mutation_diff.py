# Feature-Spec: AgentQualityGauntlet AQG-CORE-006
"""Boundary tests for net Python mutation diff parsing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aqg.python_mutation_diff import (
    _diff_body,
    _diff_header,
    _diff_hunk_header,
    _diff_path_header,
    add_untracked_lines,
    comparison_ref,
    deleted_file_line_counts,
    deleted_names,
    line_changes,
    net_diff,
    nontrivial_line_numbers,
    old_source,
    parse_mutation_diff,
    untracked_targets,
)


class ParseMutationDiffTests(unittest.TestCase):
    def test_nontrivial_lines_exclude_imports_mutmut_cannot_target(self) -> None:
        source = (
            "import os\n"
            "from package import (\n"
            "    first,\n"
            "    second,\n"
            ")\n"
            "\n"
            "def value() -> str:\n"
            "    return os.environ.get('VALUE', first or second)\n"
        )

        selected = nontrivial_line_numbers(source, set(range(1, 9)))

        self.assertEqual(selected, {7, 8})

    def test_nontrivial_lines_fail_closed_when_source_cannot_be_parsed(self) -> None:
        source = "import (\nvalue = 1\n"

        selected = nontrivial_line_numbers(source, {1, 2})

        self.assertEqual(selected, {1, 2})

    def test_parses_added_and_deleted_line_numbers_from_unified_zero(self) -> None:
        diff = (
            "diff --git a/src/module.py b/src/module.py\n"
            "--- a/src/module.py\n"
            "+++ b/src/module.py\n"
            "@@ -2,2 +2,1 @@\n"
            "-    if not user.is_admin:\n"
            "-        return False\n"
            "+    return True\n"
        )
        changes = parse_mutation_diff(diff, ["src/module.py"])
        self.assertEqual(changes["src/module.py"]["deleted"], {2, 3})
        self.assertEqual(changes["src/module.py"]["added"], {2})
        self.assertEqual(changes["src/module.py"]["old_path"], "src/module.py")

    def test_ignores_paths_outside_the_changed_target_set(self) -> None:
        diff = (
            "diff --git a/src/other.py b/src/other.py\n"
            "--- a/src/other.py\n"
            "+++ b/src/other.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        self.assertEqual(parse_mutation_diff(diff, ["src/module.py"]), {})

    def test_records_old_path_for_renames_when_new_path_is_targeted(self) -> None:
        diff = (
            "diff --git a/src/old_name.py b/src/new_name.py\n"
            "--- a/src/old_name.py\n"
            "+++ b/src/new_name.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        changes = parse_mutation_diff(diff, ["src/new_name.py"])
        self.assertEqual(changes["src/new_name.py"]["old_path"], "src/old_name.py")
        self.assertEqual(changes["src/new_name.py"]["deleted"], {1})
        self.assertEqual(changes["src/new_name.py"]["added"], {1})

    def test_handles_hunk_headers_without_comma_counts(self) -> None:
        diff = (
            "diff --git a/src/module.py b/src/module.py\n"
            "--- a/src/module.py\n"
            "+++ b/src/module.py\n"
            "@@ -4 +4 @@\n"
            "-    return 1\n"
            "+    return 2\n"
        )
        changes = parse_mutation_diff(diff, ["src/module.py"])
        self.assertEqual(changes["src/module.py"]["deleted"], {4})
        self.assertEqual(changes["src/module.py"]["added"], {4})

    def test_advances_line_counters_for_context_lines(self) -> None:
        diff = (
            "diff --git a/src/module.py b/src/module.py\n"
            "--- a/src/module.py\n"
            "+++ b/src/module.py\n"
            "@@ -1,3 +1,3 @@\n"
            " def value() -> int:\n"
            "-    return 1\n"
            "+    return 2\n"
            "\n"
        )
        changes = parse_mutation_diff(diff, ["src/module.py"])
        self.assertEqual(changes["src/module.py"]["deleted"], {2})
        self.assertEqual(changes["src/module.py"]["added"], {2})

    def test_resets_path_state_between_file_headers(self) -> None:
        diff = (
            "diff --git a/src/a.py b/src/a.py\n"
            "--- a/src/a.py\n"
            "+++ b/src/a.py\n"
            "@@ -1 +1 @@\n"
            "-a_old\n"
            "+a_new\n"
            "diff --git a/src/b.py b/src/b.py\n"
            "--- a/src/b.py\n"
            "+++ b/src/b.py\n"
            "@@ -5 +5 @@\n"
            "-b_old\n"
            "+b_new\n"
        )
        changes = parse_mutation_diff(diff, ["src/a.py", "src/b.py"])
        self.assertEqual(changes["src/a.py"]["added"], {1})
        self.assertEqual(changes["src/b.py"]["deleted"], {5})

    def test_treats_dev_null_new_file_as_additions_only(self) -> None:
        diff = (
            "diff --git a/src/new.py b/src/new.py\n"
            "--- /dev/null\n"
            "+++ b/src/new.py\n"
            "@@ -0,0 +1,2 @@\n"
            "+def value() -> int:\n"
            "+    return 1\n"
        )
        changes = parse_mutation_diff(diff, ["src/new.py"])
        self.assertEqual(changes["src/new.py"]["added"], {1, 2})
        self.assertEqual(changes["src/new.py"]["deleted"], set())
        self.assertEqual(changes["src/new.py"]["old_path"], "src/new.py")

    def test_ignores_binary_or_header_noise_outside_hunks(self) -> None:
        diff = (
            "diff --git a/src/module.py b/src/module.py\n"
            "index 111..222 100644\n"
            "--- a/src/module.py\n"
            "+++ b/src/module.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        changes = parse_mutation_diff(diff, ["src/module.py"])
        self.assertEqual(changes["src/module.py"]["added"], {1})
        self.assertEqual(changes["src/module.py"]["deleted"], {1})

    def test_empty_diff_yields_empty_changes(self) -> None:
        self.assertEqual(parse_mutation_diff("", ["src/module.py"]), {})

    def test_malformed_hunk_header_records_zero_based_placeholders(self) -> None:
        """Invalid @@ headers leave counters at 0; nontrivial filter drops them later."""
        diff = (
            "diff --git a/src/module.py b/src/module.py\n"
            "--- a/src/module.py\n"
            "+++ b/src/module.py\n"
            "@@ broken hunk @@\n"
            "-old\n"
            "+new\n"
        )
        changes = parse_mutation_diff(diff, ["src/module.py"])
        self.assertEqual(changes["src/module.py"]["deleted"], {0})
        self.assertEqual(changes["src/module.py"]["added"], {0})
        self.assertEqual(nontrivial_line_numbers("old\nnew\n", {0}), set())

    def test_plus_plus_plus_without_b_prefix_does_not_select_path(self) -> None:
        diff = (
            "diff --git a/src/module.py b/src/module.py\n"
            "--- a/src/module.py\n"
            "+++ src/module.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        self.assertEqual(parse_mutation_diff(diff, ["src/module.py"]), {})

    def test_body_lines_ignored_when_path_unset(self) -> None:
        state = {
            "old_path": "",
            "path": "",
            "old_line": 1,
            "new_line": 1,
            "in_hunk": True,
        }
        changes: dict[str, dict[str, object]] = {}
        _diff_body("-gone\n", state, changes)
        _diff_body("+here\n", state, changes)
        self.assertEqual(changes, {})
        self.assertEqual(state["old_line"], 1)
        self.assertEqual(state["new_line"], 1)


class DiffHelperUnitTests(unittest.TestCase):
    def test_path_header_sets_old_path_from_a_prefix(self) -> None:
        state = {"old_path": "", "path": "", "in_hunk": False}
        changes: dict[str, dict[str, object]] = {}
        self.assertTrue(_diff_path_header("--- a/src/old.py", state, set(), changes))
        self.assertEqual(state["old_path"], "src/old.py")

    def test_path_header_ignores_non_a_minus_lines_for_old_path(self) -> None:
        state = {"old_path": "keep", "path": "", "in_hunk": False}
        self.assertTrue(_diff_path_header("--- /dev/null", state, set(), {}))
        self.assertEqual(state["old_path"], "")

    def test_path_header_noop_inside_hunk(self) -> None:
        state = {"old_path": "", "path": "src/a.py", "in_hunk": True}
        self.assertFalse(_diff_path_header("--- a/src/a.py", state, {"src/a.py"}, {}))

    def test_path_header_creates_change_bucket_with_fallback_old_path(self) -> None:
        state = {"old_path": "", "path": "", "in_hunk": False}
        changes: dict[str, dict[str, object]] = {}
        self.assertTrue(_diff_path_header("+++ b/src/module.py", state, {"src/module.py"}, changes))
        self.assertEqual(state["path"], "src/module.py")
        self.assertEqual(changes["src/module.py"]["old_path"], "src/module.py")
        self.assertEqual(changes["src/module.py"]["added"], set())
        self.assertEqual(changes["src/module.py"]["deleted"], set())

    def test_hunk_header_sets_line_numbers_and_in_hunk_flag(self) -> None:
        state = {"old_line": 0, "new_line": 0, "in_hunk": False}
        self.assertTrue(_diff_hunk_header("@@ -10,2 +20,3 @@ def value", state))
        self.assertEqual(state["old_line"], 10)
        self.assertEqual(state["new_line"], 20)
        self.assertTrue(state["in_hunk"])

    def test_hunk_header_rejects_non_hunk_lines(self) -> None:
        state = {"old_line": 3, "new_line": 4, "in_hunk": True}
        self.assertFalse(_diff_hunk_header("not a hunk", state))
        self.assertEqual(state["old_line"], 3)
        self.assertTrue(state["in_hunk"])

    def test_hunk_header_zeroes_counters_on_malformed_match(self) -> None:
        state = {"old_line": 9, "new_line": 9, "in_hunk": True}
        self.assertTrue(_diff_hunk_header("@@ broken @@", state))
        self.assertEqual(state["old_line"], 0)
        self.assertEqual(state["new_line"], 0)
        self.assertFalse(state["in_hunk"])

    def test_diff_header_resets_paths_on_git_header(self) -> None:
        state = {
            "old_path": "x",
            "path": "y",
            "old_line": 5,
            "new_line": 6,
            "in_hunk": True,
        }
        self.assertTrue(_diff_header("diff --git a/x b/y", state, set(), {}))
        self.assertEqual(state["old_path"], "")
        self.assertEqual(state["path"], "")
        self.assertFalse(state["in_hunk"])
        self.assertEqual(state["old_line"], 5)

    def test_diff_body_records_delete_add_and_context(self) -> None:
        state = {
            "path": "src/module.py",
            "old_line": 2,
            "new_line": 2,
            "in_hunk": True,
        }
        changes = {"src/module.py": {"added": set(), "deleted": set(), "old_path": "src/module.py"}}
        _diff_body("-old", state, changes)
        self.assertEqual(changes["src/module.py"]["deleted"], {2})
        self.assertEqual(state["old_line"], 3)
        _diff_body("+new", state, changes)
        self.assertEqual(changes["src/module.py"]["added"], {2})
        self.assertEqual(state["new_line"], 3)
        _diff_body(" context", state, changes)
        self.assertEqual(state["old_line"], 4)
        self.assertEqual(state["new_line"], 4)


class NontrivialLineNumberTests(unittest.TestCase):
    def test_filters_blank_and_comment_lines(self) -> None:
        source = "def value() -> int:\n    # note\n\n    return 1\n"
        self.assertEqual(nontrivial_line_numbers(source, {1, 2, 3, 4}), {1, 4})

    def test_ignores_out_of_range_line_numbers(self) -> None:
        source = "x = 1\n"
        self.assertEqual(nontrivial_line_numbers(source, {0, 1, 2, 99}), {1})


class ComparisonAndUntrackedTests(unittest.TestCase):
    def test_old_source_requires_comparison_ref(self) -> None:
        source, error = old_source(Path("."), None, "src/a.py")
        self.assertIsNone(source)
        self.assertEqual(error, "comparison source is unavailable")

    def test_deleted_file_line_counts_records_errors_and_counts(self) -> None:
        counts, errors = deleted_file_line_counts(Path("."), None, ["src/a.py"])
        self.assertEqual(counts, {})
        self.assertEqual(errors["src/a.py"], "comparison source is unavailable")

    def test_untracked_targets_empty_for_empty_changed(self) -> None:
        self.assertEqual(untracked_targets(Path("."), []), set())

    def test_add_untracked_lines_fills_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = "module.py"
            (root / path).write_text("a\nb\n", encoding="utf-8")
            seen: list[tuple[object, object]] = []

            def capture(received_root: object, received_changed: object) -> set[str]:
                seen.append((received_root, received_changed))
                return {path}

            with patch(
                "aqg.python_mutation_diff.untracked_targets",
                side_effect=capture,
            ):
                changes: dict[str, dict[str, object]] = {}
                add_untracked_lines(root, [path], changes)
            self.assertEqual(seen, [(root, [path])])
            self.assertEqual(changes[path]["added"], {1, 2})
            self.assertEqual(changes[path]["deleted"], set())
            self.assertEqual(changes[path]["old_path"], path)

    def test_add_untracked_lines_skips_existing_change_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = "module.py"
            (root / path).write_text("a\n", encoding="utf-8")
            changes = {
                path: {"added": {9}, "deleted": set(), "old_path": path},
            }
            with patch(
                "aqg.python_mutation_diff.untracked_targets",
                return_value={path},
            ):
                add_untracked_lines(root, [path], changes)
            self.assertEqual(changes[path]["added"], {9})

    def test_add_untracked_lines_continues_past_existing_buckets(self) -> None:
        """Already-known paths must be skipped without aborting later untracked files."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            known = "alpha.py"
            fresh = "beta.py"
            (root / known).write_text("keep\n", encoding="utf-8")
            (root / fresh).write_text("one\ntwo\n", encoding="utf-8")
            changes: dict[str, dict[str, object]] = {
                known: {"added": {42}, "deleted": set(), "old_path": known},
            }
            with patch(
                "aqg.python_mutation_diff.untracked_targets",
                return_value={known, fresh},
            ):
                add_untracked_lines(root, [known, fresh], changes)
            self.assertEqual(changes[known]["added"], {42})
            self.assertEqual(changes[fresh]["added"], {1, 2})
            self.assertEqual(changes[fresh]["deleted"], set())
            self.assertEqual(changes[fresh]["old_path"], fresh)

    def test_comparison_ref_returns_none_when_git_unavailable(self) -> None:
        with patch("aqg.python_mutation_diff.git_output", return_value=(1, "", "err")):
            self.assertIsNone(comparison_ref(Path("."), "HEAD"))

    def test_net_diff_falls_back_when_comparison_missing(self) -> None:
        with (
            patch("aqg.python_mutation_diff.comparison_ref", return_value=None),
            patch("aqg.python_mutation_diff.git_diff", return_value="DIFF") as git_diff,
        ):
            diff, ref = net_diff(Path("."), "HEAD")
        self.assertEqual(diff, "DIFF")
        self.assertIsNone(ref)
        git_diff.assert_called_once()

    def test_deleted_names_empty_without_comparison(self) -> None:
        with patch("aqg.python_mutation_diff.comparison_ref", return_value=None):
            self.assertEqual(deleted_names(Path("."), "HEAD", suffixes={".py"}), [])

    def test_deleted_names_requires_matching_suffix_and_missing_worktree_file(self) -> None:
        """Only deleted production-suffix paths remain; still-present or wrong-suffix paths drop."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "still_present.py").write_text("x = 1\n", encoding="utf-8")
            # gone.py is absent from the worktree; other.txt is also absent but wrong suffix.
            listing = "\0".join(["still_present.py", "gone.py", "other.txt", ""])
            with (
                patch("aqg.python_mutation_diff.comparison_ref", return_value="abc123"),
                patch(
                    "aqg.python_mutation_diff.git_output",
                    return_value=(0, listing, ""),
                ) as git_output,
            ):
                names = deleted_names(root, "HEAD", suffixes={".py"})
            self.assertEqual(names, ["gone.py"])
            git_output.assert_called_once()
            self.assertEqual(
                git_output.call_args.args[1],
                ["diff", "--diff-filter=D", "--name-only", "-z", "abc123", "--"],
            )

    def test_line_changes_uses_parse_and_untracked(self) -> None:
        with (
            patch(
                "aqg.python_mutation_diff.net_diff",
                return_value=("diff --git a/a.py b/a.py\n", "abc"),
            ),
            patch(
                "aqg.python_mutation_diff.parse_mutation_diff",
                return_value={"a.py": {"added": {1}, "deleted": set(), "old_path": "a.py"}},
            ) as parse,
            patch("aqg.python_mutation_diff.add_untracked_lines") as add_untracked,
        ):
            changes, ref = line_changes(Path("."), "HEAD", ["a.py"])
        self.assertEqual(ref, "abc")
        self.assertEqual(changes["a.py"]["added"], {1})
        parse.assert_called_once()
        add_untracked.assert_called_once()


if __name__ == "__main__":
    unittest.main()
