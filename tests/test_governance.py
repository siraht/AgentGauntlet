from __future__ import annotations

import json
import unittest
from pathlib import Path


class GitHubGovernanceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.ruleset = json.loads(
            (root / "quality" / "github" / "main-ruleset.json").read_text(encoding="utf-8")
        )
        cls.rules = {rule["type"]: rule for rule in cls.ruleset["rules"]}

    def test_default_branch_requires_review_without_bypass(self) -> None:
        self.assertEqual(self.ruleset["enforcement"], "active")
        self.assertEqual(self.ruleset["bypass_actors"], [])
        self.assertEqual(
            self.ruleset["conditions"]["ref_name"]["include"],
            ["~DEFAULT_BRANCH"],
        )
        self.assertTrue(
            {"deletion", "non_fast_forward", "required_linear_history", "pull_request"}
            <= self.rules.keys()
        )
        review = self.rules["pull_request"]["parameters"]
        self.assertEqual(review["required_approving_review_count"], 1)
        self.assertTrue(review["dismiss_stale_reviews_on_push"])
        self.assertTrue(review["require_last_push_approval"])
        self.assertTrue(review["required_review_thread_resolution"])

    def test_repository_review_scope_uses_the_published_mainline(self) -> None:
        root = Path(__file__).resolve().parents[1]
        project = json.loads((root / "quality" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(project["enforcement"]["base_ref"], "origin/main")
        self.assertEqual(
            project["python"]["test_paths"],
            ["tests", "agent_ergonomics_audit/audit/regression_tests"],
        )

    def test_every_hosted_gauntlet_context_is_pinned_to_github_actions(self) -> None:
        expected = {
            "Python 3.11",
            "Python 3.12",
            "Python 3.13",
            "release-build",
            "Contract (ubuntu-latest, Python 3.11)",
            "Contract (ubuntu-latest, Python 3.13)",
            "Contract (macos-latest, Python 3.11)",
            "Contract (macos-latest, Python 3.13)",
            "Contract (windows-latest, Python 3.11)",
            "Contract (windows-latest, Python 3.13)",
            "Live project adapters",
            "Browser and accessibility adapter",
        }
        parameters = self.rules["required_status_checks"]["parameters"]
        required = parameters["required_status_checks"]
        self.assertTrue(parameters["strict_required_status_checks_policy"])
        self.assertEqual({check["context"] for check in required}, expected)
        self.assertEqual({check["integration_id"] for check in required}, {15368})


if __name__ == "__main__":
    unittest.main()
