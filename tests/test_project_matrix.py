from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aqg.detect import detect_project
from aqg.scaffold import build_project_config


class CrossPlatformMatrixContractTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
