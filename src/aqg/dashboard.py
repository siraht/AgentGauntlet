"""Dependency-free local dashboard and JSON control API."""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .constants import PASS
from .errors import ConfigurationError
from .owner_status import build_owner_status
from .policy import load_policy, risk_summary
from .project import load_project
from .review import analyze_review, write_review_packet
from .runner import run_profile
from .util import read_json

STATIC_ROOT = Path(__file__).resolve().parent / "static"


def project_status(root: Path) -> dict[str, Any]:
    owner_status = build_owner_status(root)
    payload = {
        **{
            key: owner_status[key]
            for key in (
                "generated_at",
                "root",
                "project",
                "profiles",
                "risk_profiles",
                "risk",
                "risk_errors",
                "approvals",
                "onboarding",
                "latest",
                "runs",
                "review",
            )
        },
        "owner_status": owner_status,
    }
    payload["runs"] = owner_status["runs"][:25]
    return payload


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "AQGDashboard/2"

    @property
    def aqg_server(self) -> DashboardServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, format: str, *args: object) -> None:
        if self.aqg_server.verbose:
            super().log_message(format, *args)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        )

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, indent=2, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path) -> None:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self._security_headers()
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        payload: Any
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/api/status":
            self._send_json(self.aqg_server.status_payload())
            return
        if path == "/api/review":
            payload = self.aqg_server.review_payload(write=False)
            self._send_json(payload)
            return
        if path.startswith("/api/runs/"):
            run_id = path.rsplit("/", 1)[-1]
            payload = self.aqg_server.run_payload(run_id)
            if payload is None:
                self._send_json({"error": "run not found"}, HTTPStatus.NOT_FOUND)
            else:
                self._send_json(payload)
            return
        if path == "/api/config":
            self._send_json(
                {
                    "actions_enabled": self.aqg_server.allow_actions,
                    "portfolio": self.aqg_server.portfolio,
                }
            )
            return
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        if ".." in Path(relative).parts:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        self._send_file(STATIC_ROOT / relative)

    def do_POST(self) -> None:  # noqa: N802
        if not self.aqg_server.allow_actions:
            self._send_json({"error": "dashboard actions are disabled"}, HTTPStatus.FORBIDDEN)
            return
        if self.headers.get("X-AQG-Token") != self.aqg_server.token:
            self._send_json({"error": "invalid action token"}, HTTPStatus.FORBIDDEN)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 65536:
            self._send_json(
                {"error": "request body too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE
            )
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json({"error": "invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/actions/check":
            profile = str(body.get("profile", "fast"))
            if profile == "risk":
                thread = threading.Thread(target=self.aqg_server.run_risk_check, daemon=True)
            else:
                thread = threading.Thread(
                    target=self.aqg_server.run_check, args=(profile,), daemon=True
                )
            thread.start()
            self._send_json({"accepted": True, "profile": profile}, HTTPStatus.ACCEPTED)
            return
        if self.path == "/api/actions/review":
            self._send_json(self.aqg_server.review_payload(write=True))
            return
        self._send_json({"error": "unknown action"}, HTTPStatus.NOT_FOUND)


class DashboardServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        roots: list[Path],
        *,
        allow_actions: bool,
        token: str,
        verbose: bool = False,
    ) -> None:
        super().__init__(address, DashboardHandler)
        self.roots = roots
        self.allow_actions = allow_actions and len(roots) == 1
        self.token = token
        self.verbose = verbose
        self.portfolio = len(roots) > 1
        self.active_actions: dict[str, str] = {}

    def status_payload(self) -> dict[str, Any]:
        projects: list[dict[str, Any]] = []
        for root in self.roots:
            try:
                projects.append(project_status(root))
            except Exception as exc:
                projects.append({"root": str(root), "error": str(exc)})
        return {"portfolio": self.portfolio, "projects": projects, "actions": self.active_actions}

    def review_payload(self, *, write: bool) -> dict[str, Any]:
        if self.portfolio:
            return {"error": "select a project; portfolio review aggregation is read-only"}
        root = self.roots[0]
        project = load_project(root)
        base = os.environ.get("AQG_DIFF_BASE") or str(
            project.get("enforcement", {}).get("base_ref", "HEAD")
        )
        packet = analyze_review(root, load_policy(root), base=base, require_evidence=True)
        if write:
            packet["artifacts"] = write_review_packet(root, packet)
        return packet

    def run_payload(self, run_id: str) -> dict[str, Any] | None:
        for root in self.roots:
            run_dir = root / ".aqg" / "runs" / run_id
            summary = run_dir / "summary.json"
            if not summary.exists():
                continue
            gates: dict[str, Any] = {}
            for path in (
                sorted((run_dir / "gates").glob("*.json")) if (run_dir / "gates").exists() else []
            ):
                gates[path.stem] = read_json(path)
            return {"root": str(root), "summary": read_json(summary), "gates": gates}
        return None

    def run_check(self, profile: str) -> None:
        if self.portfolio:
            self.active_actions[profile] = "portfolio actions are disabled"
            return
        root = self.roots[0]
        policy = load_policy(root)
        if profile not in policy.get("profiles", {}):
            self.active_actions[profile] = "error: unknown profile"
            return
        if self.active_actions.get(profile) == "running":
            return
        self.active_actions[profile] = "running"
        try:
            _, summary = run_profile(root, policy, profile, keep_going=True, quiet=True)
            self.active_actions[profile] = summary["status"]
        except Exception as exc:
            self.active_actions[profile] = f"error: {exc}"

    def run_risk_check(self) -> None:
        key = "risk"
        if self.portfolio:
            self.active_actions[key] = "portfolio actions are disabled"
            return
        if self.active_actions.get(key) == "running":
            return
        root = self.roots[0]
        policy = load_policy(root)
        self.active_actions[key] = "running"
        try:
            errors, risk = risk_summary(root, policy, "quality/change-risk.json")
            if errors:
                self.active_actions[key] = "configuration_error: " + "; ".join(errors[:2])
                return
            final = PASS
            for profile in risk.get("required_execution_profiles", []):
                code, _ = run_profile(root, policy, str(profile), keep_going=True, quiet=True)
                final = max(final, code)
            self.active_actions[key] = {
                0: "pass",
                1: "quality_failure",
                2: "configuration_error",
                3: "infrastructure_error",
            }.get(final, "error")
        except Exception as exc:
            self.active_actions[key] = f"error: {exc}"


def serve_dashboard(
    roots: list[Path],
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
    allow_actions: bool = False,
    verbose: bool = False,
) -> None:
    if allow_actions and host not in {"127.0.0.1", "localhost", "::1"}:
        raise ConfigurationError(
            "dashboard actions may bind only to a loopback address; use read-only mode for remote dashboards"
        )
    effective_actions = allow_actions and len(roots) == 1
    token = secrets.token_urlsafe(24) if effective_actions else ""
    server = DashboardServer(
        (host, port), roots, allow_actions=effective_actions, token=token, verbose=verbose
    )
    url = f"http://{host}:{server.server_address[1]}"
    print(f"AQG dashboard: {url}")
    print(
        "Read-only mode." if not effective_actions else f"Actions enabled. Browser token: {token}"
    )
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
