from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from aqg.approvals import template, validate_approval
from aqg.dashboard import DashboardServer, project_status
from aqg.detect import detect_project
from aqg.policy import load_policy
from aqg.project import load_project, validate_project
from aqg.review import analyze_review
from aqg.scaffold import initialize_project
from aqg.util import change_fingerprint, detect_base_ref, git_changed_files, write_json


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)
    return result.stdout.strip()


class RepoCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="aqg-tests-")
        self.root = Path(self.temp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "aqg@example.invalid")
        git(self.root, "config", "user.name", "AQG Tests")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def commit(self, message: str = "baseline") -> None:
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", message)


class DetectionTests(RepoCase):
    def test_detects_combined_supported_stack(self) -> None:
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src" / "app.ts").write_text("export const answer: number = 42;\n", encoding="utf-8")
        (self.root / "src" / "worker.py").write_text("def answer() -> int:\n    return 42\n", encoding="utf-8")
        (self.root / "index.html").write_text("<!doctype html><title>AQG</title>\n", encoding="utf-8")
        (self.root / "styles.css").write_text("body { margin: 0; }\n", encoding="utf-8")
        (self.root / "tests" / "app.test.ts").write_text("import { test } from 'vitest';\ntest('x', () => {});\n", encoding="utf-8")
        (self.root / "package.json").write_text(json.dumps({"name": "mixed", "devDependencies": {"vitest": "1.0.0"}}), encoding="utf-8")
        detection = detect_project(self.root)
        self.assertTrue(detection.javascript)
        self.assertTrue(detection.typescript)
        self.assertTrue(detection.python)
        self.assertTrue(detection.html)
        self.assertTrue(detection.css)
        self.assertEqual(detection.js_test_runner, "vitest")
        self.assertIn("tests", detection.test_paths)


class SetupTests(RepoCase):
    def test_setup_generates_valid_vendored_runtime_without_network(self) -> None:
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src" / "app.py").write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")
        (self.root / "tests" / "test_app.py").write_text("def test_add():\n    assert 1 + 1 == 2\n", encoding="utf-8")
        result = initialize_project(self.root, owner="@quality-owner", install=False, ci=True, mode="adopt")
        self.assertFalse(result["installed"])
        project = load_project(self.root)
        self.assertEqual(validate_project(project), [])
        self.assertEqual(project["enforcement"]["base_ref"], "HEAD")
        self.assertTrue((self.root / "quality" / "qg.py").is_file())
        self.assertTrue((self.root / "quality" / "_aqg" / "cli.py").is_file())
        self.assertTrue((self.root / ".github" / "workflows" / "quality-gauntlet.yml").is_file())
        command = subprocess.run(
            [sys.executable, "quality/qg.py", "--version"],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(command.returncode, 0, command.stderr)
        self.assertIn("2.0.0", command.stdout)

    def test_static_web_setup_generates_isolated_web_pack(self) -> None:
        (self.root / "index.html").write_text("<!doctype html><html lang='en'><title>Example</title></html>\n", encoding="utf-8")
        (self.root / "styles.css").write_text("body { font-family: sans-serif; }\n", encoding="utf-8")
        initialize_project(self.root, install=False, ci=False)
        project = load_project(self.root)
        self.assertTrue(project["stacks"]["html"])
        self.assertTrue(project["stacks"]["css"])
        self.assertFalse(project["stacks"]["python"])
        self.assertTrue(project["gates"]["acceptance"]["applicable"])
        self.assertTrue((self.root / "quality" / "tools" / "js" / "config" / "htmlvalidate.json").exists())
        self.assertTrue((self.root / "tests" / "aqg-browser" / "aqg-smoke.spec.mjs").exists())


class FingerprintTests(RepoCase):
    def test_untracked_and_modified_files_change_fingerprint(self) -> None:
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.commit()
        baseline = change_fingerprint(self.root, "HEAD")
        (self.root / "src" / "untracked.py").write_text("VALUE = 2\n", encoding="utf-8")
        with_untracked = change_fingerprint(self.root, "HEAD")
        self.assertNotEqual(baseline, with_untracked)
        self.assertIn("src/untracked.py", git_changed_files(self.root, "HEAD"))
        (self.root / "src" / "app.py").write_text("VALUE = 3\n", encoding="utf-8")
        self.assertNotEqual(with_untracked, change_fingerprint(self.root, "HEAD"))

    def test_base_ref_prefers_existing_mainline(self) -> None:
        (self.root / "a.txt").write_text("a\n", encoding="utf-8")
        self.commit()
        current = git(self.root, "branch", "--show-current")
        expected = current if current in {"main", "master"} else "HEAD"
        self.assertEqual(detect_base_ref(self.root), expected)


class ReviewAndApprovalTests(RepoCase):
    def _initialized(self) -> None:
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src" / "app.py").write_text("def calculate(value: int) -> int:\n    return value + 1\n", encoding="utf-8")
        (self.root / "tests" / "test_app.py").write_text("# Feature-Spec: Product.Calculation\ndef test_calculate():\n    assert 2 == 2\n", encoding="utf-8")
        initialize_project(self.root, install=False, ci=False)
        (self.root / "feature-spec" / "Product.Calculation.md").write_text(
            "# Product.Calculation\n\n## Requirements\n\n- The product MUST calculate a result.\n",
            encoding="utf-8",
        )
        self.commit()

    def test_review_blocks_production_change_without_tests_and_suppressions(self) -> None:
        self._initialized()
        (self.root / "src" / "app.py").write_text(
            "def calculate(value: int) -> int:\n    return value - 1  # type: ignore\n",
            encoding="utf-8",
        )
        packet = analyze_review(self.root, load_policy(self.root), base="HEAD", require_evidence=False)
        codes = {finding["code"] for finding in packet["findings"]}
        self.assertIn("production-without-tests", codes)
        self.assertIn("lint-or-type-suppression", codes)

    def test_approval_is_invalidated_by_subsequent_change(self) -> None:
        self._initialized()
        payload = template(self.root, "behavior-review", reviewer="human@example.test")
        payload.update(
            {
                "result": "pass",
                "scope": ["Product.Calculation"],
                "procedure": ["Reviewed active requirement and executable test"],
                "evidence": ["tests/test_app.py"],
            }
        )
        write_json(self.root / "quality" / "approvals" / "behavior-review.json", payload)
        self.assertEqual(validate_approval(self.root, "behavior-review"), [])
        (self.root / "src" / "app.py").write_text("def calculate(value: int) -> int:\n    return value + 2\n", encoding="utf-8")
        errors = validate_approval(self.root, "behavior-review")
        self.assertTrue(any("stale" in error for error in errors), errors)


class DashboardTests(RepoCase):
    def test_dashboard_status_is_read_only_and_uses_same_project_state(self) -> None:
        (self.root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        initialize_project(self.root, install=False, ci=False)
        payload = project_status(self.root)
        self.assertEqual(payload["project"]["name"], self.root.name)
        server = DashboardServer(("127.0.0.1", 0), [self.root], allow_actions=False, token="", verbose=False)
        try:
            status = server.status_payload()
            self.assertFalse(status["portfolio"])
            self.assertEqual(len(status["projects"]), 1)
            self.assertFalse(server.allow_actions)
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
