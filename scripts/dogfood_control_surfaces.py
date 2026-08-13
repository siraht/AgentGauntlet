#!/usr/bin/env python3
"""Exercise AQG's public setup, CLI, TUI, dashboard, review, and evidence surfaces."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pty
import re
import select
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
QG = ROOT / "qg"
EVIDENCE_TYPE = "aqg.functional-rehearsal"
SCHEMA_VERSION = 2


class DogfoodFailure(RuntimeError):
    """A public control surface violated its expected contract."""


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _timed(durations: dict[str, int], name: str, operation: Any) -> Any:
    started = time.monotonic_ns()
    try:
        return operation()
    finally:
        elapsed = time.monotonic_ns() - started
        durations[name] = max(0, round(elapsed / 1_000_000))


def _tree_files(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(root).parts
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )


def _file_manifest(root: Path, paths: list[Path]) -> dict[str, Any]:
    files = [
        {
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "executable": bool(path.stat().st_mode & stat.S_IXUSR),
            "sha256": _sha256(path.read_bytes()),
        }
        for path in paths
    ]
    return {"algorithm": "sha256", "digest": _sha256(_canonical(files)), "files": len(files)}


def _tree_manifest(root: Path) -> dict[str, Any]:
    return _file_manifest(root, _tree_files(root))


def _installation_manifest(root: Path) -> dict[str, Any]:
    managed = [root / "aqg", root / "quality" / "qg.py"]
    runtime = root / "quality" / "_aqg"
    if runtime.is_dir():
        managed.extend(_tree_files(runtime))
    paths = sorted((path for path in managed if path.is_file()), key=lambda path: path.as_posix())
    if not paths:
        raise DogfoodFailure("candidate installation did not contain a managed runtime")
    return _file_manifest(root, paths)


def _capture_tree(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        for path in _tree_files(root)
    }


def _write_tree(root: Path, snapshot: dict[str, tuple[bytes, int]]) -> None:
    root.mkdir(parents=True)
    for relative, (content, mode) in snapshot.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(mode)


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


def _git_output(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=root, text=True, capture_output=True, check=False
    )
    if completed.returncode:
        raise DogfoodFailure(completed.stderr)
    return completed.stdout.strip()


def _source_identity() -> dict[str, Any]:
    governed = [QG, Path(__file__).resolve()]
    governed.extend(
        path
        for path in (ROOT / "src" / "aqg").rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )
    materials = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": _sha256(path.read_bytes()),
        }
        for path in sorted(set(governed), key=lambda item: item.relative_to(ROOT).as_posix())
    ]
    changed = _git_output(
        ROOT,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--",
        "qg",
        "src/aqg",
        "scripts/dogfood_control_surfaces.py",
    )
    return {
        "revision": _git_output(ROOT, "rev-parse", "HEAD"),
        "dirty": bool(changed),
        "source_tree_sha256": _sha256(_canonical(materials)),
        "material_count": len(materials),
    }


def _identity_payload(payload: dict[str, Any]) -> dict[str, Any]:
    stable = dict(payload)
    stable.pop("result_identity", None)
    stable.pop("durations_ms", None)
    return stable


def _result_identity(payload: dict[str, Any]) -> str:
    return f"sha256:{_sha256(_canonical(_identity_payload(payload)))}"


def _exact_keys(value: dict[str, Any], expected: set[str], location: str) -> None:
    if set(value) != expected:
        raise DogfoodFailure(
            f"{location} keys differ: expected={sorted(expected)!r}, actual={sorted(value)!r}"
        )


def _validate_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise DogfoodFailure("functional evidence must be an object")
    _exact_keys(
        payload,
        {
            "schema_version",
            "evidence_type",
            "status",
            "candidate",
            "result_identity",
            "durations_ms",
            "cleanup",
            "cold_start",
            "setup",
            "functional_qa",
            "rollback",
            "cleanup_verified",
        },
        "evidence",
    )
    if payload["schema_version"] != SCHEMA_VERSION or payload["evidence_type"] != EVIDENCE_TYPE:
        raise DogfoodFailure("functional evidence schema identity is invalid")
    if payload["status"] != "pass":
        raise DogfoodFailure("a completed functional rehearsal must have pass status")
    _validate_candidate(payload["candidate"])
    _validate_durations(payload["durations_ms"])
    _validate_cleanup(payload["cleanup"])
    if payload["cleanup_verified"] is not True:
        raise DogfoodFailure("cleanup_verified must be true")
    _validate_functional_qa(payload["functional_qa"])
    evidence = payload["functional_qa"]["evidence"]
    if payload["cold_start"] != evidence["cold_start"] or payload["setup"] != evidence["setup"]:
        raise DogfoodFailure("top-level evidence aliases do not match functional QA evidence")
    _validate_rollback(payload["rollback"])
    if payload["result_identity"] != _result_identity(payload):
        raise DogfoodFailure("functional evidence result identity does not match its content")


def _validate_candidate(candidate: Any) -> None:
    if not isinstance(candidate, dict):
        raise DogfoodFailure("candidate must be an object")
    _exact_keys(
        candidate, {"revision", "dirty", "source_tree_sha256", "material_count"}, "candidate"
    )
    if not isinstance(candidate["revision"], str) or not re.fullmatch(
        r"[0-9a-f]{40,64}", candidate["revision"]
    ):
        raise DogfoodFailure("candidate revision is not a Git object identity")
    if not isinstance(candidate["dirty"], bool):
        raise DogfoodFailure("candidate dirty must be boolean")
    if not isinstance(candidate["source_tree_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", candidate["source_tree_sha256"]
    ):
        raise DogfoodFailure("candidate source tree digest is invalid")
    if not isinstance(candidate["material_count"], int) or candidate["material_count"] < 1:
        raise DogfoodFailure("candidate material count must be positive")


def _validate_durations(durations: Any) -> None:
    expected = {"total", "cold_start", "setup", "commands", "dashboard", "tui", "rollback"}
    if not isinstance(durations, dict):
        raise DogfoodFailure("durations_ms must be an object")
    _exact_keys(durations, expected, "durations_ms")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in durations.values()
    ):
        raise DogfoodFailure("durations_ms values must be non-negative integers")
    if any(durations["total"] < value for key, value in durations.items() if key != "total"):
        raise DogfoodFailure("total duration cannot be shorter than one of its phases")


def _validate_cleanup(cleanup: Any) -> None:
    if not isinstance(cleanup, dict):
        raise DogfoodFailure("cleanup must be an object")
    _exact_keys(cleanup, {"method", "temporary_workspace_removed"}, "cleanup")
    if cleanup != {"method": "TemporaryDirectory", "temporary_workspace_removed": True}:
        raise DogfoodFailure("disposable workspace cleanup was not verified")


def _validate_rollback(rollback: Any) -> None:
    expected = {
        "status",
        "mechanism",
        "before_identity",
        "candidate_identity",
        "restored_identity",
        "candidate_changed",
        "restored_matches_before",
        "operation_outputs_equal",
    }
    if not isinstance(rollback, dict):
        raise DogfoodFailure("rollback must be an object")
    _exact_keys(rollback, expected, "rollback")
    if rollback["status"] != "pass":
        raise DogfoodFailure("rollback status must be pass")
    if not isinstance(rollback["mechanism"], str) or not rollback["mechanism"].strip():
        raise DogfoodFailure("rollback mechanism must be a nonempty string")
    for key in ("before_identity", "candidate_identity", "restored_identity"):
        if not isinstance(rollback[key], str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", rollback[key]
        ):
            raise DogfoodFailure(f"rollback {key} is not a SHA-256 digest")
    if not all(
        rollback[key] is True
        for key in ("candidate_changed", "restored_matches_before", "operation_outputs_equal")
    ):
        raise DogfoodFailure("rollback did not prove a changed candidate and exact restoration")
    if rollback["before_identity"] != rollback["restored_identity"]:
        raise DogfoodFailure("rollback identity does not match the before identity")
    if rollback["candidate_identity"] == rollback["before_identity"]:
        raise DogfoodFailure("candidate identity does not demonstrate a changed installation")


def _validate_functional_qa(functional_qa: Any) -> None:
    if not isinstance(functional_qa, dict):
        raise DogfoodFailure("functional_qa must be an object")
    _exact_keys(functional_qa, {"status", "checks", "evidence"}, "functional_qa")
    if functional_qa["status"] != "pass":
        raise DogfoodFailure("functional QA status must be pass")
    checks = functional_qa["checks"]
    evidence = functional_qa["evidence"]
    if (
        not isinstance(checks, list)
        or not checks
        or any(not isinstance(item, str) for item in checks)
    ):
        raise DogfoodFailure("functional QA checks must be a nonempty string list")
    if len(checks) != len(set(checks)):
        raise DogfoodFailure("functional QA checks must be unique")
    if not isinstance(evidence, dict) or set(evidence) != set(checks):
        raise DogfoodFailure("functional QA evidence must match every named check")
    if any(not isinstance(item, dict) or not item for item in evidence.values()):
        raise DogfoodFailure("each functional QA check must contain nonempty evidence")


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


def _dashboard_start(
    project: Path, *, allow_actions: bool
) -> tuple[subprocess.Popen[str], str, str]:
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
    try:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


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
        status, _, _ = _request(url + "/api/actions/review", method="POST", payload={})
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


def _seed_project(project: Path) -> None:
    project.mkdir()
    _git(project, "init", "-q")
    _git(project, "config", "user.email", "aqg@example.invalid")
    _git(project, "config", "user.name", "AQG Dogfood")
    (project / "app.py").write_text(
        "import json\nprint(json.dumps({'value': 1}, sort_keys=True))\n", encoding="utf-8"
    )
    _git(project, "add", "app.py")
    _git(project, "commit", "-qm", "seed")


def _run_seed_operation(project: Path) -> str:
    completed = subprocess.run(
        [sys.executable, "app.py"],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    if completed.returncode or completed.stdout != '{"value": 1}\n':
        raise DogfoodFailure(
            f"seed application operation failed: exit={completed.returncode}, "
            f"stdout={completed.stdout!r}, stderr={completed.stderr!r}"
        )
    return completed.stdout


def _cold_start() -> dict[str, Any]:
    return {
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


def _install_candidate(project: Path) -> subprocess.CompletedProcess[str]:
    return _run(
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


def _exercise_commands(project: Path, setup: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    _git(project, "add", ".")
    _git(project, "commit", "-qm", "install AQG")
    status = _json(_run(["--root", str(project), "status", "--json"], cwd=project))
    doctor = _json(_run(["--root", str(project), "doctor", "--json"], cwd=project))
    triage_run = _run(["--root", str(project), "triage", "--json"], cwd=project, expected=(0, 2))
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
    conformance = _json(_run(["--root", str(project), "conformance", "--json"], cwd=project))
    return _command_result(setup, status, doctor, triage_run, triage, review, conformance)


def _command_result(
    setup: subprocess.CompletedProcess[str],
    status: dict[str, Any],
    doctor: dict[str, Any],
    triage_run: subprocess.CompletedProcess[str],
    triage: dict[str, Any],
    review: dict[str, Any],
    conformance: dict[str, Any],
) -> dict[str, Any]:
    review_packet = review.get("packet", review)
    return {
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
    }


def _rehearse_rollback(
    project: Path,
    snapshot: dict[str, tuple[bytes, int]],
    old_manifest: dict[str, Any],
    old_output: str,
) -> dict[str, Any]:
    candidate_manifest = _tree_manifest(project)
    installation_manifest = _installation_manifest(project)
    preserved = project.with_name("candidate-preserved")
    project.rename(preserved)
    _write_tree(project, snapshot)
    restored_output = _run_seed_operation(project)
    restored_manifest = _tree_manifest(project)
    result = {
        "status": "pass",
        "mechanism": "content-addressed-copy-into-fresh-root",
        "before_identity": f"sha256:{old_manifest['digest']}",
        "candidate_identity": f"sha256:{installation_manifest['digest']}",
        "restored_identity": f"sha256:{restored_manifest['digest']}",
        "candidate_changed": candidate_manifest["digest"] != old_manifest["digest"],
        "restored_matches_before": restored_manifest == old_manifest,
        "operation_outputs_equal": restored_output == old_output,
    }
    _validate_rollback(result)
    return result


def _exercise_workspace(workspace: Path, durations: dict[str, int]) -> dict[str, Any]:
    project = workspace / "project"
    _seed_project(project)
    old_output = _run_seed_operation(project)
    snapshot = _capture_tree(project)
    old_manifest = _tree_manifest(project)
    cold = _timed(durations, "cold_start", _cold_start)
    setup = _timed(durations, "setup", lambda: _install_candidate(project))
    commands = _timed(durations, "commands", lambda: _exercise_commands(project, setup))
    dashboard = _timed(durations, "dashboard", lambda: _dogfood_dashboard(project))
    tui = _timed(durations, "tui", lambda: _dogfood_tui(project))
    rollback = _timed(
        durations,
        "rollback",
        lambda: _rehearse_rollback(project, snapshot, old_manifest, old_output),
    )
    return {
        "cold_start": cold,
        "setup": commands["setup"],
        "functional_qa": _functional_qa(cold, commands, dashboard, tui),
        "rollback": rollback,
    }


def _functional_qa(
    cold: dict[str, Any],
    commands: dict[str, Any],
    dashboard: dict[str, Any],
    tui: dict[str, Any],
) -> dict[str, Any]:
    evidence = {
        "cold_start": cold,
        "setup": commands["setup"],
        "review": commands["review"],
        "conformance": commands["conformance"],
        "dashboard": dashboard,
        "tui": tui,
    }
    return {"status": "pass", "checks": list(evidence), "evidence": evidence}


def dogfood() -> dict[str, Any]:
    durations: dict[str, int] = {}
    started = time.monotonic_ns()
    temporary = tempfile.TemporaryDirectory(prefix="aqg-control-dogfood-")
    workspace = Path(temporary.name)
    try:
        result = _exercise_workspace(workspace, durations)
    finally:
        temporary.cleanup()
    durations["total"] = max(0, round((time.monotonic_ns() - started) / 1_000_000))
    cleanup = {
        "method": "TemporaryDirectory",
        "temporary_workspace_removed": not workspace.exists(),
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": EVIDENCE_TYPE,
        "status": "pass",
        "candidate": _source_identity(),
        "result_identity": "",
        "durations_ms": durations,
        "cleanup": cleanup,
        "cleanup_verified": cleanup["temporary_workspace_removed"],
        **result,
    }
    payload["result_identity"] = _result_identity(payload)
    _validate_payload(payload)
    return payload


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
