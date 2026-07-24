import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("qg", ROOT / "quality" / "qg.py")
qg = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(qg)


class PatternTests(unittest.TestCase):
    def test_double_star_root_match(self):
        self.assertTrue(qg.matches_any("golden/output.yaml", ["**/golden/**"]))

    def test_directory_descendant_match(self):
        self.assertTrue(qg.matches_any("quality/hooks/check.py", ["quality/hooks/**"]))

    def test_unrelated_path_does_not_match(self):
        self.assertFalse(qg.matches_any("src/quality_model.py", ["quality/**"]))

    def test_relative_paths_are_resolved_from_repository_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "src" / "module"
            nested.mkdir(parents=True)
            old = Path.cwd()
            try:
                os.chdir(nested)
                self.assertEqual(qg.relpath(root, "quality/policy.toml"), "quality/policy.toml")
            finally:
                os.chdir(old)


class PatchTests(unittest.TestCase):
    def test_extracts_apply_patch_paths(self):
        patch = """*** Begin Patch
*** Update File: quality/policy.toml
@@
-x
+y
*** Add File: src/new.py
*** End Patch
"""
        self.assertEqual(
            qg.patch_paths(patch),
            ["quality/policy.toml", "src/new.py"],
        )

    def test_extracts_path_from_mutating_mcp_tool(self):
        paths = qg.direct_write_paths(
            "mcp__filesystem__update_file",
            {"path": "quality/policy.toml", "content": "x"},
        )
        self.assertEqual(paths, ["quality/policy.toml"])


class CleanupTests(unittest.TestCase):
    def test_refuses_repository_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(qg.PolicyError):
                qg.safe_remove(root, ".")

    def test_removes_only_inside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "build" / "x"
            target.mkdir(parents=True)
            (target / "artifact").write_text("x")
            qg.safe_remove(root, "build/x")
            self.assertFalse(target.exists())


class ExitClassificationTests(unittest.TestCase):
    def test_contract(self):
        self.assertEqual(qg.classify_exit(0, {1}), "pass")
        self.assertEqual(qg.classify_exit(1, {1}), "fail")
        self.assertEqual(qg.classify_exit(2, {1}), "configuration_error")
        self.assertEqual(qg.classify_exit(3, {1}), "infrastructure_error")
        self.assertEqual(qg.classify_exit(99, {1}), "infrastructure_error")


class OverrideTests(unittest.TestCase):
    def test_authoritative_checks_reject_maintenance_override(self):
        policy = {"policy": {"policy_maintenance_env": "AQG_TEST_MAINTENANCE"}}
        old = os.environ.get("AQG_TEST_MAINTENANCE")
        try:
            os.environ["AQG_TEST_MAINTENANCE"] = "1"
            self.assertIn(
                "unsafe override AQG_TEST_MAINTENANCE=1 is enabled",
                qg.unsafe_override_errors(policy),
            )
        finally:
            if old is None:
                os.environ.pop("AQG_TEST_MAINTENANCE", None)
            else:
                os.environ["AQG_TEST_MAINTENANCE"] = old


class RiskCardTests(unittest.TestCase):
    def setUp(self):
        self.policy = {
            "risk_rules": {
                "minimum_profile_by_factor": {
                    "authorization": "high_assurance",
                    "safety": "critical",
                }
            },
            "risk_profiles": {
                "experiment": {"required_execution_profiles": ["fast"]},
                "standard": {"required_execution_profiles": ["pr"]},
                "high_assurance": {"required_execution_profiles": ["deep"]},
                "critical": {"required_execution_profiles": ["release"]},
            },
        }

    def card(self):
        return {
            "schema_version": "1",
            "summary": "Change one observable behavior.",
            "risk_profile": "standard",
            "production_scope": True,
            "reversible": True,
            "blast_radius": "single_service",
            "behavior_changes": ["The output changes."],
            "behavior_preserved": ["Authorization remains unchanged."],
            "risk_factors": {"authorization": False, "safety": False},
            "failure_detection": "Acceptance tests and telemetry.",
            "rollback": "Restore the previous release.",
            "human_review": ["Gherkin examples"],
        }

    def test_production_change_requires_standard(self):
        minimum, reasons = qg.minimum_risk_profile(self.card(), self.policy)
        self.assertEqual(minimum, "standard")
        self.assertIn("production_scope=true", reasons)

    def test_authorization_change_requires_high_assurance(self):
        card = self.card()
        card["risk_factors"]["authorization"] = True
        minimum, _ = qg.minimum_risk_profile(card, self.policy)
        self.assertEqual(minimum, "high_assurance")

    def test_safety_change_requires_critical(self):
        card = self.card()
        card["risk_factors"]["safety"] = True
        minimum, _ = qg.minimum_risk_profile(card, self.policy)
        self.assertEqual(minimum, "critical")

    def test_missing_configured_factor_is_invalid(self):
        card = self.card()
        del card["risk_factors"]["safety"]
        errors = qg.risk_card_errors(card, self.policy)
        self.assertTrue(any("safety" in error for error in errors))

    def test_underclassification_reports_minimum_controls(self):
        card = self.card()
        card["risk_factors"]["safety"] = True
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            card_path = root / "change-risk.json"
            card_path.write_text(json.dumps(card))
            result, payload = qg.risk_card_summary(root, self.policy, str(card_path))
        self.assertEqual(result, qg.CONFIGURATION_ERROR)
        self.assertEqual(payload["effective_risk_profile"], "critical")
        self.assertEqual(payload["required_execution_profiles"], ["release"])


if __name__ == "__main__":
    unittest.main()
