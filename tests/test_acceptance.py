"""Executable acceptance contract for AQG's own public setup behavior."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from aqg.adapters import run_adapter  # noqa: E402
from aqg.checks import lint_features  # noqa: E402
from aqg.cli import build_parser  # noqa: E402
from aqg.constants import CONFIGURATION_ERROR  # noqa: E402
from aqg.scaffold import initialize_project  # noqa: E402


def _record_application_boundary(history: str, expected_scope: str) -> None:
    trace = os.environ.get("AQG_ACCEPTANCE_TRACE")
    if not trace:
        return
    Path(trace).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "reached_application_boundary": True,
                "stage": "initialize_project",
                "history": history,
                "expected_scope": expected_scope,
            }
        ),
        encoding="utf-8",
    )


def _git(root: Path, *args: str) -> None:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def _setup_scope(history: str, expected_scope: str) -> None:
    assert history in {"none", "present"}
    assert expected_scope in {"full", "changed"}
    with tempfile.TemporaryDirectory(prefix="aqg-acceptance-setup-") as temp:
        target = Path(temp)
        _git(target, "init", "-q")
        if history == "present":
            _git(target, "config", "user.email", "aqg@example.invalid")
            _git(target, "config", "user.name", "AQG Acceptance")
            (target / "existing.py").write_text("VALUE = 1\n", encoding="utf-8")
            _git(target, "add", "existing.py")
            _git(target, "commit", "-qm", "existing history")
        _record_application_boundary(history, expected_scope)
        result = initialize_project(target, install=False, ci=False, mode="auto")
        assert result["project"]["enforcement"]["scope"] == expected_scope
        assert (target / "aqg").is_file()
        assert (target / "quality" / "qg.py").is_file()


def _feature_payload() -> dict[str, Any]:
    mutated = os.environ.get("AQG_FEATURE_JSON")
    if mutated:
        return cast(dict[str, Any], json.loads(Path(mutated).read_text(encoding="utf-8")))
    lint = lint_features(PROJECT_ROOT)
    assert lint["errors"] == 0, lint["findings"]
    match = next(
        item
        for item in lint["features"]
        if item["path"] == "features/AgentQualityGauntlet.Setup.feature"
    )
    return dict(match["feature"])


def _exercise_setup_examples(payload: dict[str, Any]) -> None:
    scenario = next(
        item
        for item in payload["scenarios"]
        if item["name"] == "setup selects the expected enforcement scope"
    )
    assert scenario["examples"], "the setup scope contract requires executable examples"
    for example in scenario["examples"]:
        _setup_scope(str(example["history"]), str(example["scope"]))


def test_acceptance_setup_examples_execute_against_real_projects() -> None:
    _exercise_setup_examples(_feature_payload())


def test_acceptance_browser_installation_is_explicitly_opt_in() -> None:
    args = build_parser().parse_args(["setup", ".", "--no-install"])
    assert args.browsers is False


def test_acceptance_incomplete_supply_chain_inventory_fails_closed() -> None:
    with tempfile.TemporaryDirectory(prefix="aqg-acceptance-sbom-") as temp:
        target = Path(temp)
        (target / "package.json").write_text(
            json.dumps({"name": "incomplete", "dependencies": {"example": "1.0.0"}}),
            encoding="utf-8",
        )
        initialize_project(target, install=False, ci=False, mode="greenfield")
        code, report = run_adapter(target, "supply_chain")
        assert code == CONFIGURATION_ERROR
        assert report["inventory"]["complete"] is False


if __name__ == "__main__":
    _exercise_setup_examples(_feature_payload())
