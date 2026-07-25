from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from argparse import _SubParsersAction
from pathlib import Path

from aqg.cli import COMMAND_HANDLERS, build_parser, main
from aqg.constants import CONFIGURATION_ERROR, PASS, QUALITY_FAILURE
from aqg.scaffold import initialize_project


def _git(root: Path, *args: str) -> None:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise AssertionError(completed.stderr)


class CliControlSurfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="aqg-cli-")
        self.root = Path(self.temp.name)
        _git(self.root, "init", "-q")
        _git(self.root, "config", "user.email", "aqg@example.invalid")
        _git(self.root, "config", "user.name", "AQG CLI Tests")
        (self.root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        _git(self.root, "add", "app.py")
        _git(self.root, "commit", "-qm", "existing project")
        initialize_project(
            self.root,
            owner="@quality",
            install=False,
            ci=False,
            mode="adopt",
        )
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-qm", "initialize AQG")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _json_command(self, *arguments: str) -> tuple[int, object, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        argv = ["--root", str(self.root), "--json", *arguments]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        return code, json.loads(stdout.getvalue()), stderr.getvalue()

    def test_every_parser_command_has_an_explicit_route(self) -> None:
        parser = build_parser()
        subparsers = next(
            action for action in parser._actions if isinstance(action, _SubParsersAction)
        )
        routed = set(COMMAND_HANDLERS) | {"wizard", "setup", "init"}
        self.assertEqual(set(subparsers.choices), routed)

    def test_read_only_json_control_surfaces_return_structured_payloads(self) -> None:
        cases = (
            (("detect",), {PASS}),
            (("status",), {PASS}),
            (("doctor",), {PASS}),
            (("tools", "status"), {PASS}),
            (("risk-card",), {PASS}),
            (("changed-files",), {PASS}),
            (("guidance", "--list"), {PASS}),
            (("guidance", "--search", "mutation"), {PASS}),
            (("onboarding", "show"), {PASS, CONFIGURATION_ERROR}),
            (("onboarding", "next"), {PASS, CONFIGURATION_ERROR}),
            (("acceptance", "lint"), {PASS}),
            (("golden",), {CONFIGURATION_ERROR}),
            (("conformance",), {PASS}),
            (("report",), {PASS}),
        )
        for arguments, expected_codes in cases:
            with self.subTest(command=" ".join(arguments)):
                code, payload, stderr = self._json_command(*arguments)
                self.assertIn(code, expected_codes, stderr)
                self.assertIsNotNone(payload)

    def test_json_mode_wraps_exceptions_in_a_stable_error_envelope(self) -> None:
        code, payload, stderr = self._json_command("golden")
        self.assertEqual(code, CONFIGURATION_ERROR)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"]["category"], "configuration_error")
        self.assertEqual(payload["error"]["exit_code"], CONFIGURATION_ERROR)
        self.assertIn("scenarios.json", payload["error"]["message"])
        self.assertIn("configuration error:", stderr)

    def test_missing_human_approvals_fail_closed_with_json_evidence(self) -> None:
        code, payload, _ = self._json_command(
            "approval", "validate", "--risk-profile", "high_assurance"
        )
        self.assertEqual(code, QUALITY_FAILURE)
        self.assertTrue(payload["errors"])
        self.assertEqual(payload["exit_code"], QUALITY_FAILURE)

    def test_global_flags_work_after_the_subcommand(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["status", "--root", str(self.root), "--json"])
        self.assertEqual(code, PASS)
        self.assertEqual(json.loads(stdout.getvalue())["project"]["name"], self.root.name)


if __name__ == "__main__":
    unittest.main()
