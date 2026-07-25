from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path

from aqg.adapters import _python_crap, _python_structure_evidence, run_adapter
from aqg.approvals import template, validate_approval
from aqg.cli import build_parser
from aqg.constants import CONFIGURATION_ERROR, PASS
from aqg.dashboard import DashboardServer, project_status
from aqg.detect import detect_project
from aqg.policy import GATE_NAMES, load_policy, render_policy, validate_policy
from aqg.project import load_project, validate_project
from aqg.review import analyze_review
from aqg.runner import run_gate
from aqg.sbom import (
    generate_sboms,
    javascript_inventory,
    python_inventory,
    validate_cyclonedx_document,
)
from aqg.scaffold import build_project_config, initialize_project
from aqg.util import change_fingerprint, detect_base_ref, git_changed_files, read_json, write_json


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def build_release(source_root: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
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

    def test_runner_and_package_manager_command_matrix(self) -> None:
        matrix = {
            ("npm", "vitest"): ("$AQG_JS_BIN/vitest", "$AQG_JS_BIN/vitest"),
            ("pnpm", "jest"): ("pnpm", "pnpm"),
            ("yarn", "mocha"): ("yarn", "$AQG_JS_BIN/c8"),
            ("bun", "ava"): ("bun", "$AQG_JS_BIN/c8"),
            ("npm", "node"): ("node", "$AQG_JS_BIN/c8"),
        }
        for (manager, runner), (unit_prefix, coverage_prefix) in matrix.items():
            with self.subTest(manager=manager, runner=runner):
                case = self.root / f"{manager}-{runner}"
                (case / "src").mkdir(parents=True)
                (case / "tests").mkdir()
                (case / "src" / "answer.js").write_text(
                    "export const answer = 42;\n", encoding="utf-8"
                )
                (case / "tests" / "answer.test.js").write_text(
                    "export const covered = true;\n", encoding="utf-8"
                )
                dependency = "node:test" if runner == "node" else runner
                package = {
                    "name": case.name,
                    "packageManager": f"{manager}@1.0.0",
                    "devDependencies": {dependency: "1.0.0"},
                }
                if runner == "node":
                    package["scripts"] = {"check": "node --test"}
                (case / "package.json").write_text(json.dumps(package), encoding="utf-8")
                detection = detect_project(case)
                project = build_project_config(case, detection)
                self.assertEqual(detection.package_manager, manager)
                self.assertEqual(detection.js_test_runner, runner)
                self.assertEqual(project["javascript"]["unit_command"][0], unit_prefix)
                self.assertEqual(project["javascript"]["coverage_command"][0], coverage_prefix)
                self.assertTrue(project["javascript"]["collect_command"])
                for command_name in ("unit_command", "collect_command", "coverage_command"):
                    command = project["javascript"][command_name]
                    self.assertIsInstance(command, list)
                    self.assertNotIn("sh", command)
                    self.assertNotIn("bash", command)

    def test_package_manager_lockfile_precedence(self) -> None:
        for lockfile, expected in (
            ("pnpm-lock.yaml", "pnpm"),
            ("yarn.lock", "yarn"),
            ("bun.lock", "bun"),
            ("bun.lockb", "bun"),
            ("package-lock.json", "npm"),
            ("npm-shrinkwrap.json", "npm"),
        ):
            with self.subTest(lockfile=lockfile):
                case = self.root / lockfile.replace(".", "-")
                case.mkdir()
                (case / "package.json").write_text('{"name":"matrix"}\n', encoding="utf-8")
                (case / lockfile).write_text("{}\n", encoding="utf-8")
                self.assertEqual(detect_project(case).package_manager, expected)

    def test_tox_configuration_generates_protected_commands(self) -> None:
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src" / "answer.py").write_text(
            "def answer() -> int:\n    return 42\n", encoding="utf-8"
        )
        (self.root / "tests" / "test_answer.py").write_text(
            "def test_answer() -> None:\n    assert True\n", encoding="utf-8"
        )
        (self.root / "tox.ini").write_text(
            "[tox]\nenv_list = py\n\n[testenv]\ncommands = pytest {posargs}\n",
            encoding="utf-8",
        )
        detection = detect_project(self.root)
        project = build_project_config(self.root, detection)
        self.assertEqual(detection.python_test_runner, "tox")
        self.assertEqual(project["python"]["test_runner"], "tox")
        self.assertEqual(project["python"]["unit_command"], ["$AQG_PY_BIN/tox", "run"])
        self.assertEqual(
            project["python"]["collect_command"],
            ["$AQG_PY_BIN/tox", "run", "--", "--collect-only", "-q"],
        )


