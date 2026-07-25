from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from aqg.adapters import _python_crap, run_adapter
from aqg.approvals import template, validate_approval
from aqg.cli import build_parser
from aqg.constants import CONFIGURATION_ERROR, PASS
from aqg.dashboard import DashboardServer, project_status
from aqg.detect import detect_project
from aqg.policy import GATE_NAMES, load_policy, render_policy
from aqg.project import load_project, validate_project
from aqg.review import analyze_review
from aqg.runner import run_gate
from aqg.sbom import (
    generate_sboms,
    javascript_inventory,
    python_inventory,
    validate_cyclonedx_document,
)
from aqg.scaffold import initialize_project
from aqg.util import change_fingerprint, detect_base_ref, git_changed_files, read_json, write_json


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
        (self.root / "src" / "app.ts").write_text(
            "export const answer: number = 42;\n", encoding="utf-8"
        )
        (self.root / "src" / "worker.py").write_text(
            "def answer() -> int:\n    return 42\n", encoding="utf-8"
        )
        (self.root / "index.html").write_text(
            "<!doctype html><title>AQG</title>\n", encoding="utf-8"
        )
        (self.root / "styles.css").write_text("body { margin: 0; }\n", encoding="utf-8")
        (self.root / "tests" / "app.test.ts").write_text(
            "import { test } from 'vitest';\ntest('x', () => {});\n", encoding="utf-8"
        )
        (self.root / "package.json").write_text(
            json.dumps({"name": "mixed", "devDependencies": {"vitest": "1.0.0"}}), encoding="utf-8"
        )
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
        (self.root / "src" / "app.py").write_text(
            "def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8"
        )
        (self.root / "tests" / "test_app.py").write_text(
            "def test_add():\n    assert 1 + 1 == 2\n", encoding="utf-8"
        )
        result = initialize_project(
            self.root, owner="@quality-owner", install=False, ci=True, mode="adopt"
        )
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
        (self.root / "index.html").write_text(
            "<!doctype html><html lang='en'><title>Example</title></html>\n", encoding="utf-8"
        )
        (self.root / "styles.css").write_text(
            "body { font-family: sans-serif; }\n", encoding="utf-8"
        )
        initialize_project(self.root, install=False, ci=False)
        project = load_project(self.root)
        self.assertTrue(project["stacks"]["html"])
        self.assertTrue(project["stacks"]["css"])
        self.assertFalse(project["stacks"]["python"])
        self.assertTrue(project["gates"]["acceptance"]["applicable"])
        self.assertTrue(
            (self.root / "quality" / "tools" / "js" / "config" / "htmlvalidate.json").exists()
        )
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
        (self.root / "src" / "app.py").write_text(
            "def calculate(value: int) -> int:\n    return value + 1\n", encoding="utf-8"
        )
        (self.root / "tests" / "test_app.py").write_text(
            "# Feature-Spec: Product.Calculation\ndef test_calculate():\n    assert 2 == 2\n",
            encoding="utf-8",
        )
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
        packet = analyze_review(
            self.root, load_policy(self.root), base="HEAD", require_evidence=False
        )
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
        (self.root / "src" / "app.py").write_text(
            "def calculate(value: int) -> int:\n    return value + 2\n", encoding="utf-8"
        )
        errors = validate_approval(self.root, "behavior-review")
        self.assertTrue(any("stale" in error for error in errors), errors)


