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
            "policy-evidence",
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

    def test_authoritative_profile_installs_browser_and_retains_checker_reports(self) -> None:
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "quality-gauntlet.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("AQG_DIFF_BASE=$AQG_BASE", workflow)
        self.assertIn('github.event_name }}" == "workflow_dispatch"', workflow)
        self.assertIn("github.event.repository.default_branch", workflow)
        self.assertIn('AQG_BASE="origin/$AQG_TARGET"', workflow)
        self.assertNotIn('AQG_BASE="HEAD~1"', workflow)
        self.assertIn("tools install --ci --browsers", workflow)
        self.assertIn(".aqg/work/*/report.json", workflow)
        self.assertIn(".aqg/work/coverage/*.json", workflow)
        self.assertIn(".aqg/work/supply_chain/sbom/*.json", workflow)

        release = workflow.split("  release-build:\n", 1)[1]
        self.assertIn("needs: [test, policy-evidence]", release)
        self.assertIn("Attest release provenance", release)

    def test_hosted_workflows_checkout_the_exact_candidate_revision(self) -> None:
        root = Path(__file__).resolve().parents[1]
        paths = [
            *sorted((root / ".github" / "workflows").glob("*.yml")),
            root / "ci" / "github-actions-quality.yml.example",
        ]
        exact_candidate_ref = "ref: ${{ github.event.pull_request.head.sha || github.sha }}"

        for path in paths:
            workflow = path.read_text(encoding="utf-8")
            checkout_count = workflow.count("uses: actions/checkout@")
            self.assertGreater(checkout_count, 0, path.relative_to(root).as_posix())
            self.assertEqual(
                workflow.count(exact_candidate_ref),
                checkout_count,
                (
                    f"{path.relative_to(root).as_posix()} must bind every checkout "
                    "to the pull-request head SHA instead of GitHub's synthetic merge commit"
                ),
            )


if __name__ == "__main__":
    unittest.main()