class ConfigurationValidationTests(RepoCase):
    def _valid_project(self) -> dict[str, object]:
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src" / "answer.py").write_text(
            "def answer() -> int:\n    return 42\n", encoding="utf-8"
        )
        (self.root / "tests" / "test_answer.py").write_text(
            "def test_answer() -> None:\n    assert True\n", encoding="utf-8"
        )
        return build_project_config(self.root, detect_project(self.root))

    @staticmethod
    def _replace(payload: dict[str, object], path: str, value: object) -> dict[str, object]:
        changed = copy.deepcopy(payload)
        target: dict[str, object] = changed
        parts = path.split(".")
        for part in parts[:-1]:
            target = target[part]  # type: ignore[assignment]
        target[parts[-1]] = value
        return changed

    def test_project_validator_reports_each_contract_with_exact_message(self) -> None:
        project = self._valid_project()
        self.assertEqual(validate_project(project), [])
        cases = (
            ("schema_version", 1, "schema_version must be 2"),
            ("name", " ", "name must be a non-empty string"),
            ("stacks.python", "yes", "stacks.python must be boolean"),
            ("paths.tests", [""], "paths.tests must be an array of non-empty strings"),
            ("enforcement.mode", "loose", "enforcement.mode must be adopt or greenfield"),
            ("enforcement.scope", "some", "enforcement.scope must be changed or full"),
            ("enforcement.base_ref", "", "enforcement.base_ref must be a non-empty Git ref"),
            ("gates.unit.applicable", "yes", "gates.unit.applicable must be boolean"),
            (
                "thresholds.coverage.lines",
                True,
                "thresholds.coverage.lines must be a number from 0 to 100",
            ),
            (
                "thresholds.structure.max_function_lines",
                0,
                "thresholds.structure.max_function_lines must be a positive number",
            ),
            (
                "thresholds.mutation.minimum_score",
                101,
                "thresholds.mutation.minimum_score must be a number from 0 to 100",
            ),
            (
                "thresholds.mutation.maximum_survivors",
                -1,
                "thresholds.mutation.maximum_survivors must be a non-negative integer",
            ),
            (
                "profile_thresholds",
                {"unknown": {}},
                "profile_thresholds has unknown execution profile 'unknown'",
            ),
            (
                "web.start_command",
                [],
                "web.start_command must be null or a non-empty string array",
            ),
            ("web.base_url", "file:///tmp", "web.base_url must be null or an http(s) URL"),
        )
        for path, value, expected in cases:
            with self.subTest(path=path):
                errors = validate_project(self._replace(project, path, value))
                self.assertIn(expected, errors)

    def test_project_validator_reports_cross_field_and_missing_objects(self) -> None:
        project = self._valid_project()
        stacks = copy.deepcopy(project["stacks"])
        stacks.update({"javascript": False, "typescript": True})
        self.assertEqual(
            validate_project(self._replace(project, "stacks", stacks)),
            ["stacks.typescript=true requires stacks.javascript=true"],
        )
        gate = copy.deepcopy(project)
        gate["gates"]["unit"] = {"applicable": False, "reason": ""}  # type: ignore[index]
        self.assertIn(
            "gates.unit.reason is required when the gate is not applicable",
            validate_project(gate),
        )
        for key, expected in (
            ("stacks", "stacks must be an object"),
            ("paths", "paths must be an object"),
            ("enforcement", "enforcement must be an object"),
            ("gates", "gates must be a non-empty object"),
            ("thresholds", "thresholds must be an object"),
            ("profile_thresholds", "profile_thresholds must be an object"),
            ("web", "web must be an object"),
        ):
            with self.subTest(key=key):
                self.assertIn(expected, validate_project(self._replace(project, key, None)))

    def test_policy_validator_reports_gate_policy_and_risk_contracts(self) -> None:
        policy = tomllib.loads(render_policy("@quality"))
        self.assertEqual(validate_policy(policy), [])
        mutations = (
            ("initialized", False, "policy initialized=false; run qg init or qg bootstrap"),
            ("profiles", {}, "no execution profiles are configured"),
            ("gates", {}, "no gates are configured"),
            (
                "gates.unit.command",
                " ",
                "gate 'unit' has an unconfigured command",
            ),
            (
                "gates.unit.timeout_seconds",
                0,
                "gate 'unit' needs a positive timeout_seconds",
            ),
            (
                "gates.unit.clean_paths",
                "bad",
                "gate 'unit' clean_paths must be a string array",
            ),
            (
                "policy.protected_paths",
                "bad",
                "policy.protected_paths must be a string array",
            ),
            (
                "policy.blocked_command_regex",
                ["["],
                "invalid blocked command regex '[': unterminated character set at position 0",
            ),
            (
                "risk_profiles.standard.required_execution_profiles",
                [],
                "risk profile 'standard' has no required execution profiles",
            ),
        )
        for path, value, expected in mutations:
            with self.subTest(path=path):
                errors = validate_policy(self._replace(policy, path, value))
                self.assertIn(expected, errors)

    def test_policy_validator_detects_missing_references(self) -> None:
        policy = tomllib.loads(render_policy("@quality"))
        policy["profiles"]["fast"]["gates"].append("missing")
        self.assertIn(
            "profile 'fast' references missing gate 'missing'",
            validate_policy(policy),
        )
        policy = tomllib.loads(render_policy("@quality"))
        policy["risk_profiles"]["experiment"]["required_execution_profiles"] = ["missing"]
        self.assertIn(
            "risk profile 'experiment' references a missing execution profile",
            validate_policy(policy),
        )
        policy["risk_profiles"].pop("critical")
        self.assertIn("missing risk profile 'critical'", validate_policy(policy))


