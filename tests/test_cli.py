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

    def test_capabilities_is_complete_deterministic_and_project_independent(self) -> None:
        outputs: list[str] = []
        for _ in range(2):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["capabilities", "--json"])
            self.assertEqual(code, PASS)
            outputs.append(stdout.getvalue())
        self.assertEqual(outputs[0], outputs[1])
        payload = json.loads(outputs[0])
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["contract_version"], "1.0")
        self.assertEqual(set(payload["exit_codes"]), {"0", "1", "2", "3"})
        paths = {command["path"] for command in payload["commands"]}
        self.assertIn("check", paths)
        self.assertIn("onboarding refresh", paths)
        self.assertIn("capabilities", paths)
        self.assertEqual(payload["output"]["stdout"], "requested data")
        self.assertEqual(payload["output"]["stderr"], "diagnostics")

    def test_parse_errors_teach_exact_safe_corrections(self) -> None:
        cases = (
            (["capabilities", "--jsno"], "qg capabilities --json"),
            (["test"], "qg check fast"),
            (["verify"], "qg check-risk --keep-going"),
            (["health"], "qg doctor"),
            (["onboarding", "refrsh"], "qg onboarding refresh"),
            (["check"], "qg check fast"),
        )
        for argv, expected in cases:
            with self.subTest(argv=argv):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    code = main(argv)
                self.assertEqual(code, CONFIGURATION_ERROR)
                self.assertIn(expected, stderr.getvalue())

    def test_json_parse_error_contains_the_same_correction(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["test", "--json"])
        self.assertEqual(code, CONFIGURATION_ERROR)
        payload = json.loads(stdout.getvalue())
        self.assertIn("qg --json check fast", payload["error"]["message"])
        self.assertIn("qg --json check fast", stderr.getvalue())

    def test_robot_docs_is_project_independent_and_copy_pasteable(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["robot-docs", "guide", "--json"])
        self.assertEqual(code, PASS)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["schema_version"], 1)
        self.assertIn(
            "qg setup . --owner @your-org/quality --mode auto", payload["workflows"]["setup"]
        )
        self.assertIn("qg check-risk --keep-going", payload["workflows"]["high_assurance"])
        self.assertTrue(any("Do not weaken policy" in rule for rule in payload["safety_rules"]))

        human = io.StringIO()
        with contextlib.redirect_stdout(human):
            self.assertEqual(main(["robot-docs", "guide"]), PASS)
        self.assertIn("# AQG agent operating guide", human.getvalue())
        self.assertIn("`qg review --write --sarif`", human.getvalue())

    def test_triage_collapses_orientation_into_one_stable_payload(self) -> None:
        first_code, first, _ = self._json_command("triage")
        second_code, second, _ = self._json_command("triage")
        self.assertEqual(first_code, second_code)
        self.assertIn(first_code, {PASS, CONFIGURATION_ERROR})
        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], 1)
        self.assertEqual(first["project"]["name"], self.root.name)
        self.assertIn("summary", first["readiness"])
        self.assertIn("selected", first["risk"])
        self.assertIn("qg doctor", first["commands"])
        self.assertIn("qg check-risk --keep-going", first["commands"])


if __name__ == "__main__":
    unittest.main()
