from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aqg.detect import detect_project
from aqg.scaffold import build_project_config

_MATRIX_SPEC = importlib.util.spec_from_file_location(
    "aqg_project_matrix",
    Path(__file__).resolve().parents[1] / "scripts" / "project_matrix.py",
)
assert _MATRIX_SPEC and _MATRIX_SPEC.loader
_MATRIX_MODULE = importlib.util.module_from_spec(_MATRIX_SPEC)
_MATRIX_SPEC.loader.exec_module(_MATRIX_MODULE)
_corepack_shim = _MATRIX_MODULE._corepack_shim
_prepare_typescript_web = _MATRIX_MODULE._prepare_typescript_web
_stage_typescript_web_change = _MATRIX_MODULE._stage_typescript_web_change
_executed_mutant_count = _MATRIX_MODULE._executed_mutant_count

_PILOT_SPEC = importlib.util.spec_from_file_location(
    "aqg_dogfood_web_pilot",
    Path(__file__).resolve().parents[1] / "scripts" / "dogfood_web_pilot.py",
)
assert _PILOT_SPEC and _PILOT_SPEC.loader
_PILOT_MODULE = importlib.util.module_from_spec(_PILOT_SPEC)
_PILOT_SPEC.loader.exec_module(_PILOT_MODULE)


