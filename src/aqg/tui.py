"""Curses control surface for terminal-first operation."""

from __future__ import annotations

import contextlib
import curses
import os
import textwrap
from pathlib import Path
from typing import Any

from .conformance import run_conformance
from .policy import load_policy, risk_summary
from .project import load_project
from .review import analyze_review, write_review_packet
from .runner import list_runs, run_profile
from .scaffold import current_onboarding, refresh_onboarding
from .util import human_duration


def _safe_add(stdscr: Any, row: int, col: int, text: str, attr: int = 0) -> None:
    height, width = stdscr.getmaxyx()
    if row < 0 or row >= height or col >= width:
        return
    with contextlib.suppress(curses.error):
        stdscr.addnstr(row, col, text, max(0, width - col - 1), attr)


def _color(status: str) -> int:
    mapping = {
        "pass": curses.color_pair(2),
        "quality_failure": curses.color_pair(3),
        "configuration_error": curses.color_pair(3),
        "infrastructure_error": curses.color_pair(3),
        "blocker": curses.color_pair(3),
        "review": curses.color_pair(4),
    }
    return mapping.get(status, curses.color_pair(1))


def _draw(stdscr: Any, root: Path, message: str = "") -> None:
    stdscr.erase()
    project = load_project(root)
    runs = list_runs(root, 20)
    latest = runs[0] if runs else None
    policy = load_policy(root)
    risk_errors, risk = risk_summary(root, policy, "quality/change-risk.json")
    onboarding_bundle = current_onboarding(root)
    onboarding = onboarding_bundle["current"]
    try:
        base = os.environ.get("AQG_DIFF_BASE") or str(
            project.get("enforcement", {}).get("base_ref", "HEAD")
        )
        review = analyze_review(root, policy, base=base, require_evidence=True)
    except Exception as exc:
        review = {
            "summary": {"blockers": 1, "human_review": 0},
            "findings": [{"severity": "blocker", "title": str(exc), "detail": ""}],
        }
    height, width = stdscr.getmaxyx()
    _safe_add(stdscr, 0, 0, " AQG ", curses.A_BOLD | curses.color_pair(5))
    _safe_add(stdscr, 0, 6, f"{project['name']}  ·  {root}", curses.A_BOLD)
    status = latest.get("status", "no evidence") if latest else "no evidence"
    _safe_add(stdscr, 2, 2, "LATEST", curses.A_DIM)
    _safe_add(stdscr, 3, 2, status.replace("_", " ").upper(), curses.A_BOLD | _color(status))
    if latest:
        _safe_add(
            stdscr,
            4,
            2,
            f"{latest['profile']} · {human_duration(latest['duration_ms'])} · {latest['run_id']}",
            curses.A_DIM,
        )
    _safe_add(stdscr, 2, 34, "RISK / REVIEW / SETUP", curses.A_DIM)
    blockers = review["summary"]["blockers"]
    prompts = review["summary"]["human_review"]
    approval_status = review.get("summary", {}).get("approval_status", "unknown")
    setup_blockers = int(onboarding.get("summary", {}).get("blockers", 0))
    risk_name = str(risk.get("selected_risk_profile", "invalid")) if not risk_errors else "invalid"
    _safe_add(
        stdscr,
        3,
        34,
        f"{risk_name} · {blockers} review blocker(s) · {setup_blockers} setup",
        curses.A_BOLD | _color("blocker" if blockers or risk_errors or setup_blockers else "pass"),
    )
    _safe_add(
        stdscr,
        4,
        34,
        f"{prompts} human prompt(s) · approvals {approval_status}"
        + (" · onboarding stale" if onboarding_bundle["stale"] else ""),
        _color(
            "review"
            if prompts or approval_status != "current" or onboarding_bundle["stale"]
            else "pass"
        ),
    )
    row = 6
    _safe_add(stdscr, row, 2, "GATES", curses.A_BOLD)
    row += 1
    gates = latest.get("gates", []) if latest else []
    columns = 2 if width >= 100 else 1
    col_width = max(32, (width - 6) // columns)
    for index, gate in enumerate(gates):
        gate_row = row + index // columns
        gate_col = 2 + (index % columns) * col_width
        symbol = "●" if gate["status"] == "pass" else "×"
        _safe_add(stdscr, gate_row, gate_col, symbol, _color(gate["status"]))
        _safe_add(
            stdscr,
            gate_row,
            gate_col + 2,
            f"{gate['name']:<23} {human_duration(gate['duration_ms'])}",
        )
    row += max(1, (len(gates) + columns - 1) // columns) + 1
    _safe_add(stdscr, row, 2, "TOP REVIEW FINDINGS", curses.A_BOLD)
    row += 1
    for finding in review.get("findings", [])[: max(2, height - row - 5)]:
        severity = finding["severity"]
        _safe_add(stdscr, row, 2, severity.upper(), curses.A_BOLD | _color(severity))
        _safe_add(stdscr, row, 13, finding["title"])
        row += 1
        if finding.get("detail") and row < height - 4:
            for line in textwrap.wrap(finding["detail"], max(30, width - 18))[:2]:
                _safe_add(stdscr, row, 13, line, curses.A_DIM)
                row += 1
    _safe_add(
        stdscr,
        height - 2,
        1,
        "[f] fast [p] PR [d] deep [R] release [x] risk [r] review [c] conformance [s] setup [u] refresh setup [o] refresh [q] quit",
        curses.A_REVERSE,
    )
    if message:
        _safe_add(stdscr, height - 1, 1, message, curses.A_BOLD)
    stdscr.refresh()


def _run(stdscr: Any, root: Path) -> None:
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    curses.init_pair(4, curses.COLOR_YELLOW, -1)
    curses.init_pair(5, curses.COLOR_CYAN, -1)
    message = ""
    while True:
        _draw(stdscr, root, message)
        key = stdscr.getch()
        if key in (ord("q"), 27):
            return
        if key in (ord("o"), curses.KEY_RESIZE):
            message = "Refreshed."
            continue
        if key == ord("r"):
            project = load_project(root)
            base = os.environ.get("AQG_DIFF_BASE") or str(
                project.get("enforcement", {}).get("base_ref", "HEAD")
            )
            packet = analyze_review(root, load_policy(root), base=base, require_evidence=True)
            paths = write_review_packet(root, packet)
            message = f"Review packet written: {paths['html']}"
            continue
        if key == ord("c"):
            code, report = run_conformance(root, tools=False)
            message = f"conformance: {report['status']} · {report['internal']['summary']['passed']}/{report['internal']['summary']['total']} passed"
            continue
        if key == ord("s"):
            bundle = current_onboarding(root)
            action = bundle["current"].get("next_action", {})
            message = f"setup next: {action.get('next_step', 'no action')}" + (
                " · stored plan stale" if bundle["stale"] else ""
            )
            continue
        if key == ord("u"):
            payload = refresh_onboarding(root)
            summary = payload.get("summary", {})
            message = f"setup refreshed: {summary.get('blockers', 0)} blocker(s), {summary.get('review', 0)} review item(s)"
            continue
        profiles: list[str] = []
        if key == ord("x"):
            errors, risk = risk_summary(root, load_policy(root), "quality/change-risk.json")
            if errors:
                message = "risk card invalid: " + "; ".join(errors[:2])
                continue
            profiles = [str(item) for item in risk.get("required_execution_profiles", [])]
        else:
            profile = {ord("f"): "fast", ord("p"): "pr", ord("d"): "deep", ord("R"): "release"}.get(
                key
            )
            if profile:
                profiles = [profile]
        if profiles:
            profile = profiles[0] if len(profiles) == 1 else "+".join(profiles)
            stdscr.erase()
            _safe_add(
                stdscr,
                1,
                2,
                f"Running AQG {profile}; output is captured as evidence…",
                curses.A_BOLD,
            )
            stdscr.refresh()
            summaries = []
            final_status = "pass"
            for selected in profiles:
                _, summary = run_profile(
                    root, load_policy(root), selected, keep_going=True, quiet=True
                )
                summaries.append(summary)
                if summary["status"] != "pass":
                    final_status = summary["status"]
            elapsed = sum(int(item["duration_ms"]) for item in summaries)
            message = f"{profile}: {final_status} ({human_duration(elapsed)})"


def run_tui(root: Path) -> None:
    try:
        curses.wrapper(_run, root)
    except (curses.error, KeyboardInterrupt):
        runs = list_runs(root, 1)
        latest = runs[0] if runs else None
        print(f"AQG {load_project(root)['name']}")
        print(
            f"Latest: {latest['status']} · {latest['profile']}"
            if latest
            else "No evidence runs yet."
        )
