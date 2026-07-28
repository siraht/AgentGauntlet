# Feature-Spec: AgentQualityGauntlet AQG-CORE-001 AQG-CORE-002 AQG-CORE-007 AQG-CORE-008 AQG-CORE-009 AQG-CORE-010 AQG-CORE-011 AQG-CORE-012 AQG-CORE-013 AQG-CORE-014 AQG-CORE-015 AQG-CORE-016 AQG-CORE-017 AQG-CORE-018 AQG-CORE-025
# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-006 AQG-RETRO-009 AQG-RETRO-013
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from aqg.adapters import (
    DEFAULT_PYTHON_MUTATION_MAX_CHANGED_LINES,
    PYTHON_MUTATION_GATE_TIMEOUT_SECONDS,
    PYTHON_MUTATION_OVERHEAD_SECONDS,
    PYTHON_MUTATION_RESULTS_TIMEOUT_SECONDS,
    PYTHON_MUTATION_RUN_TIMEOUT_SECONDS,
    PYTHON_MUTATION_SAFETY_MARGIN_SECONDS,
    _append_mutmut_config,
    _changed_lines,
    _changed_production_files,
    _classify_mutmut_results,
    _count_changed_python_production_lines,
    _is_test_path,
    _javascript_unit_spec,
    _js_mutation_scope,
    _mutation_python,
    _mutmut_allows_decorators,
    _mutmut_function_candidates,
    _mutmut_module_name,
    _mutmut_results_command,
    _nontrivial_changed_lines,
    _parse_mutmut_results,
    _python_crap,
    _python_mutation_function_selection,
    _python_mutation_platform_supported,
    _python_structure_evidence,
    _python_test_env,
    run_adapter,
)
from aqg.approvals import template, validate_approval, validate_required_approvals
from aqg.checks import test_feature_traceability as feature_traceability
from aqg.cli import build_parser
from aqg.constants import CONFIGURATION_ERROR, INFRASTRUCTURE_ERROR, PASS, QUALITY_FAILURE
from aqg.dashboard import DashboardServer, project_status
from aqg.detect import detect_project
from aqg.doctor import diagnose
from aqg.errors import ConfigurationError
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
from aqg.scaffold import (
    _direct_requirement_markers,
    _restore_direct_requirement_markers,
    build_project_config,
    initialize_project,
    upgrade_runtime,
)
from aqg.schema_contracts import validate_named_schema
from aqg.util import (
    CommandResult,
    change_fingerprint,
    detect_base_ref,
    git_changed_files,
    git_diff,
    read_json,
    write_json,
)

