#!/usr/bin/env python3
"""Normalize whole-tree coverage and complexity into a strict-mode readiness report."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _revision(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip())
    return completed.stdout.strip()


def _coverage_payload(report: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    totals = report["totals"]
    summary = {
        "statements": int(totals["num_statements"]),
        "covered_statements": int(totals["covered_lines"]),
        "line_percent": round(float(totals["percent_statements_covered"]), 2),
        "branches": int(totals["num_branches"]),
        "covered_branches": int(totals["covered_branches"]),
        "branch_percent": round(float(totals["percent_branches_covered"]), 2),
    }
    modules = [
        {
            "path": path,
            "line_percent": round(float(item["summary"]["percent_statements_covered"]), 2),
            "branch_percent": round(float(item["summary"]["percent_branches_covered"]), 2)
            if item["summary"]["num_branches"]
            else 100.0,
            "missing_statements": int(item["summary"]["missing_lines"]),
        }
        for path, item in report["files"].items()
    ]
    modules.sort(key=lambda item: (item["line_percent"], item["path"]))
    return summary, modules


def _complexity_payload(report: dict[str, Any]) -> list[dict[str, Any]]:
    hotspots = [
        {
            "path": path,
            "name": item["name"],
            "line": int(item["lineno"]),
            "complexity": int(item["complexity"]),
            "rank": item["rank"],
        }
        for path, items in report.items()
        for item in items
        if item.get("type") in {"function", "method"} or "complexity" in item
    ]
    hotspots.sort(key=lambda item: (-item["complexity"], item["path"], item["line"]))
    return hotspots


def build_report(
    root: Path,
    coverage_path: Path,
    complexity_path: Path,
    *,
    test_count: int,
    generated_at: str,
) -> dict[str, Any]:
    project = _read(root / "quality" / "project.json")
    coverage, modules = _coverage_payload(_read(coverage_path))
    hotspots = _complexity_payload(_read(complexity_path))
    targets = project["thresholds"]
    blockers = {
        "line_coverage_points": round(
            max(0.0, float(targets["coverage"]["lines"]) - coverage["line_percent"]), 2
        ),
        "branch_coverage_points": round(
            max(0.0, float(targets["coverage"]["branches"]) - coverage["branch_percent"]), 2
        ),
        "functions_over_complexity_cap": sum(
            item["complexity"] > int(targets["structure"]["max_cyclomatic_complexity"])
            for item in hotspots
        ),
    }
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "revision": _revision(root),
        "enforcement_mode": project["enforcement"]["mode"],
        "ready_for_strict": not any(blockers.values()),
        "test_count": test_count,
        "targets": {
            "coverage": targets["coverage"],
            "structure": targets["structure"],
            "mutation": targets["mutation"],
        },
        "coverage": coverage,
        "blockers": blockers,
        "lowest_coverage_modules": modules[:12],
        "highest_complexity_functions": hotspots[:20],
        "switch_contract": [
            "whole-tree line and branch coverage meet Standard thresholds",
            "whole-tree structure and CRAP meet Standard caps",
            "whole-tree mutation meets the Standard target after survivor triage",
            "all supported adapter, control-surface, and release conformance passes",
            "no missing, stale, crashed, or silently skipped required evidence",
        ],
    }


def _markdown(payload: dict[str, Any]) -> str:
    coverage = payload["coverage"]
    blockers = payload["blockers"]
    lines = [
        "# Strict-mode readiness",
        "",
        f"Revision: `{payload['revision']}` · mode: **{payload['enforcement_mode']}** · "
        f"strict ready: **{'yes' if payload['ready_for_strict'] else 'no'}**",
        "",
        "## Current evidence",
        "",
        f"- Tests: {payload['test_count']}",
        f"- Line coverage: {coverage['line_percent']:.2f}% "
        f"(gap {blockers['line_coverage_points']:.2f} points)",
        f"- Branch coverage: {coverage['branch_percent']:.2f}% "
        f"(gap {blockers['branch_coverage_points']:.2f} points)",
        f"- Functions above complexity cap: {blockers['functions_over_complexity_cap']}",
        "",
        "## Lowest coverage modules",
        "",
        "| Module | Lines | Branches | Missing statements |",
        "|---|---:|---:|---:|",
    ]
    lines.extend(
        f"| `{item['path']}` | {item['line_percent']:.2f}% | "
        f"{item['branch_percent']:.2f}% | {item['missing_statements']} |"
        for item in payload["lowest_coverage_modules"]
    )
    lines.extend(
        [
            "",
            "## Highest complexity functions",
            "",
            "| Function | Complexity | Rank |",
            "|---|---:|:---:|",
        ]
    )
    lines.extend(
        f"| `{item['path']}:{item['line']}::{item['name']}` | "
        f"{item['complexity']} | {item['rank']} |"
        for item in payload["highest_complexity_functions"]
    )
    lines.extend(["", "## Switch contract", ""])
    lines.extend(f"- {item}" for item in payload["switch_contract"])
    lines.extend(
        [
            "",
            "## Ratchet-to-strict roadmap",
            "",
            "1. Keep changed-code Standard gates authoritative while inherited debt remains visible.",
            "2. Test low-coverage control and evidence modules by observable failure mode, not by line.",
            "3. Split the highest-complexity functions behind characterization tests without changing diagnostics.",
            "4. Run broader source mutation only after fresh coverage makes the scope trustworthy.",
            "5. Switch `quality/project.json` to strict in a dedicated policy-maintenance change only when every switch-contract item is green.",
            "",
            "Suggested coverage checkpoints are 60%, 70%, then the 85% Standard line target. "
            "They are progress markers, not substitutes for the final threshold.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--complexity", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument("--test-count", type=int, required=True)
    parser.add_argument("--generated-at", required=True)
    args = parser.parse_args()
    payload = build_report(
        Path.cwd(),
        args.coverage,
        args.complexity,
        test_count=args.test_count,
        generated_at=args.generated_at,
    )
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.write_text(_markdown(payload), encoding="utf-8")
    print(
        f"strict readiness: lines={payload['coverage']['line_percent']:.2f}% "
        f"branches={payload['coverage']['branch_percent']:.2f}% "
        f"complexity_blockers={payload['blockers']['functions_over_complexity_cap']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
