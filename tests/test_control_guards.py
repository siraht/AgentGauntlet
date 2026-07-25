from __future__ import annotations

import contextlib
import curses
import io
import json
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from aqg import hooks, tui
from aqg.constants import CONFIGURATION_ERROR, PASS
from aqg.dashboard import DashboardServer
from aqg.scaffold import initialize_project


def _git(root: Path, *arguments: str) -> None:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise AssertionError(completed.stderr)


class ControlGuardCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="aqg-controls-")
        self.root = Path(self.temporary.name)
        _git(self.root, "init", "-q")
        _git(self.root, "config", "user.email", "aqg@example.invalid")
        _git(self.root, "config", "user.name", "AQG Controls")
        (self.root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        _git(self.root, "add", "app.py")
        _git(self.root, "commit", "-qm", "seed")
        initialize_project(self.root, owner="@quality", install=False, ci=False, mode="adopt")
        _git(self.root, "add", ".")
        _git(self.root, "commit", "-qm", "install AQG")

    def tearDown(self) -> None:
        self.temporary.cleanup()


class HookTests(ControlGuardCase):
    def _pretool(self, payload: object) -> tuple[int, str]:
        stderr = io.StringIO()
        with (
            mock.patch("sys.stdin", io.StringIO(json.dumps(payload))),
            contextlib.redirect_stderr(stderr),
        ):
            code = hooks.hook_pretool(self.root)
        return code, stderr.getvalue()

    def test_pretool_allows_source_reads_and_blocks_policy_writes(self) -> None:
        safe, safe_error = self._pretool(
            {"tool_name": "write", "tool_input": {"file_path": "src/app.py"}}
        )
        blocked, blocked_error = self._pretool(
            {"tool_name": "apply_patch", "tool_input": {"file_path": "quality/policy.toml"}}
        )
        shell, shell_error = self._pretool(
            {
                "tool_name": "shell",
                "tool_input": {"command": "printf changed > quality/policy.toml"},
            }
        )
        self.assertEqual((safe, safe_error), (PASS, ""))
        self.assertEqual(blocked, CONFIGURATION_ERROR)
        self.assertIn("protected policy path", blocked_error)
        self.assertEqual(shell, CONFIGURATION_ERROR)
        self.assertIn("may modify protected policy path", shell_error)

    def test_pretool_fails_invalid_json_and_honors_explicit_maintenance(self) -> None:
        stderr = io.StringIO()
        with (
            mock.patch("sys.stdin", io.StringIO("{")),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(hooks.hook_pretool(self.root), CONFIGURATION_ERROR)
        self.assertIn("invalid JSON", stderr.getvalue())

        with (
            mock.patch("sys.stdin", io.StringIO(json.dumps({"tool_name": "write"}))),
            mock.patch("aqg.hooks.policy_override_enabled", return_value=True),
        ):
            self.assertEqual(hooks.hook_pretool(self.root), PASS)

    def test_stop_hook_is_recursive_safe_and_fail_closed(self) -> None:
        disabled = {"hooks": {"enforce_on_stop": False}}
        active = {"hooks": {"enforce_on_stop": True, "stop_profile": "fast"}}
        with (
            mock.patch("sys.stdin", io.StringIO("{}")),
            mock.patch("aqg.hooks.load_policy", return_value=disabled),
        ):
            self.assertEqual(hooks.hook_stop(self.root), PASS)
        with (
            mock.patch("sys.stdin", io.StringIO('{"stop_hook_active": true}')),
            mock.patch("aqg.hooks.load_policy", return_value=active),
        ):
            self.assertEqual(hooks.hook_stop(self.root), PASS)

        stderr = io.StringIO()
        with (
            mock.patch("sys.stdin", io.StringIO("{}")),
            mock.patch("aqg.hooks.load_policy", return_value=active),
            mock.patch("aqg.hooks.run_profile", return_value=(1, {"status": "quality_failure"})),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(hooks.hook_stop(self.root), CONFIGURATION_ERROR)
        self.assertIn("is not green", stderr.getvalue())

    def test_hook_path_helpers_cover_patch_shell_and_outside_paths(self) -> None:
        patch = "*** Update File: quality/policy.toml\n--- a/src/old.py\n+++ b/src/new.py\n"
        self.assertEqual(
            hooks._patch_paths(patch),
            ["quality/policy.toml", "src/old.py", "src/new.py"],
        )
        self.assertIn(
            "quality/policy.toml",
            hooks._direct_write_paths("apply_patch", {"patch": patch}),
        )
        self.assertEqual(
            hooks._command_policy_writes(
                "echo ok", ["quality/policy.toml", ".github/workflows/**"]
            ),
            [],
        )
        self.assertEqual(hooks._normalize(self.root, str(self.root / "app.py")), "app.py")
        self.assertTrue(hooks._normalize(self.root, "/outside/file").endswith("outside/file"))


class FakeScreen:
    def __init__(self, keys: list[int] | None = None) -> None:
        self.keys = list(keys or [])
        self.writes: list[str] = []

    def getmaxyx(self) -> tuple[int, int]:
        return 40, 140

    def erase(self) -> None:
        return None

    def refresh(self) -> None:
        return None

    def addnstr(self, row: int, col: int, text: str, length: int, attr: int) -> None:
        del row, col, length, attr
        self.writes.append(text)

    def getch(self) -> int:
        return self.keys.pop(0)


class TuiTests(ControlGuardCase):
    def test_tui_draws_project_state_and_quits(self) -> None:
        screen = FakeScreen([ord("q")])
        with (
            mock.patch("aqg.tui.curses.curs_set"),
            mock.patch("aqg.tui.curses.use_default_colors"),
            mock.patch("aqg.tui.curses.init_pair"),
            mock.patch("aqg.tui.curses.color_pair", side_effect=lambda value: value),
        ):
            tui._run(screen, self.root)
        rendered = " ".join(screen.writes)
        self.assertIn("AQG", rendered)
        self.assertIn("[f] fast", rendered)

    def test_tui_falls_back_to_plain_text_when_curses_is_unavailable(self) -> None:
        stdout = io.StringIO()
        with (
            mock.patch("aqg.tui.curses.wrapper", side_effect=curses.error),
            contextlib.redirect_stdout(stdout),
        ):
            tui.run_tui(self.root)
        self.assertIn(f"AQG {self.root.name}", stdout.getvalue())

    def test_safe_add_clips_out_of_bounds_and_suppresses_terminal_errors(self) -> None:
        screen = FakeScreen()
        tui._safe_add(screen, -1, 0, "hidden")
        tui._safe_add(screen, 0, 999, "hidden")
        self.assertEqual(screen.writes, [])
        failing = mock.Mock()
        failing.getmaxyx.return_value = (10, 20)
        failing.addnstr.side_effect = curses.error
        tui._safe_add(failing, 1, 1, "ignored")


class DashboardHttpTests(ControlGuardCase):
    def _serve(self, *, allow_actions: bool, token: str) -> tuple[DashboardServer, str]:
        server = DashboardServer(
            ("127.0.0.1", 0),
            [self.root],
            allow_actions=allow_actions,
            token=token,
            verbose=False,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, f"http://127.0.0.1:{server.server_address[1]}"

    def test_dashboard_http_headers_errors_and_action_authentication(self) -> None:
        server, base = self._serve(allow_actions=False, token="")
        try:
            with urllib.request.urlopen(base + "/api/config") as response:
                self.assertEqual(response.status, 200)
                self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
                self.assertFalse(json.load(response)["actions_enabled"])
            request = urllib.request.Request(
                base + "/api/actions/review",
                data=b"{}",
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as blocked:
                urllib.request.urlopen(request)
            self.assertEqual(blocked.exception.code, 403)
            with self.assertRaises(urllib.error.HTTPError) as missing:
                urllib.request.urlopen(base + "/api/runs/not-present")
            self.assertEqual(missing.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()

        server, base = self._serve(allow_actions=True, token="secret")
        try:
            request = urllib.request.Request(
                base + "/api/actions/unknown",
                data=b"{}",
                headers={"X-AQG-Token": "secret"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as unknown:
                urllib.request.urlopen(request)
            self.assertEqual(unknown.exception.code, 404)
            invalid_json = urllib.request.Request(
                base + "/api/actions/review",
                data=b"{",
                headers={"X-AQG-Token": "secret"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as malformed:
                urllib.request.urlopen(invalid_json)
            self.assertEqual(malformed.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