class CrossPlatformMatrixContractTests(unittest.TestCase):
    def test_yarn_uses_project_pinned_corepack_even_when_global_yarn_exists(self) -> None:
        with (
            tempfile.TemporaryDirectory(prefix="aqg-contract-") as temporary,
            patch.object(_MATRIX_MODULE, "_run") as run,
            patch.object(
                _MATRIX_MODULE.shutil,
                "which",
                side_effect=lambda command: {
                    "npm": sys.executable,
                    "node": sys.executable,
                    "yarn": "/usr/bin/yarn",
                }.get(command),
            ),
            patch.dict(os.environ, {"PATH": "/usr/bin"}),
        ):
            project = Path(temporary) / "project"
            project.mkdir()
            _corepack_shim(project, "yarn")

            self.assertEqual(run.call_count, 3)
            bootstrap = run.call_args_list[0].args[0]
            self.assertEqual(bootstrap[:2], ["npm", "install"])
            self.assertIn("corepack@0.34.0", bootstrap)
            hydrate = run.call_args_list[1].args[0]
            self.assertEqual(hydrate[-1], "install")
            enable = run.call_args_list[2].args[0]
            self.assertEqual(enable[-1], "yarn")
            self.assertTrue(os.environ["PATH"].startswith(str(Path(temporary) / ".manager-bin")))

    def test_every_manager_and_runner_produces_argv_commands(self) -> None:
        combinations = (
            ("npm", "vitest"),
            ("npm", "jest"),
            ("pnpm", "mocha"),
            ("yarn", "ava"),
            ("bun", "node"),
        )
        for manager, runner in combinations:
            with (
                self.subTest(manager=manager, runner=runner),
                tempfile.TemporaryDirectory(prefix="aqg-contract-") as temporary,
            ):
                root = Path(temporary)
                (root / "src").mkdir()
                (root / "test").mkdir()
                (root / "src" / "value.js").write_text(
                    "export const value = 1;\n", encoding="utf-8"
                )
                (root / "test" / "value.test.js").write_text(
                    "export const covered = true;\n", encoding="utf-8"
                )
                package = {
                    "name": "contract",
                    "packageManager": f"{manager}@1.0.0",
                    "devDependencies": {runner: "1.0.0"},
                }
                if runner == "node":
                    package["scripts"] = {"check": "node --test"}
                (root / "package.json").write_text(json.dumps(package), encoding="utf-8")
                project = build_project_config(root, detect_project(root))
                self.assertEqual(project["javascript"]["test_runner"], runner)
                for command_name in (
                    "collect_command",
                    "unit_command",
                    "coverage_command",
                ):
                    command = project["javascript"][command_name]
                    self.assertIsInstance(command, list)
                    self.assertTrue(command)
                    self.assertNotIn("sh", command)
                    self.assertNotIn("bash", command)

    def test_tox_is_detected_without_importing_tox(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aqg-contract-") as temporary:
            root = Path(temporary)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tox.ini").write_text("[tox]\nenv_list = py\n", encoding="utf-8")
            project = build_project_config(root, detect_project(root))
            self.assertEqual(project["python"]["test_runner"], "tox")
            self.assertEqual(project["python"]["unit_command"][0], "$AQG_PY_BIN/tox")

    def test_typescript_web_pilot_is_offline_inspectable_and_strict(self) -> None:
        """The connected matrix case is generated deterministically before npm installs it."""
        with tempfile.TemporaryDirectory(prefix="aqg-contract-") as temporary:
            root = Path(temporary)
            gates = _prepare_typescript_web(root)

            self.assertEqual(
                gates,
                [
                    "format",
                    "lint",
                    "typecheck",
                    "test_integrity",
                    "unit",
                    "structure",
                    "coverage",
                    "acceptance",
                    "mutation_changed",
                ],
            )
            detection = detect_project(root)
            self.assertTrue(detection.typescript)
            self.assertTrue(detection.html)
            self.assertTrue(detection.css)
            self.assertIn("vite", detection.frameworks)
            self.assertEqual(detection.js_test_runner, "vitest")
            project = build_project_config(root, detection, mode="greenfield")
            self.assertEqual(project["enforcement"]["mode"], "greenfield")
            self.assertEqual(project["enforcement"]["scope"], "full")
            self.assertTrue(project["gates"]["acceptance"]["applicable"])
            self.assertEqual(project["web"]["base_url"], "http://127.0.0.1:5173")
            self.assertIn("noUncheckedIndexedAccess", (root / "tsconfig.json").read_text())
            self.assertIn("fast-check", (root / "tests" / "counter.test.ts").read_text())
            self.assertIn("AxeBuilder", (root / "e2e" / "counter.spec.mjs").read_text())
            self.assertIn("CTP-WEB-001", (root / "feature-spec" / "Counter.md").read_text())
            self.assertTrue((root / "qa" / "procedures" / "QA-COUNTER.md").is_file())

    def test_typescript_web_pilot_stages_a_real_mutation_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aqg-contract-") as temporary:
            root = Path(temporary)
            _prepare_typescript_web(root)
            before = (root / "src" / "counter.ts").read_text(encoding="utf-8")

            _stage_typescript_web_change(root)

            after = (root / "src" / "counter.ts").read_text(encoding="utf-8")
            test = (root / "tests" / "counter.test.ts").read_text(encoding="utf-8")
            self.assertNotEqual(after, before)
            self.assertIn("incrementByOne", after)
            self.assertIn("incrementByOne({ value: 4 })", test)

    def test_web_pilot_missing_control_is_configuration_error(self) -> None:
        result = {
            "duration_seconds": 0.1,
            "gates": [
                {"gate": gate, "exit_code": 0, "status": "pass"}
                for gate in sorted(_PILOT_MODULE.REQUIRED_CONTROLS - {"mutation_changed"})
            ],
        }
        with (
            tempfile.TemporaryDirectory(prefix="aqg-contract-") as temporary,
            patch.object(_PILOT_MODULE, "_execute_case", return_value=result),
        ):
            code, report = _PILOT_MODULE.run_pilot(Path(temporary))

        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "configuration_error")
        self.assertEqual(report["missing_controls"], ["mutation_changed"])

    def test_web_pilot_preserves_gate_failure_classification(self) -> None:
        for raw_code, status in (
            (1, "measured_failure"),
            (2, "configuration_error"),
            (3, "infrastructure_error"),
        ):
            with self.subTest(raw_code=raw_code):
                error = RuntimeError(f"typescript-web gate returned {raw_code}: detail")
                self.assertEqual(_PILOT_MODULE._failure_kind(error), (status, raw_code))

    def test_compile_errors_alone_do_not_count_as_executed_mutants(self) -> None:
        self.assertEqual(_executed_mutant_count({"CompileError": 4}), 0)
        self.assertEqual(_executed_mutant_count({"CompileError": 4, "Killed": 1}), 1)

    def test_web_pilot_help_starts_without_pythonpath(self) -> None:
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, "scripts/dogfood_web_pilot.py", "--help"],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("greenfield TypeScript/HTML/CSS", result.stdout)

    def test_installed_vitest_config_excludes_packaged_runtime_tests(self) -> None:
        """The application runner must not collect AQG's packaged template tests."""
        template = (
            Path(__file__).parents[1] / "src" / "aqg" / "templates" / "js" / "vitest.config.mjs"
        ).read_text(encoding="utf-8")
        self.assertIn('"**/quality/_aqg/**"', template)

    def test_installed_playwright_server_starts_from_application_root(self) -> None:
        """The browser runner must resolve the application's package scripts."""
        template = (
            Path(__file__).parents[1] / "src" / "aqg" / "templates" / "js" / "playwright.config.mjs"
        ).read_text(encoding="utf-8")
        self.assertIn("cwd: process.cwd()", template)


if __name__ == "__main__":
    unittest.main()
