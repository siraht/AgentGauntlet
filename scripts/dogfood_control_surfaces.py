#!/usr/bin/env python3
"""Exercise AQG's public setup, CLI, TUI, dashboard, review, and evidence surfaces."""

from __future__ import annotations

import argparse
import json
import os
import pty
import re
import select
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
QG = ROOT / "qg"


class DogfoodFailure(RuntimeError):
    """A public control surface violated its expected contract."""


def _run(
    arguments: list[str],
    *,
    cwd: Path,
    expected: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [str(QG), *arguments],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if completed.returncode not in expected:
        raise DogfoodFailure(
            f"{' '.join(arguments)} exited {completed.returncode}; "
            f"stdout={completed.stdout[-1000:]!r}; stderr={completed.stderr[-1000:]!r}"
        )
    return completed


def _json(completed: subprocess.CompletedProcess[str]) -> Any:
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise DogfoodFailure(f"invalid JSON from {completed.args}: {exc}") from exc


def _git(root: Path, *arguments: str) -> None:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise DogfoodFailure(completed.stderr)


def _request(
    url: str,
    *,
    method: str = "GET",
    token: str | None = None,
    payload: dict[str, Any] | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if token is not None:
        headers["X-AQG-Token"] = token
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def _dashboard_start(project: Path, *, allow_actions: bool) -> tuple[subprocess.Popen[str], str, str]:
    arguments = [str(QG), "--root", str(project), "dashboard", "--port", "0"]
    if allow_actions:
        arguments.append("--allow-actions")
    environment = {**os.environ, "PYTHONUNBUFFERED": "1"}
    process = subprocess.Popen(
        arguments,
        cwd=project,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    lines: list[str] = []
    deadline = time.monotonic() + 10
    while not lines and time.monotonic() < deadline:
        ready, _, _ = select.select([process.stdout], [], [], 0.25)
        if ready:
            line = process.stdout.readline()
            if line:
                lines.append(line.strip())
        if process.poll() is not None:
            break
    if lines:
        second = process.stdout.readline()
        if second:
            lines.append(second.strip())
    output = "\n".join(lines)
    match = re.search(r"AQG dashboard: (http://\S+)", output)
    if not match:
        stderr = process.stderr.read() if process.stderr is not None else ""
        process.kill()
        raise DogfoodFailure(f"dashboard did not announce its URL: {output!r} {stderr!r}")
    token_match = re.search(r"Browser token: (\S+)", output)
    return process, match.group(1), token_match.group(1) if token_match else ""


def _dashboard_stop(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=5)


def _dogfood_dashboard(project: Path) -> dict[str, Any]:
    checks: list[str] = []
    process, url, _ = _dashboard_start(project, allow_actions=False)
    try:
        for path in ("/", "/api/status", "/api/config", "/api/review"):
            status, body, headers = _request(url + path)
            if status != 200 or "Content-Security-Policy" not in headers:
                raise DogfoodFailure(f"read-only dashboard {path} returned {status}")
            if path.startswith("/api/"):
                json.loads(body)
            checks.append(f"GET {path}=200")
        status, _, _ = _request(
            url + "/api/actions/review", method="POST", payload={}
        )
        if status != 403:
            raise DogfoodFailure(f"disabled dashboard action returned {status}")
        checks.append("disabled POST=403")
    finally:
        _dashboard_stop(process)

    process, url, token = _dashboard_start(project, allow_actions=True)
    try:
        invalid, _, _ = _request(
            url + "/api/actions/review", method="POST", token="invalid", payload={}
        )
        accepted, body, _ = _request(
            url + "/api/actions/review", method="POST", token=token, payload={}
        )
        unknown, _, _ = _request(
            url + "/api/actions/unknown", method="POST", token=token, payload={}
        )
        if invalid != 403 or accepted != 200 or unknown != 404:
            raise DogfoodFailure(
                f"dashboard action contract invalid: {invalid=}, {accepted=}, {unknown=}"
            )
        packet = json.loads(body)
        if "artifacts" not in packet:
            raise DogfoodFailure("authenticated review action did not write artifacts")
        checks.extend(["invalid token=403", "review action=200", "unknown action=404"])
    finally:
        _dashboard_stop(process)
    return {"url_mode": "ephemeral-loopback", "checks": checks}


def _dogfood_tui(project: Path) -> dict[str, Any]:
    master, slave = pty.openpty()
    environment = {**os.environ, "TERM": "xterm", "NO_COLOR": "1"}
    process = subprocess.Popen(
        [str(QG), "--root", str(project), "tui"],
        cwd=project,
        env=environment,
        stdin=slave,
        stdout=slave,
        stderr=slave,
    )
    os.close(slave)
    output = bytearray()
    try:
        time.sleep(0.75)
        os.write(master, b"q")
        process.wait(timeout=10)
        while True:
            ready, _, _ = select.select([master], [], [], 0)
            if not ready:
                break
            try:
                output.extend(os.read(master, 65536))
            except OSError:
                break
    finally:
        os.close(master)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
    if process.returncode != 0 or b"AQG" not in output:
        raise DogfoodFailure(f"TUI failed: exit={process.returncode}, bytes={len(output)}")
    return {"exit_code": process.returncode, "output_bytes": len(output)}


def dogfood() -> dict[str, Any]:
    cold = {
        "bare_help": _run([], cwd=Path("/tmp")).returncode,
        "capabilities": _json(_run(["--json"], cwd=Path("/tmp")))["contract_version"],
        "guidance_results": len(
            _json(
                _run(
                    ["guidance", "mutation", "testing", "--json"],
                    cwd=Path("/tmp"),
                )
            )
        ),
    }
    with tempfile.TemporaryDirectory(prefix="aqg-control-dogfood-") as temporary:
        project = Path(temporary)
        _git(project, "init", "-q")
        _git(project, "config", "user.email", "aqg@example.invalid")
        _git(project, "config", "user.name", "AQG Dogfood")
        (project / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        _git(project, "add", "app.py")
        _git(project, "commit", "-qm", "seed")
        setup = _run(
            [
                "setup",
                str(project),
                "--owner",
                "@quality",
                "--mode",
                "adopt",
                "--no-install",
                "--no-ci",
                "--no-verify",
            ],
            cwd=project,
        )
        _git(project, "add", ".")
        _git(project, "commit", "-qm", "install AQG")
        status = _json(_run(["--root", str(project), "status", "--json"], cwd=project))
        doctor = _json(_run(["--root", str(project), "doctor", "--json"], cwd=project))
        triage_run = _run(
            ["--root", str(project), "triage", "--json"],
            cwd=project,
            expected=(0, 2),
        )
        triage = _json(triage_run)
        review = _json(
            _run(
                [
                    "--root",
                    str(project),
                    "review",
                    "--no-evidence",
                    "--write",
                    "--sarif",
                    "--json",
                ],
                cwd=project,
                expected=(0, 1),
            )
        )
        conformance = _json(
            _run(["--root", str(project), "conformance", "--json"], cwd=project)
        )
        dashboard = _dogfood_dashboard(project)
        tui = _dogfood_tui(project)
        review_packet = review.get("packet", review)
        return {
            "schema_version": 1,
            "status": "pass",
            "cold_start": cold,
            "setup": {
                "exit_code": setup.returncode,
                "project": status["project"]["name"],
                "doctor_errors": doctor["counts"]["error"],
                "triage_exit": triage_run.returncode,
                "triage_blockers": triage["readiness"]["summary"]["blockers"],
            },
            "review": {
                "findings": len(review_packet["findings"]),
                "artifacts": sorted(review.get("artifacts", {})),
            },
            "conformance": conformance["internal"]["summary"],
            "dashboard": dashboard,
            "tui": tui,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = dogfood()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
