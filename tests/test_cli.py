from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from argparse import _SubParsersAction
from pathlib import Path
from unittest.mock import patch

from aqg.cli import COMMAND_HANDLERS, _triage_payload, build_parser, main
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
            (("guidance", "mutation", "testing"), {PASS}),
            (("onboarding", "show"), {PASS, CONFIGURATION_ERROR}),
            (("onboarding", "next"), {PASS, CONFIGURATION_ERROR}),
            (("acceptance", "lint"), {PASS}),
            (("golden",), {CONFIGURATION_ERROR}),
            (("conformance",), {PASS}),
            (("promote", "status"), {PASS}),
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

    def test_authoritative_commands_reject_active_update_overrides(self) -> None:
        cases = (
            ("AQG_POLICY_MAINTENANCE", ("doctor",)),
            ("AQG_POLICY_MAINTENANCE", ("check", "fast")),
            ("AQG_ALLOW_GOLDEN_UPDATE", ("audit", "shadow")),
            ("AQG_ALLOW_GOLDEN_UPDATE", ("gate", "format")),
        )
        for variable, command in cases:
            with self.subTest(variable=variable, command=command):
                with patch.dict(os.environ, {variable: "1"}, clear=False):
                    code, payload, _ = self._json_command(*command)
                self.assertEqual(code, CONFIGURATION_ERROR)
                self.assertIn("refuses active", payload["error"]["message"])
                self.assertIn(variable, payload["error"]["message"])

    def test_maintenance_request_cli_is_scoped_and_non_authorizing(self) -> None:
        code, payload, stderr = self._json_command(
            "maintenance",
            "request",
            "--change",
            "modify:quality/policy.toml",
            "--reason",
            "Prepare a code-owner-reviewed policy update",
            "--requester",
            "builder@example.test",
        )
        self.assertEqual(code, PASS, stderr)
        self.assertEqual(payload["request"]["authority"], "none")
        self.assertEqual(
            payload["request"]["authorized_changes"],
            [{"operation": "modify", "path": "quality/policy.toml"}],
        )
        self.assertFalse((self.root / "quality" / "approvals" / "policy-maintenance.json").exists())

    def test_check_risk_can_run_every_selected_profile_in_shadow_mode(self) -> None:
        risk = {
            "required_execution_profiles": ["fast", "deep"],
            "selected_risk_profile": "high_assurance",
        }
        summaries = [
            {"profile": "fast", "mode": "shadow"},
            {"profile": "deep", "mode": "shadow"},
        ]
        with (
            patch("aqg.cli.risk_summary", return_value=([], risk)),
            patch(
                "aqg.cli.run_profile",
                side_effect=[(PASS, summaries[0]), (PASS, summaries[1])],
            ) as run,
        ):
            code, payload, stderr = self._json_command("check-risk", "--shadow", "--keep-going")

        self.assertEqual(code, PASS, stderr)
        self.assertEqual(payload["runs"], summaries)
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertTrue(call.kwargs["shadow"])
            self.assertTrue(call.kwargs["keep_going"])

    def test_debt_review_requires_explicit_human_confirmation(self) -> None:
        code, payload, _ = self._json_command(
            "baseline",
            "debt",
            "review",
            "--proposal",
            "debt-example",
            "--reviewer",
            "owner@example.test",
        )
        self.assertEqual(code, CONFIGURATION_ERROR)
        self.assertIn("--confirm-reviewed", payload["error"]["message"])

    def test_global_flags_work_after_the_subcommand(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["status", "--root", str(self.root), "--json"])
        self.assertEqual(code, PASS)
        self.assertEqual(json.loads(stdout.getvalue())["project"]["name"], self.root.name)

    def test_manual_gate_run_id_is_a_safe_single_path_component(self) -> None:
        evidence = {
            "status": "pass",
            "stdout": "",
            "stderr": "",
        }
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with (
                patch("aqg.cli.utc_now", return_value="2026-07-28T00:41:31+00:00"),
                patch("aqg.cli.uuid.uuid4") as uuid4,
                patch("aqg.cli.run_gate", return_value=(PASS, evidence)) as run,
            ):
                uuid4.return_value.hex = "12345678deadbeef"
                code = main(["--root", str(self.root), "gate", "format"])
        self.assertEqual(code, PASS)
        self.assertEqual(stdout.getvalue(), "format: pass\n")
        self.assertEqual(run.call_args.args[0], self.root)
        self.assertIsInstance(run.call_args.args[1], dict)
        self.assertEqual(run.call_args.args[2], "format")
        self.assertEqual(run.call_args.args[3], "manual-2026-07-28T004131Z-12345678")

    def test_manual_gate_honors_explicit_run_id_and_json_output(self) -> None:
        evidence = {"status": "pass", "stdout": "", "stderr": "", "gate": "format"}
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with (
                patch.dict(os.environ, {"AQG_RUN_ID": "caller-owned-run"}),
                patch("aqg.cli.uuid.uuid4") as uuid4,
                patch("aqg.cli.run_gate", return_value=(PASS, evidence)) as run,
            ):
                code = main(["--root", str(self.root), "gate", "format", "--json"])

        self.assertEqual(code, PASS)
        self.assertEqual(json.loads(stdout.getvalue()), evidence)
        self.assertEqual(run.call_args.args[3], "caller-owned-run")
        uuid4.assert_not_called()

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

    def test_bare_invocation_teaches_humans_and_json_describes_the_contract(self) -> None:
        human = io.StringIO()
        with contextlib.redirect_stdout(human):
            self.assertEqual(main([]), PASS)
        self.assertIn("Constraint-first quality control", human.getvalue())
        self.assertRegex(
            human.getvalue(),
            r"capabilities\s+describe the machine-readable",
        )

        machine = io.StringIO()
        with contextlib.redirect_stdout(machine):
            self.assertEqual(main(["--json"]), PASS)
        payload = json.loads(machine.getvalue())
        self.assertEqual(payload["contract_version"], "1.0")
        self.assertIn("commands", payload)

    def test_parse_errors_teach_exact_safe_corrections(self) -> None:
        cases = (
            (["--jsno"], "qg capabilities --json"),
            (["--baes-url"], "qg detect --base-url BASE_URL"),
            (["--browers"], "qg init --browsers"),
            (["--verion"], "qg --version"),
            (["capabilities", "--jsno"], "qg capabilities --json"),
            (["test"], "qg check fast"),
            (["verify"], "qg check-risk --keep-going"),
            (["health"], "qg doctor"),
            (["docs"], "qg robot-docs guide"),
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

    def test_natural_multiword_guidance_is_treated_as_a_search(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["guidance", "mutation", "testing", "--json"])
        self.assertEqual(code, PASS)
        payload = json.loads(stdout.getvalue())
        self.assertIsInstance(payload, list)
        self.assertTrue(payload)

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
        # AQG-OWNER-001: CLI triage projects the shared owner-status model.
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
        self.assertEqual(first["owner_status"]["schema_version"], 1)
        self.assertNotIn("generated_at", first["owner_status"])
        self.assertNotIn("generated_at", first["owner_status"]["onboarding"]["current"])
        self.assertIn("merge", first["owner_status"]["decisions"])
        self.assertEqual(set(first["project"]), {"name", "stacks", "enforcement"})
        self.assertEqual(set(first["readiness"]), {"summary", "stale", "next_action"})
        self.assertEqual(
            set(first["risk"]),
            {"selected", "minimum", "required_execution_profiles", "errors"},
        )
        self.assertIn("latest", first)

    def test_triage_requests_only_the_latest_run(self) -> None:
        runs = [{"run_id": "first"}, {"run_id": "second"}]

        with patch("aqg.cli.list_runs", return_value=runs) as list_runs:
            payload = _triage_payload(self.root)

        list_runs.assert_called_once_with(self.root, 1)
        self.assertEqual(payload["latest"], runs[0])

    def test_status_exposes_the_shared_owner_decision_without_changing_legacy_fields(self) -> None:
        """AQG-OWNER-001/002: status retains its legacy data and adds owner decisions."""
        code, payload, stderr = self._json_command("status")
        self.assertEqual(code, PASS, stderr)
        self.assertEqual(payload["project"]["name"], self.root.name)
        self.assertEqual(payload["owner_status"]["schema_version"], 1)
        self.assertIn(
            payload["owner_status"]["decisions"]["develop"]["state"], {"allowed", "blocked"}
        )

    def test_help_accepts_conventional_and_nested_command_ordering(self) -> None:
        human = io.StringIO()
        with contextlib.redirect_stdout(human):
            self.assertEqual(main(["help", "onboarding", "refresh"]), PASS)
        self.assertIn("usage: qg onboarding refresh", human.getvalue())

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["help", "check", "--json"]), PASS)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["path"], ["check"])
        self.assertIn("{inner,fast,pr,deep,release}", payload["help"])

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(
                main(["help", "onbording", "refresh"]),
                CONFIGURATION_ERROR,
            )
        self.assertIn("qg help onboarding refresh", stderr.getvalue())

    def test_council_doctor_is_routed_as_advisory_json(self) -> None:
        report = {
            "schema_version": 1,
            "kind": "aqg-council-doctor",
            "advisory_only": True,
            "banner": "AGENT ADVISORY — NOT AN APPROVAL OR RELEASE AUTHORITY",
            "status": "ready",
            "missing_tools": [],
            "tools": {},
            "models": {"smoke": [], "pr": [], "high": []},
        }
        with patch("aqg.cli.council_doctor", return_value=report):
            code, payload, stderr = self._json_command("council", "doctor")
        self.assertEqual(code, PASS, stderr)
        self.assertEqual(payload, report)
        self.assertTrue(payload["advisory_only"])

    def test_council_plan_routes_explicit_data_classification(self) -> None:
        report = {
            "schema_version": 1,
            "kind": "aqg-council-plan",
            "advisory_only": True,
            "banner": "AGENT ADVISORY — NOT AN APPROVAL OR RELEASE AUTHORITY",
            "tier": "pr",
            "members": [],
            "bundle_bytes": 1,
            "max_bundle_bytes": 100,
        }
        with patch("aqg.cli.plan_council", return_value=report) as plan:
            code, payload, stderr = self._json_command(
                "council",
                "plan",
                "--tier",
                "pr",
                "--data-classification",
                "public",
            )
        self.assertEqual(code, PASS, stderr)
        self.assertEqual(payload, report)
        self.assertEqual(plan.call_args.args[-1], "public")

    def test_council_run_routes_classification_and_returns_advisory_code(self) -> None:
        report = {
            "schema_version": 1,
            "kind": "aqg-council-report",
            "advisory_only": True,
            "banner": "AGENT ADVISORY — NOT AN APPROVAL OR RELEASE AUTHORITY",
            "run_id": "council-test",
            "status": "advisory_concerns",
        }
        with patch("aqg.cli.run_council", return_value=(QUALITY_FAILURE, report)) as run:
            code, payload, stderr = self._json_command(
                "council",
                "run",
                "--tier",
                "pr",
                "--data-classification",
                "public",
            )
        self.assertEqual(code, QUALITY_FAILURE, stderr)
        self.assertEqual(payload, report)
        self.assertEqual(run.call_args.kwargs["data_classification"], "public")

    def test_council_verify_and_report_are_routed(self) -> None:
        verification = {
            "schema_version": 1,
            "kind": "aqg-council-verification",
            "advisory_only": True,
            "banner": "AGENT ADVISORY — NOT AN APPROVAL OR RELEASE AUTHORITY",
            "run_id": "council-test",
            "ok": False,
            "errors": ["tampered"],
        }
        with patch("aqg.cli.verify_council_run", return_value=verification):
            code, payload, stderr = self._json_command(
                "council", "verify", "--run-id", "council-test"
            )
        self.assertEqual(code, CONFIGURATION_ERROR, stderr)
        self.assertEqual(payload, verification)

        report = {
            "schema_version": 1,
            "kind": "aqg-council-report",
            "advisory_only": True,
            "banner": "AGENT ADVISORY — NOT AN APPROVAL OR RELEASE AUTHORITY",
            "run_id": "council-test",
            "status": "advisory_clear",
        }
        with patch("aqg.cli.report_council", return_value=report):
            code, payload, stderr = self._json_command(
                "council", "report", "--run-id", "council-test"
            )
        self.assertEqual(code, PASS, stderr)
        self.assertEqual(payload, report)


if __name__ == "__main__":
    unittest.main()