_RELEASE_SPEC = importlib.util.spec_from_file_location(
    "scripts.build_release",
    Path(__file__).resolve().parents[1] / "scripts" / "build_release.py",
)
assert _RELEASE_SPEC and _RELEASE_SPEC.loader
_RELEASE_MODULE = importlib.util.module_from_spec(_RELEASE_SPEC)
_RELEASE_SPEC.loader.exec_module(_RELEASE_MODULE)


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
            target = cast(dict[str, object], target[part])
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
                "thresholds.mutation.minimum_selection_coverage",
                101,
                ("thresholds.mutation.minimum_selection_coverage must be a number from 0 to 100"),
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
        gates = cast(dict[str, object], gate["gates"])
        gates["unit"] = {"applicable": False, "reason": ""}
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
        self.assertTrue((self.root / "aqg").is_file())
        self.assertTrue((self.root / "quality" / "qg.py").is_file())
        self.assertTrue((self.root / "quality" / "_aqg" / "cli.py").is_file())
        self.assertTrue((self.root / "quality" / "schemas" / "run-summary.schema.json").is_file())
        self.assertEqual(
            validate_named_schema(
                self.root,
                "change-risk",
                read_json(self.root / "quality" / "change-risk.json"),
            ),
            [],
        )
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
        self.assertIn("__pycache__/", (self.root / ".gitignore").read_text(encoding="utf-8"))

    @pytest.mark.mutation_incompatible
    def test_project_launchers_execute_copied_runtime_without_dirtying_repository(self) -> None:
        """Exercise the copied runtime outside mutmut's in-process instrumentation."""
        (self.root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        initialize_project(self.root, owner="@quality-owner", install=False, ci=False, mode="adopt")
        convenience = subprocess.run(
            [str(self.root / "aqg"), "--version"],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(convenience.returncode, 0, convenience.stderr)
        self.assertIn("2.0.0", convenience.stdout)
        self.commit("install AQG")
        repeated = subprocess.run(
            [str(self.root / "aqg"), "doctor", "--json"],
            cwd=self.root,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(git(self.root, "status", "--porcelain"), "")

    def test_static_web_setup_generates_isolated_web_pack(self) -> None:
        (self.root / "index.html").write_text(
            "<!doctype html><html lang='en'><title>Example</title></html>\n", encoding="utf-8"
        )
        (self.root / "styles.css").write_text(
            "body { font-family: sans-serif; }\n", encoding="utf-8"
        )
        setup = initialize_project(self.root, install=False, ci=False)
        project = load_project(self.root)
        self.assertTrue(project["stacks"]["html"])
        self.assertTrue(project["stacks"]["css"])
        self.assertFalse(project["stacks"]["javascript"])
        self.assertFalse(project["stacks"]["python"])
        self.assertFalse(setup["onboarding"]["state"]["detected_stacks"]["python"])
        self.assertTrue(project["gates"]["acceptance"]["applicable"])
        self.assertTrue(
            (self.root / "quality" / "tools" / "js" / "config" / "htmlvalidate.json").exists()
        )
        smoke = self.root / "tests" / "aqg-browser" / "aqg-smoke.spec.mjs"
        self.assertTrue(smoke.exists())
        smoke_source = smoke.read_text(encoding="utf-8")
        self.assertIn("createRequire", smoke_source)
        self.assertIn("quality/tools/js/package.json", smoke_source)
        post_setup = detect_project(self.root)
        self.assertFalse(post_setup.javascript)
        self.assertFalse(post_setup.python)
        self.assertNotIn(
            "project-model-stack-drift",
            {gap["code"] for gap in setup["onboarding"]["gaps"]},
        )
        doctor = diagnose(self.root)
        self.assertFalse(doctor["detected"]["python"])
        self.assertNotIn("stack-drift", {item["code"] for item in doctor["diagnostics"]})

    def test_doctor_fails_closed_and_upgrade_restores_missing_project_command(self) -> None:
        initialize_project(self.root, install=False, ci=False)
        (self.root / "aqg").unlink()
        missing = diagnose(self.root)
        self.assertIn(
            "project-command-missing",
            {item["code"] for item in missing["diagnostics"]},
        )

        upgrade_runtime(self.root)
        restored = diagnose(self.root)
        self.assertNotIn(
            "project-command-missing",
            {item["code"] for item in restored["diagnostics"]},
        )
        self.assertTrue((self.root / "aqg").is_file())

    def test_javascript_only_setup_does_not_invent_python_stack_drift(self) -> None:
        (self.root / "src").mkdir()
        (self.root / "test").mkdir()
        (self.root / "package.json").write_text(
            json.dumps(
                {
                    "name": "javascript-only",
                    "scripts": {"test": "node --test"},
                    "devDependencies": {},
                }
            ),
            encoding="utf-8",
        )
        (self.root / "src" / "app.js").write_text("export const value = 1;\n", encoding="utf-8")
        (self.root / "test" / "app.test.js").write_text(
            "import assert from 'node:assert/strict';\n"
            "import test from 'node:test';\n"
            "test('value', () => assert.equal(1, 1));\n",
            encoding="utf-8",
        )

        setup = initialize_project(
            self.root,
            owner="@quality-owner",
            install=False,
            ci=True,
            mode="greenfield",
        )
        detected = detect_project(self.root)
        doctor = diagnose(self.root)

        self.assertTrue(detected.javascript)
        self.assertFalse(detected.python)
        self.assertFalse(setup["project"]["stacks"]["python"])
        self.assertNotIn(
            "project-model-stack-drift",
            {gap["code"] for gap in setup["onboarding"]["gaps"]},
        )
        self.assertNotIn("stack-drift", {item["code"] for item in doctor["diagnostics"]})


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

    def test_missing_comparison_base_fails_closed(self) -> None:
        (self.root / "a.txt").write_text("a\n", encoding="utf-8")
        self.commit()

        with self.assertRaisesRegex(ConfigurationError, "comparison base"):
            git_changed_files(self.root, "origin/missing")
        with self.assertRaisesRegex(ConfigurationError, "comparison base"):
            git_diff(self.root, "origin/missing")


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

    def test_traceability_rejects_legacy_name_only_mapping(self) -> None:
        self._initialized()

        report = feature_traceability(self.root, load_project(self.root))

        self.assertEqual(report["active_specs"], 1)
        self.assertEqual(report["requirements"], 0)
        self.assertEqual(report["mapped_requirements"], 0)
        self.assertEqual(
            [finding["code"] for finding in report["findings"]],
            ["requirement-id-missing"],
        )

    def test_traceability_requires_exact_declared_requirement_ids(self) -> None:
        self._initialized()
        spec = self.root / "feature-spec" / "Product.Calculation.md"
        test = self.root / "tests" / "test_app.py"
        spec.write_text(
            "# Product.Calculation\n\n## Requirements\n\n"
            "- `PRODUCT-CALC-001` The product MUST calculate a result.\n",
            encoding="utf-8",
        )
        test.write_text(
            "# PRODUCT-CALC-001 appears incidentally\n"
            "# Feature-Spec: Product.Calculation PRODUCT-CALC-999\n"
            "def test_calculate():\n    assert 2 == 2\n",
            encoding="utf-8",
        )
        report = feature_traceability(self.root, load_project(self.root))
        self.assertEqual(report["mapped_requirements"], 0)
        self.assertEqual(
            {finding["code"] for finding in report["findings"]},
            {"unmapped-active-requirement", "unknown-requirement-reference"},
        )
        test.write_text(
            "# Feature-Spec: Product.Calculation PRODUCT-CALC-001\n"
            "def test_calculate():\n    assert 2 == 2\n",
            encoding="utf-8",
        )
        report = feature_traceability(self.root, load_project(self.root))
        self.assertEqual(report["mapped_requirements"], 1)
        self.assertEqual(report["findings"], [])

    def test_review_ignores_debt_words_inside_python_strings(self) -> None:
        self._initialized()
        (self.root / "src" / "app.py").write_text(
            'MESSAGE = "Create a TODO feature specification."\n'
            "def calculate(value: int) -> int:\n"
            "    return value + 1\n",
            encoding="utf-8",
        )

        packet = analyze_review(
            self.root, load_policy(self.root), base="HEAD", require_evidence=False
        )
        codes = {finding["code"] for finding in packet["findings"]}

        self.assertNotIn("new-production-debt-marker", codes)

    def test_review_reports_debt_markers_in_python_comments(self) -> None:
        self._initialized()
        (self.root / "src" / "app.py").write_text(
            "def calculate(value: int) -> int:\n"
            "    return value + 1  # TODO: replace the temporary rule\n",
            encoding="utf-8",
        )

        packet = analyze_review(
            self.root, load_policy(self.root), base="HEAD", require_evidence=False
        )
        codes = {finding["code"] for finding in packet["findings"]}

        self.assertIn("new-production-debt-marker", codes)

    def test_review_distinguishes_loopback_and_external_network_calls(self) -> None:
        self._initialized()
        test_path = self.root / "tests" / "test_network.py"
        test_path.write_text(
            "import urllib.request\n\n"
            "def test_loopback(port):\n"
            '    base = f"http://127.0.0.1:{port}"\n'
            '    request = urllib.request.Request(base + "/health")\n'
            '    urllib.request.urlopen(base + "/status")\n'
            "    urllib.request.urlopen(request)\n",
            encoding="utf-8",
        )
        loopback_packet = analyze_review(
            self.root, load_policy(self.root), base="HEAD", require_evidence=False
        )
        self.assertNotIn(
            "test-nondeterminism-introduced",
            {finding["code"] for finding in loopback_packet["findings"]},
        )

        test_path.write_text(
            test_path.read_text(encoding="utf-8")
            + '\ndef test_external():\n    urllib.request.urlopen("https://example.com/status")\n',
            encoding="utf-8",
        )
        external_packet = analyze_review(
            self.root, load_policy(self.root), base="HEAD", require_evidence=False
        )
        self.assertIn(
            "test-nondeterminism-introduced",
            {finding["code"] for finding in external_packet["findings"]},
        )

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

    def test_high_assurance_requires_independent_verification_evidence(self) -> None:
        self._initialized()
        required = validate_required_approvals(self.root, "high_assurance")
        self.assertEqual(
            required["required"],
            [
                "behavior-review",
                "manual-qa",
                "rollback-rehearsal",
                "independent-verification",
            ],
        )
        payload = template(
            self.root,
            "independent-verification",
            reviewer="verifier@example.test",
        )
        payload.update(
            {
                "result": "pass",
                "scope": ["Current candidate and required deep evidence"],
                "procedure": ["Executed verifier from a read-only isolated checkout"],
                "evidence": ["immutable run manifest"],
            }
        )
        write_json(
            self.root / "quality" / "approvals" / "independent-verification.json",
            payload,
        )
        errors = validate_approval(self.root, "independent-verification")
        self.assertTrue(any("independence." in error for error in errors))
        payload["independence"] = {
            "reviewer_did_not_author_change": True,
            "reviewer_did_not_modify_evidence": True,
        }
        write_json(
            self.root / "quality" / "approvals" / "independent-verification.json",
            payload,
        )
        self.assertEqual(validate_approval(self.root, "independent-verification"), [])

    def test_assurance_gate_blocks_missing_risk_selected_approval_evidence(self) -> None:
        self._initialized()
        code, report = run_adapter(self.root, "assurance")
        self.assertEqual(code, QUALITY_FAILURE)
        self.assertEqual(report["approvals"]["required"], ["behavior-review"])
        self.assertTrue(
            any("missing" in failure for failure in report["failures"]),
            report["failures"],
        )


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

    def test_changed_coverage_scope_ignores_untracked_aqg_scaffolding(self) -> None:
        (self.root / "src").mkdir()
        (self.root / "quality" / "_aqg").mkdir(parents=True)
        (self.root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.root / "quality" / "qg.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
        (self.root / "quality" / "_aqg" / "runtime.py").write_text(
            "VERSION = 1\n", encoding="utf-8"
        )
        project = {
            "enforcement": {"base_ref": "HEAD"},
            "paths": {
                "source": ["src"],
                "tests": ["tests"],
                "exclude": ["quality/qg.py", "quality/_aqg/**"],
            },
        }

        diff = git_diff(self.root, "HEAD")
        self.assertIn("quality/qg.py", diff)
        self.assertIn("quality/_aqg/runtime.py", diff)
        self.assertEqual(
            _changed_production_files(self.root, project, {".py"}),
            ["src/app.py"],
        )
        self.assertEqual(set(_changed_lines(self.root, project)), {"src/app.py"})

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
        self.assertIn('github.event_name }}" == "workflow_dispatch"', workflow)
        self.assertIn("github.event.repository.default_branch", workflow)
        self.assertIn('AQG_BASE="origin/$AQG_TARGET"', workflow)
        self.assertNotIn('AQG_BASE="HEAD~1"', workflow)
        self.assertIn(
            "ref: ${{ github.event.pull_request.head.sha || github.sha }}",
            workflow,
        )
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

    def test_python_tool_lock_covers_libcst_on_python_313(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        expected = 'pyyaml-ft==8.0.0; python_version >= "3.13"'
        for path in (
            source_root / "quality" / "tools" / "python" / "requirements.in",
            source_root / "src" / "aqg" / "templates" / "python" / "requirements.in",
        ):
            requirements = path.read_text(encoding="utf-8")
            self.assertIn(expected, requirements)
            self.assertIn("uv==0.11.32", requirements)
        lock = (source_root / "quality" / "tools" / "python" / "requirements.lock.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn('pyyaml-ft==8.0.0 ; python_version >= "3.13"', lock)
        self.assertIn("uv==0.11.32", lock)
        self.assertIn("sha256:052561b89d5b2a8e1289f326d060e794", lock)

    def test_source_mutation_routes_configuration_to_conformance(self) -> None:
        candidates, configuration = _js_mutation_scope(
            [
                "src/app.js",
                "src/vite.config.js",
                "src/aqg/templates/js/eslint.config.mjs",
                "quality/tools/js/config/eslint.config.mjs",
            ]
        )
        self.assertEqual(candidates, ["src/app.js"])
        self.assertEqual(
            configuration,
            [
                "src/vite.config.js",
                "src/aqg/templates/js/eslint.config.mjs",
                "quality/tools/js/config/eslint.config.mjs",
            ],
        )

    def test_project_test_commands_clear_the_outer_comparison_base(self) -> None:
        python_environment = _python_test_env(self.root, timezone=True)
        _, _, javascript_environment = _javascript_unit_spec(
            self.root,
            {"javascript": {"unit_command": ["node", "--test"]}},
        )

        self.assertEqual(python_environment["AQG_DIFF_BASE"], "")
        self.assertEqual(javascript_environment["AQG_DIFF_BASE"], "")
        for variable in ("AQG_RUN_ID", "AQG_GATE", "AQG_PROFILE", "AQG_ROOT"):
            self.assertEqual(python_environment[variable], "")
            self.assertEqual(javascript_environment[variable], "")

    def test_configured_nested_test_root_overrides_filename_heuristics(self) -> None:
        project = {
            "paths": {"tests": ["tests", "agent_ergonomics_audit/audit/regression_tests"]},
            "python": {"test_paths": ["tests"]},
        }
        self.assertTrue(
            _is_test_path(
                "agent_ergonomics_audit/audit/regression_tests/conftest.py",
                project,
            )
        )
        self.assertFalse(_is_test_path("src/conftest.py", project))

    def test_mutmut_copies_nonstandard_test_roots_into_its_sandbox(self) -> None:
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        nested = self.root / "audit" / "regression_tests"
        nested.mkdir(parents=True)
        (self.root / "fixtures").mkdir()
        (self.root / "aqg").write_text("#!/bin/sh\n", encoding="utf-8")
        _append_mutmut_config(
            self.root,
            {
                "python": {
                    "source_paths": ["src"],
                    "test_paths": ["tests", "audit/regression_tests"],
                    "mutation_copy_paths": ["fixtures"],
                }
            },
            ["src/example.py"],
        )
        content = (self.root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(
            'pytest_add_cli_args_test_selection = ["-m", "not mutation_incompatible", '
            '"tests", "audit/regression_tests"]',
            content,
        )
        self.assertIn('also_copy = ["audit/regression_tests", "fixtures", "aqg"]', content)
        self.assertIn("timeout_multiplier = 5.0", content)
        self.assertIn("timeout_constant = 1.0", content)

    def test_mutmut_sandbox_replaces_unbounded_timeout_configuration(self) -> None:
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "pyproject.toml").write_text(
            "[tool.mutmut]\n"
            "timeout_multiplier = 15.0\n"
            "timeout_constant = 30.0\n"
            'only_mutate = ["src/old.py"]\n',
            encoding="utf-8",
        )

        _append_mutmut_config(
            self.root,
            {
                "python": {
                    "source_paths": ["src"],
                    "test_paths": ["tests"],
                    "mutation_timeout_multiplier": 4.0,
                    "mutation_timeout_constant": 0.5,
                }
            },
            ["src/example.py"],
        )

        content = (self.root / "pyproject.toml").read_text(encoding="utf-8")
        self.assertEqual(content.count("timeout_multiplier ="), 1)
        self.assertEqual(content.count("timeout_constant ="), 1)
        self.assertIn("timeout_multiplier = 4.0", content)
        self.assertIn("timeout_constant = 0.5", content)
        self.assertIn('only_mutate = ["src/example.py"]', content)

    def test_mutation_timeout_configuration_has_anti_gaming_bounds(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        project = json.loads((source_root / "quality" / "project.json").read_text())
        project["python"]["mutation_timeout_multiplier"] = 2.0
        project["python"]["mutation_timeout_constant"] = 10.0

        errors = validate_project(project)

        self.assertIn(
            "python.mutation_timeout_multiplier must be a number from 3 to 10",
            errors,
        )
        self.assertIn(
            "python.mutation_timeout_constant must be a number from 0.5 to 5",
            errors,
        )

    def test_mutation_max_changed_lines_has_anti_gaming_bounds(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        project = json.loads((source_root / "quality" / "project.json").read_text())
        self.assertEqual(
            project["python"]["mutation_max_changed_lines"],
            DEFAULT_PYTHON_MUTATION_MAX_CHANGED_LINES,
        )
        self.assertEqual(validate_project(project), [])

        for invalid in (0, 1001, 12.5, True, "250"):
            with self.subTest(invalid=invalid):
                broken = copy.deepcopy(project)
                broken["python"]["mutation_max_changed_lines"] = invalid
                errors = validate_project(broken)
                self.assertIn(
                    "python.mutation_max_changed_lines must be an integer from 1 to 1000",
                    errors,
                )

    def test_scaffold_includes_protected_mutation_scope_default(self) -> None:
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.root / "tests" / "test_app.py").write_text(
            "def test_app() -> None:\n    assert True\n", encoding="utf-8"
        )
        project = build_project_config(self.root, detect_project(self.root))
        self.assertEqual(
            project["python"]["mutation_max_changed_lines"],
            DEFAULT_PYTHON_MUTATION_MAX_CHANGED_LINES,
        )
        self.assertEqual(validate_project(project), [])

    def test_mutation_run_timeout_preserves_results_headroom(self) -> None:
        self.assertEqual(PYTHON_MUTATION_GATE_TIMEOUT_SECONDS, 7200)
        self.assertEqual(PYTHON_MUTATION_RESULTS_TIMEOUT_SECONDS, 300)
        self.assertEqual(PYTHON_MUTATION_OVERHEAD_SECONDS, 300)
        self.assertEqual(PYTHON_MUTATION_SAFETY_MARGIN_SECONDS, 300)
        self.assertEqual(
            PYTHON_MUTATION_RUN_TIMEOUT_SECONDS,
            PYTHON_MUTATION_GATE_TIMEOUT_SECONDS
            - PYTHON_MUTATION_RESULTS_TIMEOUT_SECONDS
            - PYTHON_MUTATION_OVERHEAD_SECONDS
            - PYTHON_MUTATION_SAFETY_MARGIN_SECONDS,
        )
        self.assertEqual(
            PYTHON_MUTATION_RUN_TIMEOUT_SECONDS
            + PYTHON_MUTATION_RESULTS_TIMEOUT_SECONDS
            + PYTHON_MUTATION_OVERHEAD_SECONDS
            + PYTHON_MUTATION_SAFETY_MARGIN_SECONDS,
            PYTHON_MUTATION_GATE_TIMEOUT_SECONDS,
        )
        self.assertEqual(
            PYTHON_MUTATION_GATE_TIMEOUT_SECONDS - PYTHON_MUTATION_RUN_TIMEOUT_SECONDS,
            PYTHON_MUTATION_RESULTS_TIMEOUT_SECONDS
            + PYTHON_MUTATION_OVERHEAD_SECONDS
            + PYTHON_MUTATION_SAFETY_MARGIN_SECONDS,
        )

    def _python_mutation_project(self, *, max_changed_lines: int = 250) -> dict[str, object]:
        return {
            "enforcement": {"base_ref": "HEAD", "mode": "adopt", "scope": "changed"},
            "paths": {"source": ["src"], "tests": ["tests"], "exclude": []},
            "python": {
                "source_paths": ["src"],
                "test_paths": ["tests"],
                "mutation_max_changed_lines": max_changed_lines,
                "mutation_timeout_multiplier": 5.0,
                "mutation_timeout_constant": 1.0,
            },
            "thresholds": {
                "mutation": {
                    "changed_only": True,
                    "maximum_survivors": 0,
                    "minimum_selection_coverage": 80,
                    "minimum_score": 70,
                }
            },
            "profile_thresholds": {},
            "stacks": {"python": True, "javascript": False},
        }

    def test_python_mutation_full_scope_counts_total_target_lines(self) -> None:
        source = self.root / "src"
        source.mkdir()
        (self.root / "tests").mkdir()
        (source / "module.py").write_text(
            "\n".join(f"VALUE_{index} = {index}" for index in range(12)) + "\n",
            encoding="utf-8",
        )
        self.commit("baseline")
        project = self._python_mutation_project(max_changed_lines=5)
        project["thresholds"]["mutation"]["changed_only"] = False

        with (
            patch("aqg.adapters._copy_for_mutmut") as copy_sandbox,
            patch("aqg.adapters.run_command") as run_command,
            patch("aqg.adapters._tool") as tool,
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, CONFIGURATION_ERROR)
        self.assertTrue(report["scope_refused"])
        self.assertEqual(report["scope"], "full")
        self.assertEqual(report["changed_production_lines"], 12)
        self.assertEqual(report["changed_production_lines_by_file"]["src/module.py"], 12)
        self.assertIn("Python production lines 12 exceed", report["reason"])
        copy_sandbox.assert_not_called()
        run_command.assert_not_called()
        tool.assert_not_called()

    def test_python_mutation_refuses_oversized_scope_before_mutmut(self) -> None:
        source = self.root / "src"
        source.mkdir()
        (self.root / "tests").mkdir()
        body = "\n".join(f"VALUE_{index} = {index}" for index in range(40)) + "\n"
        (source / "module.py").write_text(body, encoding="utf-8")
        self.commit("baseline empty")
        (source / "module.py").write_text(
            body + "\n".join(f"EXTRA_{index} = {index}" for index in range(20)) + "\n",
            encoding="utf-8",
        )
        project = self._python_mutation_project(max_changed_lines=10)
        line_count, _ = _count_changed_python_production_lines(self.root, project)
        self.assertGreater(line_count, 10)

        with (
            patch("aqg.adapters._copy_for_mutmut") as copy_sandbox,
            patch("aqg.adapters.run_command") as run_command,
            patch("aqg.adapters._tool") as tool,
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, CONFIGURATION_ERROR)
        self.assertTrue(report["scope_refused"])
        self.assertFalse(report["campaign_complete"])
        self.assertEqual(report["incomplete_reason"], "scope_refused_before_mutmut")
        self.assertGreater(report["changed_production_lines"], 10)
        self.assertEqual(report["mutation_max_changed_lines"], 10)
        self.assertIn("exceed", report["reason"])
        copy_sandbox.assert_not_called()
        run_command.assert_not_called()
        tool.assert_not_called()

    def test_python_mutation_normal_scope_runs_mutmut_with_inner_budget(self) -> None:
        source = self.root / "src"
        source.mkdir()
        (self.root / "tests").mkdir()
        (source / "module.py").write_text(
            "VALUE = 1\n\ndef value() -> int:\n    return 1\n",
            encoding="utf-8",
        )
        self.commit("baseline")
        (source / "module.py").write_text(
            "VALUE = 1\n\ndef value() -> int:\n    return 2\n",
            encoding="utf-8",
        )
        project = self._python_mutation_project(max_changed_lines=50)
        project["thresholds"]["mutation"]["minimum_selection_coverage"] = 73
        selector = "module.x_value__mutmut_*"
        run_result = CommandResult(
            command=["mutmut", "run", selector],
            cwd=str(self.root),
            code=0,
            status="pass",
            stdout="",
            stderr="",
            duration_ms=10,
        )
        results_result = CommandResult(
            command=["mutmut", "results", "--all=true"],
            cwd=str(self.root),
            code=0,
            status="pass",
            stdout=("module.x_other__mutmut_1: not checked\nmodule.x_value__mutmut_1: killed\n"),
            stderr="",
            duration_ms=5,
        )

        with (
            patch("aqg.adapters._copy_for_mutmut") as copy_sandbox,
            patch("aqg.adapters._append_mutmut_config") as configure_sandbox,
            patch("aqg.adapters._tool", return_value="/tools/mutmut"),
            patch(
                "aqg.adapters.run_command",
                side_effect=[run_result, results_result],
            ) as run_command,
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, PASS)
        self.assertFalse(report["scope_refused"])
        self.assertTrue(report["campaign_complete"])
        self.assertEqual(report["incomplete_reason"], None)
        self.assertEqual(report["mutation_score"], 100.0)
        self.assertEqual(report["selection_mode"], "changed_functions")
        self.assertEqual(report["mutant_selectors"], [selector])
        self.assertEqual(report["selected_functions"], {"src/module.py": ["value"]})
        self.assertEqual(report["status_counts"], {"killed": 1})
        self.assertEqual(report["scope"], "changed")
        self.assertEqual(report["mutated_files"], ["src/module.py"])
        self.assertEqual(report["changed_production_lines"], 2)
        self.assertTrue(report["selection_complete"])
        self.assertEqual(report["mapped_changed_lines"], 2)
        self.assertEqual(report["unmapped_changed_lines"], {})
        self.assertEqual(report["selection_coverage"], 100.0)
        self.assertEqual(report["minimum_selection_coverage"], 73.0)
        self.assertEqual(report["mutmut_run_timeout_seconds"], PYTHON_MUTATION_RUN_TIMEOUT_SECONDS)
        self.assertEqual(run_command.call_count, 2)
        work = self.root / ".aqg" / "work" / "mutation" / "python-project"
        copy_sandbox.assert_called_once_with(self.root, work)
        configure_sandbox.assert_called_once_with(work, project, ["src/module.py"])
        run_kwargs = run_command.call_args_list[0].kwargs
        results_kwargs = run_command.call_args_list[1].kwargs
        self.assertEqual(run_kwargs["cwd"], work)
        self.assertEqual(results_kwargs["cwd"], work)
        self.assertEqual(run_kwargs["env"]["PYTHONHASHSEED"], "0")
        self.assertEqual(run_kwargs["env"]["TZ"], "UTC")
        self.assertIn(str(work), run_kwargs["env"]["PYTHONPATH"])
        self.assertIn(str(work / "src"), run_kwargs["env"]["PYTHONPATH"])
        self.assertEqual(run_kwargs["timeout"], PYTHON_MUTATION_RUN_TIMEOUT_SECONDS)
        self.assertEqual(results_kwargs["timeout"], PYTHON_MUTATION_RESULTS_TIMEOUT_SECONDS)
        self.assertEqual(
            run_command.call_args_list[0].args[0],
            ["/tools/mutmut", "run", selector],
        )
        self.assertEqual(
            run_command.call_args_list[1].args[0],
            ["/tools/mutmut", "results", "--all=true"],
        )

    def test_python_mutation_refuses_low_changed_function_selection_coverage(self) -> None:
        source = self.root / "src"
        source.mkdir()
        (self.root / "tests").mkdir()
        module = source / "module.py"
        module.write_text(
            "FIRST = 1\nSECOND = 2\nTHIRD = 3\n\ndef value() -> int:\n    return 1\n",
            encoding="utf-8",
        )
        self.commit("baseline")
        module.write_text(
            "FIRST = 2\nSECOND = 3\nTHIRD = 4\n\ndef value() -> int:\n    return 2\n",
            encoding="utf-8",
        )
        project = self._python_mutation_project()

        with (
            patch("aqg.adapters._copy_for_mutmut") as copy_sandbox,
            patch("aqg.adapters.run_command") as run_command,
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, CONFIGURATION_ERROR)
        self.assertTrue(report["scope_refused"])
        self.assertIs(report["campaign_complete"], False)
        self.assertEqual(report["incomplete_reason"], "insufficient_function_selection_coverage")
        self.assertEqual(report["mapped_changed_lines"], 2)
        self.assertEqual(report["nontrivial_changed_lines"], 8)
        self.assertEqual(report["selection_coverage"], 25.0)
        self.assertEqual(report["minimum_selection_coverage"], 80.0)
        self.assertIn("25.0% is below the protected minimum 80.0%", report["reason"])
        copy_sandbox.assert_not_called()
        run_command.assert_not_called()

    def test_python_mutation_passes_comment_only_production_changes_without_sandboxing(
        self,
    ) -> None:
        source = self.root / "src"
        source.mkdir()
        (self.root / "tests").mkdir()
        module = source / "module.py"
        module.write_text(
            "def value() -> int:\n    return 1\n",
            encoding="utf-8",
        )
        self.commit("baseline")
        module.write_text(
            "# Explain the stable behavior.\ndef value() -> int:\n    return 1\n",
            encoding="utf-8",
        )
        project = self._python_mutation_project()

        with (
            patch("aqg.adapters._copy_for_mutmut") as copy_sandbox,
            patch("aqg.adapters.run_command") as run_command,
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, PASS)
        self.assertFalse(report["scope_refused"])
        self.assertTrue(report["campaign_complete"])
        self.assertEqual(report["incomplete_reason"], None)
        self.assertEqual(report["nontrivial_changed_lines"], 0)
        self.assertEqual(report["mutant_selectors"], [])
        self.assertEqual(report["selection_coverage"], 100.0)
        self.assertEqual(report["reason"], "no changed executable Python production lines")
        copy_sandbox.assert_not_called()
        run_command.assert_not_called()

    def test_python_mutation_selects_surviving_function_for_deletion_only_edits(
        self,
    ) -> None:
        source = self.root / "src"
        source.mkdir()
        (self.root / "tests").mkdir()
        module = source / "authorization.py"
        module.write_text(
            "def allowed(user) -> bool:\n"
            "    if not user.is_admin:\n"
            "        return False\n"
            "    return True\n",
            encoding="utf-8",
        )
        self.commit("baseline")
        module.write_text(
            "def allowed(user) -> bool:\n    return True\n",
            encoding="utf-8",
        )
        project = self._python_mutation_project()
        selector = "authorization.x_allowed__mutmut_*"
        run_result = CommandResult(
            command=["mutmut", "run", selector],
            cwd=str(self.root),
            code=0,
            status="pass",
            stdout="",
            stderr="",
            duration_ms=10,
        )
        results_result = CommandResult(
            command=["mutmut", "results", "--all=true"],
            cwd=str(self.root),
            code=0,
            status="pass",
            stdout="authorization.x_allowed__mutmut_1: killed\n",
            stderr="",
            duration_ms=5,
        )

        with (
            patch("aqg.adapters._copy_for_mutmut"),
            patch("aqg.adapters._append_mutmut_config"),
            patch("aqg.adapters._tool", return_value="/tools/mutmut"),
            patch(
                "aqg.adapters.run_command",
                side_effect=[run_result, results_result],
            ) as run_command,
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, PASS)
        self.assertEqual(report["changed_production_lines"], 2)
        self.assertEqual(report["nontrivial_added_lines_by_file"], {})
        self.assertEqual(
            report["nontrivial_deleted_lines_by_file"],
            {"src/authorization.py": 2},
        )
        self.assertEqual(
            report["selected_functions"],
            {"src/authorization.py": ["allowed"]},
        )
        self.assertEqual(report["mapped_changed_lines"], 2)
        self.assertEqual(report["unmapped_deleted_lines"], {})
        self.assertEqual(report["selection_coverage"], 100.0)
        self.assertEqual(
            run_command.call_args_list[0].args[0],
            ["/tools/mutmut", "run", selector],
        )

    def test_python_mutation_passes_comment_only_deletions_without_sandboxing(
        self,
    ) -> None:
        source = self.root / "src"
        source.mkdir()
        (self.root / "tests").mkdir()
        module = source / "module.py"
        module.write_text(
            "# Explain the stable behavior.\ndef value() -> int:\n    return 1\n",
            encoding="utf-8",
        )
        self.commit("baseline")
        module.write_text(
            "def value() -> int:\n    return 1\n",
            encoding="utf-8",
        )
        project = self._python_mutation_project()

        with (
            patch("aqg.adapters._copy_for_mutmut") as copy_sandbox,
            patch("aqg.adapters.run_command") as run_command,
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, PASS)
        self.assertFalse(report["scope_refused"])
        self.assertTrue(report["campaign_complete"])
        self.assertEqual(report["changed_production_lines"], 1)
        self.assertEqual(report["nontrivial_changed_lines"], 0)
        self.assertEqual(report["mutant_selectors"], [])
        self.assertEqual(report["selection_coverage"], 100.0)
        self.assertEqual(report["reason"], "no changed executable Python production lines")
        copy_sandbox.assert_not_called()
        run_command.assert_not_called()

    def test_python_mutation_refuses_deletion_only_module_level_logic(self) -> None:
        source = self.root / "src"
        source.mkdir()
        (self.root / "tests").mkdir()
        module = source / "authorization.py"
        module.write_text(
            "REQUIRE_ADMIN = True\n\ndef allowed() -> bool:\n    return REQUIRE_ADMIN\n",
            encoding="utf-8",
        )
        self.commit("baseline")
        module.write_text(
            "def allowed() -> bool:\n    return True\n",
            encoding="utf-8",
        )
        project = self._python_mutation_project()

        with (
            patch("aqg.adapters._copy_for_mutmut") as copy_sandbox,
            patch("aqg.adapters.run_command") as run_command,
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, CONFIGURATION_ERROR)
        self.assertTrue(report["scope_refused"])
        self.assertFalse(report["campaign_complete"])
        self.assertEqual(
            report["incomplete_reason"],
            "deleted_lines_outside_mutable_functions",
        )
        self.assertEqual(report["unmapped_deleted_lines"], {"src/authorization.py": [1]})
        copy_sandbox.assert_not_called()
        run_command.assert_not_called()

    def test_python_mutation_refuses_deleted_production_files(self) -> None:
        source = self.root / "src"
        source.mkdir()
        (self.root / "tests").mkdir()
        module = source / "authorization.py"
        module.write_text(
            "def allowed() -> bool:\n    return False\n",
            encoding="utf-8",
        )
        self.commit("baseline")
        module.unlink()
        project = self._python_mutation_project()

        with (
            patch("aqg.adapters._copy_for_mutmut") as copy_sandbox,
            patch("aqg.adapters.run_command") as run_command,
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, CONFIGURATION_ERROR)
        self.assertTrue(report["scope_refused"])
        self.assertFalse(report["campaign_complete"])
        self.assertEqual(report["scope"], "changed")
        self.assertEqual(report["incomplete_reason"], "deleted_production_files")
        self.assertEqual(report["deleted_production_files"], ["src/authorization.py"])
        self.assertEqual(report["mutated_files"], [])
        self.assertEqual(report["changed_production_lines"], 2)
        self.assertEqual(
            report["changed_production_lines_by_file"],
            {"src/authorization.py": 2},
        )
        self.assertEqual(report["deletion_evidence_errors"], {})
        self.assertIn("cannot be mutation-tested", report["reason"])
        copy_sandbox.assert_not_called()
        run_command.assert_not_called()

    def test_python_mutation_ignores_deleted_test_and_ungoverned_paths(self) -> None:
        source = self.root / "src"
        source.mkdir()
        tests = self.root / "tests"
        tests.mkdir()
        support = source / "support"
        support.mkdir()
        (source / "keep.py").write_text("def keep() -> int:\n    return 1\n", encoding="utf-8")
        (tests / "test_sample.py").write_text(
            "def test_ok() -> None:\n    assert True\n", encoding="utf-8"
        )
        (support / "helper.py").write_text("def helper() -> int:\n    return 1\n", encoding="utf-8")
        (self.root / "scratch.py").write_text(
            "def noise() -> int:\n    return 0\n", encoding="utf-8"
        )
        self.commit("baseline")
        (tests / "test_sample.py").unlink()
        (support / "helper.py").unlink()
        (self.root / "scratch.py").unlink()
        project = self._python_mutation_project()
        project["paths"]["tests"] = ["tests", "src/support"]
        project["python"]["test_paths"] = ["tests", "src/support"]

        with (
            patch("aqg.adapters._copy_for_mutmut") as copy_sandbox,
            patch("aqg.adapters.run_command") as run_command,
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, PASS)
        self.assertEqual(report["changed_production_lines"], 0)
        self.assertNotIn("deleted_production_files", report)
        copy_sandbox.assert_not_called()
        run_command.assert_not_called()

    def test_python_mutation_empty_scope_report_is_exact(self) -> None:
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src" / "module.py").write_text(
            "def value() -> int:\n    return 1\n", encoding="utf-8"
        )
        self.commit("baseline")
        project = self._python_mutation_project()

        with (
            patch("aqg.adapters._copy_for_mutmut") as copy_sandbox,
            patch("aqg.adapters.run_command") as run_command,
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, PASS)
        self.assertEqual(
            report,
            {
                "scope": "changed",
                "scope_refused": False,
                "campaign_complete": True,
                "mutated_files": [],
                "changed_production_lines": 0,
                "reason": "no changed Python production files",
            },
        )
        copy_sandbox.assert_not_called()
        run_command.assert_not_called()

    def test_python_mutation_ignores_an_added_then_deleted_file_with_no_net_change(
        self,
    ) -> None:
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "README.md").write_text("baseline\n", encoding="utf-8")
        self.commit("baseline")
        base = git(self.root, "rev-parse", "HEAD")
        module = self.root / "src" / "temporary.py"
        module.write_text(
            "def transient() -> bool:\n    return True\n",
            encoding="utf-8",
        )
        self.commit("add temporary production module")
        module.unlink()
        project = self._python_mutation_project()

        with (
            patch.dict(os.environ, {"AQG_DIFF_BASE": base}),
            patch("aqg.adapters._copy_for_mutmut") as copy_sandbox,
            patch("aqg.adapters.run_command") as run_command,
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, PASS)
        self.assertEqual(report["changed_production_lines"], 0)
        self.assertNotIn("deleted_production_files", report)
        copy_sandbox.assert_not_called()
        run_command.assert_not_called()

    def test_python_mutation_counts_deleted_lines_against_scope_budget(self) -> None:
        source = self.root / "src"
        source.mkdir()
        (self.root / "tests").mkdir()
        module = source / "module.py"
        module.write_text(
            "def value() -> int:\n"
            + "".join(f"    item_{index} = {index}\n" for index in range(8))
            + "    return item_7\n",
            encoding="utf-8",
        )
        self.commit("baseline")
        module.write_text(
            "def value() -> int:\n    return 7\n",
            encoding="utf-8",
        )
        project = self._python_mutation_project(max_changed_lines=5)

        with (
            patch("aqg.adapters._copy_for_mutmut") as copy_sandbox,
            patch("aqg.adapters.run_command") as run_command,
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, CONFIGURATION_ERROR)
        self.assertTrue(report["scope_refused"])
        self.assertEqual(report["incomplete_reason"], "scope_refused_before_mutmut")
        self.assertGreater(report["changed_production_lines"], 5)
        copy_sandbox.assert_not_called()
        run_command.assert_not_called()

    def test_python_mutation_complete_survivors_are_a_quality_failure(self) -> None:
        source = self.root / "src"
        source.mkdir()
        (self.root / "tests").mkdir()
        module = source / "module.py"
        module.write_text("def value() -> int:\n    return 1\n", encoding="utf-8")
        self.commit("baseline")
        module.write_text("def value() -> int:\n    return 2\n", encoding="utf-8")
        project = self._python_mutation_project()
        selector = "module.x_value__mutmut_*"
        run_result = CommandResult(
            command=["mutmut", "run", selector],
            cwd=str(self.root),
            code=0,
            status="pass",
            stdout="",
            stderr="",
            duration_ms=10,
        )
        results_result = CommandResult(
            command=["mutmut", "results", "--all=true"],
            cwd=str(self.root),
            code=0,
            status="pass",
            stdout=(
                "module.x_value__mutmut_1: killed\n"
                "module.x_value__mutmut_2: survived\n"
                "module.x_value__mutmut_3: no tests\n"
            ),
            stderr="",
            duration_ms=5,
        )

        with (
            patch("aqg.adapters._copy_for_mutmut"),
            patch("aqg.adapters._append_mutmut_config"),
            patch("aqg.adapters._tool", return_value="/tools/mutmut"),
            patch("aqg.adapters.run_command", side_effect=[run_result, results_result]),
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, QUALITY_FAILURE)
        self.assertTrue(report["campaign_complete"])
        self.assertEqual(report["incomplete_reason"], None)
        self.assertEqual(report["status_counts"], {"killed": 1, "survived": 1, "no tests": 1})
        self.assertEqual(report["survivors"], 2)
        self.assertEqual(report["mutation_score"], 33.33)
        self.assertEqual(
            report["survivor_lines"],
            [
                "module.x_value__mutmut_2: survived",
                "module.x_value__mutmut_3: no tests",
            ],
        )

    def test_python_mutation_incomplete_campaign_is_infrastructure_failure(self) -> None:
        source = self.root / "src"
        source.mkdir()
        (self.root / "tests").mkdir()
        (source / "module.py").write_text(
            "def value() -> int:\n    return 1\n",
            encoding="utf-8",
        )
        self.commit("baseline")
        (source / "module.py").write_text(
            "def value() -> int:\n    return 2\n",
            encoding="utf-8",
        )
        project = self._python_mutation_project(max_changed_lines=50)
        run_result = CommandResult(
            command=["mutmut", "run"],
            cwd=str(self.root),
            code=INFRASTRUCTURE_ERROR,
            status="infrastructure_error",
            stdout="",
            stderr="command timed out after 6600s",
            duration_ms=6600000,
            timed_out=True,
        )
        results_result = CommandResult(
            command=["mutmut", "results", "--all=true"],
            cwd=str(self.root),
            code=0,
            status="pass",
            stdout=(
                "module.x_value__mutmut_1: killed\n"
                "module.x_value__mutmut_2: not checked\n"
                "module.x_value__mutmut_3: survived\n"
            ),
            stderr="",
            duration_ms=20,
        )

        with (
            patch("aqg.adapters._copy_for_mutmut"),
            patch("aqg.adapters._append_mutmut_config"),
            patch("aqg.adapters._tool", return_value="/tools/mutmut"),
            patch(
                "aqg.adapters.run_command",
                side_effect=[run_result, results_result],
            ),
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, INFRASTRUCTURE_ERROR)
        self.assertIs(report["campaign_complete"], False)
        self.assertTrue(report["run_timed_out"])
        self.assertEqual(report["incomplete_reason"], "mutmut_budget_exhausted")
        self.assertGreaterEqual(report["incomplete_mutants"], 1)
        # Unchecked work must not become a passing score even if some mutants died.
        self.assertNotEqual(code, PASS)

    def test_python_mutation_selects_changed_functions_and_methods_deterministically(
        self,
    ) -> None:
        source = self.root / "src" / "package"
        source.mkdir(parents=True)
        (self.root / "tests").mkdir()
        module = source / "example.py"
        module.write_text(
            "def alpha() -> int:\n"
            "    return 1\n\n"
            "class Worker:\n"
            "    @classmethod\n"
            "    def build(cls) -> int:\n"
            "        return 2\n\n"
            "def untouched() -> int:\n"
            "    return 3\n",
            encoding="utf-8",
        )
        self.commit("baseline")
        module.write_text(
            "def alpha() -> int:\n"
            "    return 4\n\n"
            "class Worker:\n"
            "    @classmethod\n"
            "    def build(cls) -> int:\n"
            "        return 5\n\n"
            "def untouched() -> int:\n"
            "    return 3\n",
            encoding="utf-8",
        )
        project = self._python_mutation_project()

        selection = _python_mutation_function_selection(
            self.root, project, ["src/package/example.py"]
        )

        self.assertEqual(
            selection["mutant_selectors"],
            [
                "package.example.x_alpha__mutmut_*",
                "package.example.xǁWorkerǁbuild__mutmut_*",
            ],
        )
        self.assertEqual(
            selection["selected_functions"],
            {"src/package/example.py": ["Worker.build", "alpha"]},
        )
        self.assertEqual(selection["unmapped_changed_lines"], {})
        self.assertEqual(selection["selection_errors"], {})
        self.assertTrue(selection["selection_complete"])
        self.assertEqual(selection["mapped_changed_lines"], 4)
        self.assertEqual(selection["selection_coverage"], 100.0)

    def test_python_mutation_rejects_nontrivial_module_level_changes(self) -> None:
        source = self.root / "src"
        source.mkdir()
        (self.root / "tests").mkdir()
        module = source / "module.py"
        module.write_text("VALUE = 1\n", encoding="utf-8")
        self.commit("baseline")
        module.write_text("VALUE = 2\n", encoding="utf-8")
        project = self._python_mutation_project()

        with (
            patch("aqg.adapters._copy_for_mutmut") as copy_sandbox,
            patch("aqg.adapters.run_command") as run_command,
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, CONFIGURATION_ERROR)
        self.assertTrue(report["scope_refused"])
        self.assertFalse(report["campaign_complete"])
        self.assertEqual(report["incomplete_reason"], "changed_lines_outside_mutable_functions")
        self.assertEqual(report["mutant_selectors"], [])
        self.assertEqual(report["unmapped_changed_lines"], {"src/module.py": [1]})
        self.assertFalse(report["selection_complete"])
        self.assertEqual(report["selection_coverage"], 0.0)
        copy_sandbox.assert_not_called()
        run_command.assert_not_called()

    def test_python_mutation_uses_protected_selection_coverage_default(self) -> None:
        source = self.root / "src"
        source.mkdir()
        (self.root / "tests").mkdir()
        module = source / "module.py"
        module.write_text(
            "def value() -> int:\n    return 1\n",
            encoding="utf-8",
        )
        self.commit("baseline")
        module.write_text(
            "# Comment-only change.\ndef value() -> int:\n    return 1\n",
            encoding="utf-8",
        )
        project = self._python_mutation_project()
        del project["thresholds"]["mutation"]["minimum_selection_coverage"]

        code, report = _mutation_python(self.root, project)

        self.assertEqual(code, PASS)
        self.assertEqual(report["minimum_selection_coverage"], 80.0)

    def test_python_mutation_rejects_selection_parse_errors_before_sandboxing(self) -> None:
        source = self.root / "src"
        source.mkdir()
        (self.root / "tests").mkdir()
        module = source / "module.py"
        module.write_text("def value() -> int:\n    return 1\n", encoding="utf-8")
        self.commit("baseline")
        module.write_text("def value( -> int:\n    return 2\n", encoding="utf-8")
        project = self._python_mutation_project()

        with (
            patch("aqg.adapters._copy_for_mutmut") as copy_sandbox,
            patch("aqg.adapters.run_command") as run_command,
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, CONFIGURATION_ERROR)
        self.assertTrue(report["scope_refused"])
        self.assertEqual(report["incomplete_reason"], "mutation_selection_error")
        self.assertIn("src/module.py", report["selection_errors"])
        self.assertIn("could not be parsed", report["reason"])
        copy_sandbox.assert_not_called()
        run_command.assert_not_called()

    def test_python_mutation_rejects_windows_before_resolving_scope(self) -> None:
        project = self._python_mutation_project()

        with (
            patch(
                "aqg.adapters._python_mutation_platform_supported", return_value=False
            ) as supported,
            patch("aqg.adapters._python_mutation_targets") as targets,
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, CONFIGURATION_ERROR)
        self.assertEqual(
            report["configuration_error"],
            "mutmut requires fork support; run the mutation gate inside WSL on Windows",
        )
        supported.assert_called_once_with(os.name)
        targets.assert_not_called()

    def test_python_mutation_platform_support_is_a_pure_name_check(self) -> None:
        self.assertFalse(_python_mutation_platform_supported("nt"))
        self.assertTrue(_python_mutation_platform_supported("posix"))

    def test_python_mutation_full_scope_runs_without_selector_arguments(self) -> None:
        source = self.root / "src"
        source.mkdir()
        (self.root / "tests").mkdir()
        module = source / "module.py"
        module.write_text("def value() -> int:\n    return 1\n", encoding="utf-8")
        self.commit("baseline")
        project = self._python_mutation_project(max_changed_lines=50)
        project["thresholds"]["mutation"]["changed_only"] = False
        run_result = CommandResult(
            command=["mutmut", "run"],
            cwd=str(self.root),
            code=0,
            status="pass",
            stdout="",
            stderr="",
            duration_ms=10,
        )
        results_result = CommandResult(
            command=["mutmut", "results", "--all=true"],
            cwd=str(self.root),
            code=0,
            status="pass",
            stdout="module.x_value__mutmut_1: killed\n",
            stderr="",
            duration_ms=5,
        )

        with (
            patch("aqg.adapters._copy_for_mutmut"),
            patch("aqg.adapters._append_mutmut_config"),
            patch("aqg.adapters._tool", return_value="/tools/mutmut"),
            patch("aqg.adapters.run_command", side_effect=[run_result, results_result]) as run,
        ):
            code, report = _mutation_python(self.root, project)

        self.assertEqual(code, PASS)
        self.assertEqual(report["scope"], "full")
        self.assertEqual(report["mutated_files"], ["src/module.py"])
        self.assertEqual(report["changed_production_lines"], 2)
        self.assertEqual(report["selection_mode"], "full")
        self.assertEqual(report["mutant_selectors"], [])
        self.assertEqual(report["selected_functions"], {})
        self.assertEqual(report["unmapped_changed_lines"], {})
        self.assertEqual(report["selection_errors"], {})
        self.assertTrue(report["campaign_complete"])
        self.assertEqual(run.call_args_list[0].args[0], ["/tools/mutmut", "run"])

    def test_nontrivial_changed_lines_reads_with_utf8_replace(self) -> None:
        source = self.root / "module.py"
        source.write_text("x = 1\n", encoding="utf-8")
        with patch(
            "pathlib.Path.read_text",
            return_value="def value() -> int:\n    # c\n    return 1\n",
        ) as read_text:
            selected = _nontrivial_changed_lines(source, {1, 2, 3})
        self.assertEqual(selected, {1, 3})
        read_text.assert_called_once_with(encoding="utf-8", errors="replace")

    def test_mutmut_module_name_matches_mutmut_path_conventions(self) -> None:
        self.assertEqual(_mutmut_module_name("src/aqg/scaffold.py"), "aqg.scaffold")
        self.assertEqual(_mutmut_module_name("src/aqg/__init__.py"), "aqg")
        self.assertEqual(_mutmut_module_name("scripts/build_release.py"), "scripts.build_release")

    def test_mutmut_function_candidates_follow_mutmut_decorator_and_method_rules(self) -> None:
        tree = ast.parse(
            "@decorator\n"
            "def decorated_function() -> int:\n"
            "    return 1\n\n"
            "async def async_function() -> int:\n"
            "    return 2\n\n"
            "@decorator\n"
            "class DecoratedClass:\n"
            "    def skipped(self) -> int:\n"
            "        return 3\n\n"
            "class Worker:\n"
            "    @staticmethod\n"
            "    async def static_async() -> int:\n"
            "        return 4\n\n"
            "    @classmethod\n"
            "    def build(cls) -> int:\n"
            "        return 5\n\n"
            "    @property\n"
            "    def label(self) -> str:\n"
            "        return 'worker'\n\n"
            "    def ordinary(self) -> int:\n"
            "        return 6\n\n"
            "    def __new__(cls):\n"
            "        return super().__new__(cls)\n"
        )

        candidates = _mutmut_function_candidates("src/package/example.py", tree)

        self.assertEqual(
            candidates,
            [
                (
                    "package.example.x_async_function__mutmut_*",
                    "async_function",
                    5,
                    6,
                ),
                (
                    "package.example.xǁWorkerǁstatic_async__mutmut_*",
                    "Worker.static_async",
                    14,
                    16,
                ),
                (
                    "package.example.xǁWorkerǁbuild__mutmut_*",
                    "Worker.build",
                    18,
                    20,
                ),
                (
                    "package.example.xǁWorkerǁordinary__mutmut_*",
                    "Worker.ordinary",
                    26,
                    27,
                ),
            ],
        )

    def test_mutmut_decorator_rules_require_exact_supported_method_decorators(self) -> None:
        module = ast.parse(
            "def plain():\n"
            "    pass\n\n"
            "@decorator\n"
            "def decorated():\n"
            "    pass\n\n"
            "class Worker:\n"
            "    @classmethod\n"
            "    def class_method(cls):\n"
            "        pass\n\n"
            "    @helpers.classmethod\n"
            "    def qualified(cls):\n"
            "        pass\n"
        )
        plain = module.body[0]
        decorated = module.body[1]
        worker = module.body[2]
        assert isinstance(plain, ast.FunctionDef)
        assert isinstance(decorated, ast.FunctionDef)
        assert isinstance(worker, ast.ClassDef)
        class_method = worker.body[0]
        qualified = worker.body[1]
        assert isinstance(class_method, ast.FunctionDef)
        assert isinstance(qualified, ast.FunctionDef)

        self.assertTrue(_mutmut_allows_decorators(plain, method=False))
        self.assertFalse(_mutmut_allows_decorators(decorated, method=False))
        self.assertTrue(_mutmut_allows_decorators(class_method, method=True))
        self.assertFalse(_mutmut_allows_decorators(qualified, method=True))

    def test_nontrivial_changed_lines_filters_bounds_blanks_and_comments(self) -> None:
        source = self.root / "module.py"
        source.write_bytes(b"# comment\n\nvalue = '\\xff'\n    # indented comment\n")

        selected = _nontrivial_changed_lines(source, {-1, 0, 1, 2, 3, 4, 5})

        self.assertEqual(selected, {3})

    def test_mutmut_result_parser_separates_outcomes(self) -> None:
        counts, lines = _parse_mutmut_results(
            """
                aqg.example.x_value__mutmut_1: killed
                aqg.example.x_value__mutmut_2: survived
                aqg.example.x_value__mutmut_3: no tests
                aqg.example.x_value__mutmut_4: not checked
                aqg.example.x_value__mutmut_5: caught by type check
            """
        )

        self.assertEqual(
            counts,
            {
                "killed": 1,
                "survived": 1,
                "no tests": 1,
                "not checked": 1,
                "caught by type check": 1,
            },
        )
        self.assertEqual(
            lines["survived"],
            ["aqg.example.x_value__mutmut_2: survived"],
        )

        filtered_counts, filtered_lines = _parse_mutmut_results(
            """
                aqg.example.x_value__mutmut_1: killed
                aqg.example.x_other__mutmut_1: not checked
            """,
            ["aqg.example.x_value__mutmut_*"],
        )
        self.assertEqual(filtered_counts, {"killed": 1})
        self.assertEqual(
            filtered_lines,
            {"killed": ["aqg.example.x_value__mutmut_1: killed"]},
        )
        empty_counts, empty_lines = _parse_mutmut_results(
            "aqg.example.x_value__mutmut_1: killed",
            [],
        )
        self.assertEqual(empty_counts, {})
        self.assertEqual(empty_lines, {})

    def test_mutmut_result_command_supplies_click_boolean_value(self) -> None:
        self.assertEqual(
            _mutmut_results_command("/tools/mutmut"),
            ["/tools/mutmut", "results", "--all=true"],
        )

    def test_mutmut_result_classifier_enforces_score_and_completeness(self) -> None:
        passing, passing_metrics = _classify_mutmut_results(
            {"killed": 7, "survived": 1},
            run_code=0,
            results_code=0,
            minimum_score=85,
            maximum_survivors=1,
        )
        weak, weak_metrics = _classify_mutmut_results(
            {"killed": 6, "survived": 2},
            run_code=0,
            results_code=0,
            minimum_score=85,
            maximum_survivors=2,
        )
        incomplete, _ = _classify_mutmut_results(
            {"killed": 8, "not checked": 1},
            run_code=0,
            results_code=0,
            minimum_score=85,
            maximum_survivors=0,
        )
        controlled_timeout, timeout_metrics = _classify_mutmut_results(
            {"killed": 7, "timeout": 1},
            run_code=0,
            results_code=0,
            minimum_score=100,
            maximum_survivors=0,
        )

        self.assertEqual(passing, PASS)
        self.assertEqual(passing_metrics["mutation_score"], 87.5)
        self.assertEqual(weak, QUALITY_FAILURE)
        self.assertEqual(weak_metrics["mutation_score"], 75.0)
        self.assertEqual(incomplete, INFRASTRUCTURE_ERROR)
        self.assertEqual(controlled_timeout, PASS)
        self.assertEqual(timeout_metrics["killed"], 8)

    def test_mutmut_result_classifier_treats_command_errors_as_infrastructure(self) -> None:
        cases = (
            (1, 0, {"killed": 8}),
            (0, 1, {"killed": 8}),
            (3, 0, {"killed": 8}),
            (0, 3, {"killed": 8}),
            (0, 0, {}),
            (1, 0, {"survived": 8}),
        )
        for run_code, results_code, statuses in cases:
            with self.subTest(
                run_code=run_code,
                results_code=results_code,
                statuses=statuses,
            ):
                code, _ = _classify_mutmut_results(
                    statuses,
                    run_code=run_code,
                    results_code=results_code,
                    minimum_score=0,
                    maximum_survivors=10,
                )
                self.assertEqual(code, INFRASTRUCTURE_ERROR)

    def test_mutmut_result_classifier_rejects_every_incomplete_status(self) -> None:
        for status in (
            "check was interrupted by user",
            "not checked",
            "skipped",
            "suspicious",
        ):
            with self.subTest(status=status):
                code, metrics = _classify_mutmut_results(
                    {"killed": 8, status: 1},
                    run_code=0,
                    results_code=0,
                    minimum_score=0,
                    maximum_survivors=0,
                )
                self.assertEqual(code, INFRASTRUCTURE_ERROR)
                self.assertEqual(metrics["incomplete_mutants"], 1)

    def test_universal_lock_restores_direct_environment_markers(self) -> None:
        requirements = self.root / "requirements.in"
        lock = self.root / "requirements.lock.txt"
        requirements.write_text(
            'conditional_dep==1.2; python_version >= "3.13"\nplain==2.0\n',
            encoding="utf-8",
        )
        lock.write_text(
            "conditional-dep==1.2 \\\n"
            "    --hash=sha256:abc\n"
            "plain==2.0 \\\n"
            "    --hash=sha256:def\n",
            encoding="utf-8",
        )

        self.assertEqual(
            _direct_requirement_markers(requirements),
            {"conditional-dep": 'python_version >= "3.13"'},
        )
        _restore_direct_requirement_markers(requirements, lock)
        content = lock.read_text(encoding="utf-8")
        self.assertIn('conditional-dep==1.2 ; python_version >= "3.13" \\', content)
        self.assertIn("plain==2.0 \\", content)

    def test_rendered_policy_contains_every_registered_gate(self) -> None:
        policy = tomllib.loads(render_policy("@quality"))
        self.assertEqual(set(policy["gates"]), set(GATE_NAMES))
        self.assertNotIn("assurance", policy["profiles"]["inner"]["gates"])
        self.assertNotIn("assurance", policy["profiles"]["fast"]["gates"])
        self.assertIn("assurance", policy["profiles"]["pr"]["gates"])
        self.assertIn("policy_maintenance", policy["profiles"]["pr"]["gates"])
        self.assertIn("supply_chain", policy["profiles"]["deep"]["gates"])
        self.assertIn("assurance", policy["profiles"]["deep"]["gates"])
        self.assertIn("policy_maintenance", policy["profiles"]["deep"]["gates"])
        self.assertIn("supply_chain", policy["profiles"]["release"]["gates"])
        self.assertIn("assurance", policy["profiles"]["release"]["gates"])
        self.assertIn("policy_maintenance", policy["profiles"]["release"]["gates"])

    def test_complete_lock_derived_supply_chain_gate_passes(self) -> None:
        (self.root / "requirements.txt").write_text("idna==3.10\n", encoding="utf-8")
        initialize_project(self.root, install=False, ci=False, mode="greenfield")
        code, report = run_adapter(self.root, "supply_chain")
        self.assertEqual(code, PASS)
        self.assertTrue(report["inventory"]["complete"])

    @pytest.mark.mutation_incompatible
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
        self.assertTrue((target / "aqg").exists())
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
        self.assertEqual(
            validate_named_schema(source_root, "release-provenance", provenance),
            [],
        )
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

    @pytest.mark.mutation_incompatible
    def test_release_excludes_ignored_caches_and_canonicalizes_remote_urls(self) -> None:
        """Ignored caches and equivalent GitHub remote spellings must not change release bytes."""
        source_root = Path(__file__).resolve().parents[1]
        output_a = self.root / "release-a"
        output_b = self.root / "release-b"
        cache_dir = source_root / "src" / "aqg" / "templates" / "python" / ".ruff_cache"
        cache_root_existed = cache_dir.exists()
        cache_files = [cache_dir / "aqg-release-repro-test" / "content.db"]
        original_remote = ""
        remote_probe = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=source_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if remote_probe.returncode == 0:
            original_remote = remote_probe.stdout.strip()

        try:
            for path in cache_files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"ignored-cache-bytes-must-not-enter-payload\n")

            git(
                source_root,
                "config",
                "remote.origin.url",
                "https://github.com/siraht/AgentGauntlet.git",
            )
            build_a = build_release(source_root, output_a)
            self.assertEqual(build_a.returncode, 0, build_a.stderr)

            git(
                source_root,
                "config",
                "remote.origin.url",
                "https://github.com/siraht/AgentGauntlet",
            )
            build_b = build_release(source_root, output_b)
            self.assertEqual(build_b.returncode, 0, build_b.stderr)

            names_a = sorted(path.name for path in output_a.iterdir() if path.is_file())
            names_b = sorted(path.name for path in output_b.iterdir() if path.is_file())
            self.assertEqual(names_a, names_b)
            for name in names_a:
                self.assertEqual(
                    (output_a / name).read_bytes(),
                    (output_b / name).read_bytes(),
                    msg=f"artifact bytes diverged for {name}",
                )

            with zipfile.ZipFile(output_a / "aqg.pyz") as archive:
                members = archive.namelist()
            self.assertIn("aqg/py.typed", members)
            self.assertFalse(
                any(".ruff_cache" in member or member.endswith(".pyc") for member in members)
            )
            self.assertEqual(len(members), len(set(members)))

            provenance = read_json(output_a / "provenance.intoto.json")
            dependencies = provenance["predicate"]["buildDefinition"]["resolvedDependencies"]
            repository_uris = {
                item["uri"]
                for item in dependencies
                if "digest" in item and "gitCommit" in item.get("digest", {})
            }
            self.assertEqual(repository_uris, {"https://github.com/siraht/AgentGauntlet"})
            material_uris = [item.get("uri", "") for item in dependencies if item.get("name")]
            self.assertTrue(material_uris)
            self.assertTrue(
                all(
                    not uri.startswith("https://github.com/siraht/AgentGauntlet.git")
                    for uri in material_uris
                )
            )
            material_names = {item.get("name") for item in dependencies}
            self.assertNotIn("src/aqg/templates/python/.ruff_cache/CACHEDIR.TAG", material_names)
        finally:
            for path in cache_files:
                path.unlink(missing_ok=True)
                if path.parent.exists():
                    path.parent.rmdir()
            if not cache_root_existed and cache_dir.exists():
                cache_dir.rmdir()
            if original_remote:
                git(source_root, "config", "remote.origin.url", original_remote)
            else:
                subprocess.run(
                    ["git", "config", "--unset", "remote.origin.url"],
                    cwd=source_root,
                    check=False,
                    capture_output=True,
                )

    def test_release_builds_from_an_isolated_copy_without_git_metadata(self) -> None:
        source_root = Path(__file__).resolve().parents[1]
        outer_revision_marker = self.root / "outer-repository.txt"
        outer_revision_marker.write_text("must not enter isolated provenance\n", encoding="utf-8")
        self.commit("outer repository revision")
        outer_revision = git(self.root, "rev-parse", "HEAD")
        outer_remote = "https://example.invalid/outer/repository.git"
        git(self.root, "remote", "add", "origin", outer_remote)
        source_copy = self.root / ".isolated" / "source-copy"
        source_copy.parent.mkdir()
        shutil.copytree(
            source_root,
            source_copy,
            ignore=shutil.ignore_patterns(
                ".git",
                ".aqg",
                "__pycache__",
                ".ruff_cache",
                ".pytest_cache",
                ".mypy_cache",
                "node_modules",
                "dist",
                "build",
            ),
        )

        output = self.root / "isolated-release"
        built = build_release(source_copy, output)
        self.assertEqual(built.returncode, 0, built.stderr)
        with zipfile.ZipFile(output / "aqg.pyz") as archive:
            members = archive.namelist()
        self.assertIn("aqg/py.typed", members)
        self.assertFalse(any(".ruff_cache" in member for member in members))

        provenance = read_json(output / "provenance.intoto.json")
        definition = provenance["predicate"]["buildDefinition"]
        dependencies = definition["resolvedDependencies"]
        repository = dependencies[0]
        self.assertEqual(repository, {"uri": "local:AgentGauntlet", "digest": {}})
        self.assertFalse(any(item.get("digest", {}).get("gitCommit") for item in dependencies))
        serialized = json.dumps(provenance, sort_keys=True)
        self.assertNotIn(outer_revision, serialized)
        self.assertNotIn(outer_remote, serialized)
        self.assertEqual(
            provenance["predicate"]["runDetails"]["metadata"]["invocationId"],
            "unversioned-source",
        )

    def test_release_source_discovery_works_beneath_a_hidden_parent(self) -> None:
        package = _RELEASE_MODULE.ROOT / "src" / "aqg"
        relative = {
            path.relative_to(package).as_posix() for path in _RELEASE_MODULE._package_source_files()
        }
        self.assertIn("py.typed", relative)
        self.assertFalse(any(part.startswith(".") for item in relative for part in item.split("/")))


if __name__ == "__main__":
    unittest.main()