class StructureRatchetTests(RepoCase):
    def test_only_changed_functions_are_enforced_in_adopt_mode(self) -> None:
        source = self.root / "src" / "module.py"
        source.parent.mkdir()
        source.write_text(
            "def inherited_debt():\n"
            + "".join(f"    value_{index} = {index}\n" for index in range(55))
            + "    return value_54\n\n"
            + "def changed_function():\n    return 1\n",
            encoding="utf-8",
        )
        self.commit()
        source.write_text(
            source.read_text(encoding="utf-8").replace(
                "def changed_function():\n    return 1\n",
                "def changed_function():\n    if True:\n        return 2\n",
            ),
            encoding="utf-8",
        )
        project = {
            "enforcement": {"scope": "changed", "base_ref": "HEAD"},
            "thresholds": {
                "structure": {
                    "max_function_lines": 50,
                    "max_cyclomatic_complexity": 10,
                    "max_nesting_depth": 4,
                }
            },
            "profile_thresholds": {},
        }
        payload = {
            "src/module.py": [
                {
                    "type": "function",
                    "name": "inherited_debt",
                    "lineno": 1,
                    "endline": 57,
                    "complexity": 20,
                },
                {
                    "type": "function",
                    "name": "changed_function",
                    "lineno": 59,
                    "endline": 61,
                    "complexity": 2,
                },
            ]
        }
        evidence = _python_structure_evidence(self.root, project, ["src/module.py"], payload)
        by_name = {item["name"]: item for item in evidence["functions"]}
        self.assertFalse(by_name["inherited_debt"]["enforced"])
        self.assertTrue(by_name["changed_function"]["enforced"])
        self.assertEqual(evidence["failures"], [])

    def test_changed_function_over_limit_fails_with_metric(self) -> None:
        source = self.root / "module.py"
        source.write_text("def risky():\n    return 1\n", encoding="utf-8")
        self.commit()
        source.write_text("def risky():\n    if True:\n        return 2\n", encoding="utf-8")
        project = {
            "enforcement": {"scope": "changed", "base_ref": "HEAD"},
            "thresholds": {
                "structure": {
                    "max_function_lines": 2,
                    "max_cyclomatic_complexity": 1,
                    "max_nesting_depth": 0,
                }
            },
            "profile_thresholds": {},
        }
        payload = {
            "module.py": [
                {
                    "type": "function",
                    "name": "risky",
                    "lineno": 1,
                    "endline": 3,
                    "complexity": 2,
                }
            ]
        }
        evidence = _python_structure_evidence(self.root, project, ["module.py"], payload)
        self.assertEqual(len(evidence["failures"]), 3)
        self.assertTrue(any("complexity 2 > 1" in item for item in evidence["failures"]))
        self.assertTrue(any("lines 3 > 2" in item for item in evidence["failures"]))
        self.assertTrue(any("nesting 1 > 0" in item for item in evidence["failures"]))


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
        smoke = self.root / "tests" / "aqg-browser" / "aqg-smoke.spec.mjs"
        self.assertTrue(smoke.exists())
        smoke_source = smoke.read_text(encoding="utf-8")
        self.assertIn("createRequire", smoke_source)
        self.assertIn("quality/tools/js/package.json", smoke_source)


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
        self.assertRegex(
            document["serialNumber"],
            r"^urn:uuid:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$",
        )

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

    def test_sbom_serial_number_changes_with_inventory_content(self) -> None:
        requirement = self.root / "requirements.txt"
        requirement.write_text("idna==3.10\n", encoding="utf-8")
        project = {"stacks": {"javascript": False, "python": True}}
        first = generate_sboms(self.root, project, include_toolchains=False)
        first_serial = read_json(self.root / first["artifacts"][0]["artifact"])["serialNumber"]

        requirement.write_text("idna==3.11\n", encoding="utf-8")
        second = generate_sboms(self.root, project, include_toolchains=False)
        second_serial = read_json(self.root / second["artifacts"][0]["artifact"])["serialNumber"]
        self.assertNotEqual(first_serial, second_serial)

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
        references = re.findall(
            r"uses:\s+[\w.-]+/[\w.-]+(?:/[\w.-]+)?@([^\s#]+)",
            workflow,
        )
        self.assertTrue(references)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in references))

    def test_checked_in_workflows_pin_actions_by_commit(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        paths = [
            *sorted((source_root / ".github" / "workflows").glob("*.yml")),
            source_root / "ci" / "github-actions-quality.yml.example",
        ]
        for path in paths:
            relative = path.relative_to(source_root).as_posix()
            workflow = path.read_text(encoding="utf-8")
            references = re.findall(
                r"uses:\s+[\w.-]+/[\w.-]+(?:/[\w.-]+)?@([^\s#]+)",
                workflow,
            )
            self.assertTrue(references, relative)
            self.assertTrue(
                all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in references),
                relative,
            )

    def test_js_toolchain_overrides_vulnerable_qs_transitive(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        installed_manifest = json.loads(
            (source_root / "quality" / "tools" / "js" / "package.json").read_text(encoding="utf-8")
        )
        template_manifest = json.loads(
            (source_root / "src" / "aqg" / "templates" / "js" / "package.json").read_text(
                encoding="utf-8"
            )
        )
        lock = json.loads(
            (source_root / "quality" / "tools" / "js" / "package-lock.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(installed_manifest["overrides"]["qs"], "6.15.3")
        self.assertEqual(template_manifest["overrides"]["qs"], "6.15.3")
        self.assertEqual(lock["packages"]["node_modules/qs"]["version"], "6.15.3")
        self.assertNotIn("node_modules/typed-rest-client/node_modules/qs", lock["packages"])

    def test_c8_coverage_runner_uses_audited_major(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        manifest = json.loads(
            (source_root / "quality" / "tools" / "js" / "package.json").read_text(encoding="utf-8")
        )
        lock = json.loads(
            (source_root / "quality" / "tools" / "js" / "package-lock.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["devDependencies"]["c8"], "12.0.0")
        self.assertEqual(lock["packages"]["node_modules/c8"]["version"], "12.0.0")

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
        build = build_release(source_root, output)
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

    def test_release_contains_complete_inventory_and_provenance(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        output = self.root / "release"
        build = build_release(source_root, output)
        self.assertEqual(build.returncode, 0, build.stderr)

        artifact_names = {
            "aqg.pyz",
            "agent-quality-gauntlet-2.0.0-portable.zip",
            "aqg-runtime.cdx.json",
            "aqg-javascript-toolchain.cdx.json",
            "aqg-python-toolchain.cdx.json",
            "provenance.intoto.json",
        }
        checksums = (output / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
        self.assertEqual({line.split("  ", 1)[1] for line in checksums}, artifact_names)
        for line in checksums:
            expected, name = line.split("  ", 1)
            self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), expected)

        for name in artifact_names:
            if name.endswith(".cdx.json"):
                self.assertEqual(validate_cyclonedx_document(read_json(output / name)), [])
        provenance = read_json(output / "provenance.intoto.json")
        self.assertEqual(provenance["_type"], "https://in-toto.io/Statement/v1")
        self.assertEqual(provenance["predicateType"], "https://slsa.dev/provenance/v1")
        self.assertEqual(
            {item["name"] for item in provenance["subject"]},
            artifact_names - {"provenance.intoto.json"},
        )
        definition = provenance["predicate"]["buildDefinition"]
        material_names = {item.get("name") for item in definition["resolvedDependencies"]}
        self.assertIn("scripts/build_release.py", material_names)
        self.assertIn("src/aqg/py.typed", material_names)
        self.assertIsInstance(definition["internalParameters"]["sourceDirty"], bool)

        with zipfile.ZipFile(output / "agent-quality-gauntlet-2.0.0-portable.zip") as archive:
            self.assertIn("LICENSE", archive.namelist())
            self.assertIn("aqg-runtime.cdx.json", archive.namelist())
        with zipfile.ZipFile(output / "aqg.pyz") as archive:
            self.assertIn("aqg/py.typed", archive.namelist())


if __name__ == "__main__":
    unittest.main()
