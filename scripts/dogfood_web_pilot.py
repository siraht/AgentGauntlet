#!/usr/bin/env python3
"""Prove AQG against a disposable greenfield TypeScript/HTML/CSS project."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIRECTORY = Path(__file__).resolve().parent
for import_root in (SCRIPT_DIRECTORY.parent / "src", SCRIPT_DIRECTORY):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from project_matrix import _execute_case  # noqa: E402

REQUIRED_CONTROLS = {
    "installed_cli_status",
    "typecheck",
    "build",
    "format",
    "lint",
    "test_integrity",
    "unit",
    "structure",
    "coverage",
    "acceptance",
    "mutation_changed",
}


def _failure_kind(error: Exception) -> tuple[str, int]:
    match = re.search(r"(?:returned|failed with) ([123])", str(error))
    if match:
        code = int(match.group(1))
        return {
            1: ("measured_failure", 1),
            2: ("configuration_error", 2),
            3: ("infrastructure_error", 3),
        }[code]
    return "infrastructure_error", 3


def run_pilot(workspace: Path) -> tuple[int, dict[str, Any]]:
    report: dict[str, Any] = {
        "schema_version": 1,
        "evidence_type": "aqg.greenfield-web-pilot",
        "case": "typescript-web",
        "status": "infrastructure_error",
        "controls": [],
        "missing_controls": sorted(REQUIRED_CONTROLS),
    }
    try:
        result = _execute_case("typescript-web", workspace)
    except Exception as exc:
        status, code = _failure_kind(exc)
        report.update({"status": status, "exit_code": code, "error": str(exc)})
        return code, report

    controls = result["gates"]
    observed = {item["gate"] for item in controls if item["status"] == "pass"}
    missing = sorted(REQUIRED_CONTROLS - observed)
    if missing:
        report.update(
            {
                "status": "configuration_error",
                "exit_code": 2,
                "controls": controls,
                "missing_controls": missing,
            }
        )
        return 2, report
    report.update(
        {
            "status": "pass",
            "exit_code": 0,
            "duration_seconds": result["duration_seconds"],
            "controls": controls,
            "missing_controls": [],
            "offline_checker_toolchain": True,
            "baseline_preparation": result["baseline_preparation"],
        }
    )
    return 0, report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write normalized JSON evidence here")
    parser.add_argument("--keep-workspace", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    workspace = Path(tempfile.mkdtemp(prefix="aqg-web-pilot-"))
    try:
        code, report = run_pilot(workspace)
        print(json.dumps(report, indent=2, sort_keys=True))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    finally:
        if args.keep_workspace:
            print(f"workspace: {workspace}")
        else:
            shutil.rmtree(workspace)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