class DashboardTests(RepoCase):
    def test_dashboard_status_is_read_only_and_uses_same_project_state(self) -> None:
        (self.root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        initialize_project(self.root, install=False, ci=False)
        payload = project_status(self.root)
        self.assertEqual(payload["project"]["name"], self.root.name)
        server = DashboardServer(
            ("127.0.0.1", 0), [self.root], allow_actions=False, token="", verbose=False
        )
        try:
            status = server.status_payload()
            self.assertFalse(status["portfolio"])
            self.assertEqual(len(status["projects"]), 1)
            self.assertFalse(server.allow_actions)
        finally:
            server.server_close()


class SupplyChainTests(RepoCase):
    def test_package_lock_inventory_is_sorted_and_valid(self) -> None:
        (self.root / "package.json").write_text(
            json.dumps(
                {
                    "name": "web",
                    "version": "1.2.3",
                    "dependencies": {"zeta": "2.0.0", "alpha": "1.0.0"},
                }
            ),
            encoding="utf-8",
        )
        write_json(
            self.root / "package-lock.json",
            {
                "lockfileVersion": 3,
                "packages": {
                    "": {"name": "web", "version": "1.2.3"},
                    "node_modules/zeta": {"name": "zeta", "version": "2.0.0"},
                    "node_modules/alpha": {"name": "alpha", "version": "1.0.0"},
                },
            },
        )
        inventory = javascript_inventory(self.root)
        self.assertTrue(inventory.complete)
        self.assertEqual([item["name"] for item in inventory.components], ["alpha", "zeta"])
        payload = generate_sboms(
            self.root,
            {"stacks": {"javascript": True, "python": False}},
            include_toolchains=False,
        )
        document = read_json(self.root / payload["artifacts"][0]["artifact"])
        self.assertEqual(validate_cyclonedx_document(document), [])

    def test_javascript_dependencies_without_lock_fail_closed(self) -> None:
        (self.root / "package.json").write_text(
            json.dumps({"name": "web", "dependencies": {"left-pad": "1.3.0"}}),
            encoding="utf-8",
        )
        inventory = javascript_inventory(self.root)
        self.assertFalse(inventory.complete)
        self.assertIn("no supported committed lockfile", inventory.reason)

    def test_exact_python_requirements_create_complete_inventory(self) -> None:
        (self.root / "requirements.txt").write_text(
            "Requests==2.32.3\nidna==3.10\n", encoding="utf-8"
        )
        inventory = python_inventory(self.root)
        self.assertTrue(inventory.complete)
        self.assertEqual([item["name"] for item in inventory.components], ["idna", "requests"])

    def test_unpinned_python_requirements_fail_closed(self) -> None:
        (self.root / "requirements.txt").write_text("requests>=2\n", encoding="utf-8")
        inventory = python_inventory(self.root)
        self.assertFalse(inventory.complete)
        self.assertIn("no exact dependency components", inventory.reason)

    def test_sbom_component_document_is_byte_deterministic(self) -> None:
        (self.root / "requirements.txt").write_text("idna==3.10\n", encoding="utf-8")
        project = {"stacks": {"javascript": False, "python": True}}
        first = generate_sboms(self.root, project, include_toolchains=False)
        artifact = self.root / first["artifacts"][0]["artifact"]
        initial = artifact.read_bytes()
        second = generate_sboms(self.root, project, include_toolchains=False)
        self.assertEqual(initial, (self.root / second["artifacts"][0]["artifact"]).read_bytes())

    def test_supply_chain_adapter_returns_configuration_error_for_missing_lock(self) -> None:
        (self.root / "package.json").write_text(
            json.dumps({"name": "web", "dependencies": {"left-pad": "1.3.0"}}),
            encoding="utf-8",
        )
        initialize_project(self.root, install=False, ci=False, mode="greenfield")
        code, report = run_adapter(self.root, "supply_chain")
        self.assertEqual(code, CONFIGURATION_ERROR)
        self.assertFalse(report["inventory"]["complete"])


class SetupContractTests(RepoCase):
    def test_auto_mode_selects_greenfield_without_history(self) -> None:
        (self.root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        result = initialize_project(self.root, install=False, ci=False, mode="auto")
        self.assertEqual(result["project"]["enforcement"]["mode"], "greenfield")
        self.assertEqual(result["project"]["enforcement"]["scope"], "full")

    def test_changed_files_expand_nested_untracked_files_without_history(self) -> None:
        nested = self.root / "src" / "package"
        nested.mkdir(parents=True)
        (nested / "module.py").write_text("VALUE = 1\n", encoding="utf-8")

        self.assertIn("src/package/module.py", git_changed_files(self.root))
        self.assertNotIn("src/", git_changed_files(self.root))

    def test_empty_changed_scope_does_not_fall_back_to_full_crap_analysis(self) -> None:
        report = _python_crap(
            self.root,
            {
                "enforcement": {"mode": "adopt"},
                "paths": {"source": ["src"]},
                "profile_thresholds": {},
                "thresholds": {"structure": {"max_crap": 15}},
            },
            self.root / "missing-coverage.json",
            [],
        )

        self.assertEqual(report["scope"], "none")
        self.assertEqual(report["functions"], [])
        self.assertEqual(report["failures"], [])

    def test_gate_commands_do_not_invoke_a_shell(self) -> None:
        escaped = self.root / "escaped"
        policy = {
            "gates": {
                "probe": {
                    "command": f"python3 -c \"print('ok')\" ; touch {escaped}",
                    "clean_paths": [],
                    "quality_failure_exit_codes": [1],
                    "timeout_seconds": 10,
                }
            }
        }

        code, evidence = run_gate(self.root, policy, "probe", "shell-safety")

        self.assertEqual(code, PASS)
        self.assertEqual(evidence["raw_exit_code"], 0)
        self.assertFalse(escaped.exists())

    def test_auto_mode_selects_adopt_with_history(self) -> None:
        (self.root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.commit()
        result = initialize_project(self.root, install=False, ci=False, mode="auto")
        self.assertEqual(result["project"]["enforcement"]["mode"], "adopt")
        self.assertEqual(result["project"]["enforcement"]["scope"], "changed")

    def test_cli_accepts_documented_auto_and_browser_flags(self) -> None:
        args = build_parser().parse_args(
            ["setup", ".", "--mode", "auto", "--browsers", "--no-install"]
        )
        self.assertEqual(args.mode, "auto")
        self.assertTrue(args.browsers)

    def test_generated_web_ci_installs_browsers_explicitly(self) -> None:
        (self.root / "index.html").write_text(
            "<!doctype html><title>Example</title>\n", encoding="utf-8"
        )
        initialize_project(self.root, owner="@quality", install=False, ci=True, mode="greenfield")
        workflow = (self.root / ".github" / "workflows" / "quality-gauntlet.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("tools install --ci --browsers", workflow)
        self.assertEqual(workflow.count("continue-on-error: true"), 1)

    def test_rendered_policy_contains_every_registered_gate(self) -> None:
        policy = tomllib.loads(render_policy("@quality"))
        self.assertEqual(set(policy["gates"]), set(GATE_NAMES))
        self.assertIn("supply_chain", policy["profiles"]["deep"]["gates"])
        self.assertIn("supply_chain", policy["profiles"]["release"]["gates"])

    def test_complete_lock_derived_supply_chain_gate_passes(self) -> None:
        (self.root / "requirements.txt").write_text("idna==3.10\n", encoding="utf-8")
        initialize_project(self.root, install=False, ci=False, mode="greenfield")
        code, report = run_adapter(self.root, "supply_chain")
        self.assertEqual(code, PASS)
        self.assertTrue(report["inventory"]["complete"])

    def test_standalone_zipapp_initializes_a_vendored_runtime(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        output = self.root / "release"
        target = self.root / "target"
        target.mkdir()
        build = subprocess.run(
            [
                sys.executable,
                str(source_root / "scripts" / "build_release.py"),
                "--output",
                str(output),
            ],
            cwd=source_root,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(build.returncode, 0, build.stderr)
        command = subprocess.run(
            [sys.executable, str(output / "aqg.pyz"), "init", str(target), "--no-ci"],
            cwd=target,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(command.returncode, 0, command.stderr)
        self.assertTrue((target / "quality" / "_aqg" / "cli.py").exists())
        self.assertTrue((target / "quality" / "qg.py").exists())


if __name__ == "__main__":
    unittest.main()
