"""Guided repository onboarding for users who do not want to edit configuration by hand."""

from __future__ import annotations

import getpass
from pathlib import Path
from typing import Callable, Any

from .constants import CONFIGURATION_ERROR, PASS, QUALITY_FAILURE
from .conformance import run_conformance
from .detect import detect_project
from .doctor import diagnose
from .scaffold import initialize_project


def _ask(prompt: str, default: str, input_fn: Callable[[str], str]) -> str:
    value = input_fn(f"{prompt} [{default}]: ").strip()
    return value or default


def _yes(prompt: str, default: bool, input_fn: Callable[[str], str]) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input_fn(f"{prompt} [{suffix}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes", "1", "true"}


def run_wizard(path: Path, *, input_fn: Callable[[str], str] = input, output: Callable[[str], None] = print) -> tuple[int, dict[str, Any]]:
    root = path.expanduser().resolve()
    detection = detect_project(root)
    enabled = [name for name, value in {
        "JavaScript": detection.javascript,
        "TypeScript": detection.typescript,
        "Python": detection.python,
        "HTML": detection.html,
        "CSS": detection.css,
    }.items() if value]
    output("Agent Quality Gauntlet guided setup")
    output(f"Repository: {root}")
    output("Detected: " + (", ".join(enabled) if enabled else "no supported stack yet"))
    if detection.frameworks:
        output("Frameworks: " + ", ".join(detection.frameworks))
    for note in detection.notes:
        output(f"Note: {note}")

    mode = _ask("Adoption mode (adopt preserves legacy debt; greenfield enforces the full tree)", "adopt", input_fn).lower()
    while mode not in {"adopt", "greenfield"}:
        output("Choose adopt or greenfield.")
        mode = _ask("Adoption mode", "adopt", input_fn).lower()
    owner = _ask("GitHub CODEOWNER user or team", getpass.getuser(), input_fn)
    install = _yes("Install isolated, locked checker toolchains now", True, input_fn)
    ci = _yes("Generate protected GitHub Actions and CODEOWNERS files", True, input_fn)
    register = _yes("Register this repository in the local portfolio dashboard", False, input_fn)
    base_url: str | None = None
    start_command: str | None = None
    if detection.html or detection.css or detection.frameworks:
        inferred_url = "http://127.0.0.1:5173" if "vite" in detection.frameworks else "http://127.0.0.1:3000"
        base_url = _ask("Local web URL used by browser and performance checks", inferred_url, input_fn)
        inferred_start = " ".join(detection.start_command or [])
        if inferred_start:
            start_command = _ask("Web start command", inferred_start, input_fn)

    result = initialize_project(
        root,
        owner=owner,
        install=install,
        ci=ci,
        base_url=base_url,
        start_command=start_command,
        mode=mode,
    )
    if register:
        from .portfolio import add_project

        result["portfolio"] = add_project(root)
    doctor = diagnose(root, strict_tools=install)
    _, conformance = run_conformance(root, tools=install)
    result["doctor"] = doctor
    result["conformance"] = conformance

    output("")
    output(f"Setup complete: {root}")
    output(f"Doctor: {doctor['status']} · {doctor['counts']['error']} error(s), {doctor['counts']['warning']} warning(s)")
    internal = conformance["internal"]["summary"]
    output(f"AQG self-conformance: {internal['passed']}/{internal['total']} cases passed")
    output("Open quality/onboarding.json next; it lists the remaining product-specific tests and behavior contracts in plain language.")
    output("Control surface: python3 quality/qg.py dashboard --open")
    output("Terminal surface: python3 quality/qg.py tui")

    if doctor["counts"]["error"]:
        return CONFIGURATION_ERROR, result
    if conformance["status"] != "pass":
        return QUALITY_FAILURE, result
    return PASS, result
