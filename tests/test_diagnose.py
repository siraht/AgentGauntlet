"""Public-output characterization for doctor.diagnose.

These tests lock DoctorReport fields, diagnostic codes/severities/messages/
remediations/order, early-return fail-closed behavior, status aggregation,
strict_tools severity, and doctor CLI exit/output contracts so later commits
can split diagnose without changing observable behavior.

They intentionally assert public report surfaces only, not private helper
choreography.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from aqg.cli import main
from aqg.constants import CONFIGURATION_ERROR, PASS, __version__
from aqg.doctor import diagnose
from aqg.scaffold import initialize_project

REPORT_CORE_FIELDS = frozenset(
    {
        "schema_version",
        "generated_at",
        "aqg_version",
        "root",
        "status",
        "counts",
        "diagnostics",
    }
)
REPORT_FULL_EXTRA_FIELDS = frozenset({"project", "risk", "detected"})
DIAGNOSTIC_FIELDS = frozenset({"code", "status", "message", "remediation", "detail"})
STATUSES = frozenset({"pass", "warning", "error"})

# Core orchestration order inside diagnose before delegated _check_* helpers.
CORE_CODE_ORDER = (
    "policy",
    "project",
    "stack",
    "runtime-or-vendored",
    "launcher",
    "command",
    "risk",
    "gate-applicability",
)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def _baseline_repo(tmp_path: Path, *, mode: str = "adopt", ci: bool = False) -> Path:
    root = tmp_path / f"repo-{mode}"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "aqg@example.invalid")
    _git(root, "config", "user.name", "AQG Tests")
    (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    initialize_project(
        root,
        owner="@quality-owner",
        install=False,
        ci=ci,
        mode=mode,
    )
    return root


def _by_code(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in report["diagnostics"]:
        grouped.setdefault(item["code"], []).append(item)
    return grouped


def _codes(report: dict[str, Any]) -> list[str]:
    return [item["code"] for item in report["diagnostics"]]


def _first(report: dict[str, Any], code: str) -> dict[str, Any]:
    for item in report["diagnostics"]:
        if item["code"] == code:
            return item
    raise AssertionError(f"diagnostic {code!r} not found in {_codes(report)}")


def _assert_diagnostic_shape(item: dict[str, Any]) -> None:
    assert set(item) == DIAGNOSTIC_FIELDS
    assert item["status"] in STATUSES
    assert isinstance(item["code"], str) and item["code"]
    assert isinstance(item["message"], str) and item["message"]
    assert item["remediation"] is None or isinstance(item["remediation"], str)


def _assert_report_core(report: dict[str, Any], root: Path) -> None:
    assert set(report) >= REPORT_CORE_FIELDS
    assert report["schema_version"] == 1
    assert report["aqg_version"] == __version__
    assert report["root"] == str(root.resolve())
    assert isinstance(report["generated_at"], str) and report["generated_at"]
    assert report["status"] in STATUSES
    assert set(report["counts"]) == {"pass", "warning", "error"}
    assert all(isinstance(report["counts"][key], int) for key in ("pass", "warning", "error"))
    assert isinstance(report["diagnostics"], list)
    for item in report["diagnostics"]:
        _assert_diagnostic_shape(item)
    recomputed = {
        status: sum(item["status"] == status for item in report["diagnostics"])
        for status in ("pass", "warning", "error")
    }
    assert report["counts"] == recomputed
    if recomputed["error"]:
        assert report["status"] == "error"
    elif recomputed["warning"]:
        assert report["status"] == "warning"
    else:
        assert report["status"] == "pass"


def _assert_full_extras(report: dict[str, Any]) -> None:
    assert set(report) >= REPORT_FULL_EXTRA_FIELDS
    assert isinstance(report["project"], dict)
    assert isinstance(report["risk"], dict)
    assert isinstance(report["detected"], dict)
    for stack in ("javascript", "typescript", "python", "html", "css"):
        assert stack in report["detected"]


def _assert_no_full_extras(report: dict[str, Any]) -> None:
    assert REPORT_FULL_EXTRA_FIELDS.isdisjoint(set(report))


def _core_positions(codes: list[str]) -> dict[str, int]:
    """Map logical diagnose stages to first matching diagnostic index."""
    positions: dict[str, int] = {}
    for index, code in enumerate(codes):
        if "policy" not in positions and code.startswith("policy"):
            positions["policy"] = index
        elif (
            "project" not in positions
            and code.startswith("project-")
            and code
            not in {
                "project-launcher",
                "project-launcher-missing",
                "project-command",
                "project-command-missing",
            }
        ):
            positions["project"] = index
        elif "stack" not in positions and code in {"stack-detection", "stack-drift"}:
            positions["stack"] = index
        elif "runtime-or-vendored" not in positions and code in {
            "runtime-version-drift",
            "vendored-runtime",
            "vendored-runtime-stale",
            "source-runtime",
            "vendored-runtime-missing",
        }:
            positions["runtime-or-vendored"] = index
        elif "launcher" not in positions and code in {
            "project-launcher",
            "project-launcher-missing",
        }:
            positions["launcher"] = index
        elif "command" not in positions and code in {
            "project-command",
            "project-command-missing",
        }:
            positions["command"] = index
        elif "risk" not in positions and code.startswith("risk-card"):
            positions["risk"] = index
        elif "gate-applicability" not in positions and code == "gate-applicability":
            positions["gate-applicability"] = index
    return positions


def test_policy_missing_fails_closed_with_exact_diagnostic(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    report = diagnose(root)
    _assert_report_core(report, root)
    _assert_no_full_extras(report)
    assert report["status"] == "error"
    assert report["counts"] == {"pass": 0, "warning": 0, "error": 1}
    assert report["diagnostics"] == [
        {
            "code": "policy-missing",
            "status": "error",
            "message": "quality/policy.toml does not exist.",
            "remediation": "Run `qg setup` in the repository root.",
            "detail": None,
        }
    ]


def test_policy_unreadable_fails_closed_before_project(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "quality" / "policy.toml").write_text("[[[[broken", encoding="utf-8")
    report = diagnose(root)
    _assert_report_core(report, root)
    _assert_no_full_extras(report)
    assert report["status"] == "error"
    assert report["counts"]["error"] == 1
    assert report["counts"]["pass"] == 0
    item = report["diagnostics"][0]
    assert item["code"] == "policy-unreadable"
    assert item["status"] == "error"
    assert "quality/policy.toml" in item["message"]
    assert item["remediation"] == "Repair or regenerate quality/policy.toml."
    assert not any(code.startswith("project") for code in _codes(report))


def test_project_unreadable_fails_closed_after_policy_valid(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "quality" / "project.json").write_text("{not-json", encoding="utf-8")
    report = diagnose(root)
    _assert_report_core(report, root)
    _assert_no_full_extras(report)
    codes = _codes(report)
    assert codes[0] == "policy-valid"
    assert codes[1] == "project-unreadable"
    assert len(codes) == 2
    item = _first(report, "project-unreadable")
    assert item["status"] == "error"
    assert item["remediation"] == "Run `qg init --force` or repair quality/project.json."
    assert "project.json" in item["message"]
    assert report["status"] == "error"


def test_policy_invalid_emits_one_error_per_message_and_continues(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    with (
        patch("aqg.doctor.load_policy", return_value={"initialized": True}),
        patch(
            "aqg.doctor.validate_policy",
            return_value=["first policy defect", "second policy defect"],
        ),
    ):
        report = diagnose(root)
    invalid = [item for item in report["diagnostics"] if item["code"] == "policy-invalid"]
    assert len(invalid) == 2
    assert invalid[0] == {
        "code": "policy-invalid",
        "status": "error",
        "message": "first policy defect",
        "remediation": "Repair the policy during an explicit policy-maintenance task.",
        "detail": None,
    }
    assert invalid[1]["message"] == "second policy defect"
    assert "policy-valid" not in _codes(report)
    # Invalid policy still continues into project checks when load succeeds.
    assert any(code.startswith("project") for code in _codes(report))


def test_project_invalid_emits_one_error_per_message_and_continues(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    with patch(
        "aqg.doctor.validate_project",
        return_value=["first project defect", "second project defect"],
    ):
        report = diagnose(root)
    invalid = [item for item in report["diagnostics"] if item["code"] == "project-invalid"]
    assert len(invalid) == 2
    assert invalid[0] == {
        "code": "project-invalid",
        "status": "error",
        "message": "first project defect",
        "remediation": "Repair quality/project.json during policy maintenance.",
        "detail": None,
    }
    assert invalid[1]["message"] == "second project defect"
    assert "project-valid" not in _codes(report)
    assert "stack-detection" in _codes(report) or "stack-drift" in _codes(report)


@pytest.mark.parametrize("mode", ["adopt", "greenfield"])
def test_healthy_initialized_project_core_contract_and_order(tmp_path: Path, mode: str) -> None:
    root = _baseline_repo(tmp_path, mode=mode)
    report = diagnose(root)
    _assert_report_core(report, root)
    _assert_full_extras(report)
    codes = _codes(report)
    assert codes[0] == "policy-valid"
    assert codes[1] == "project-valid"
    assert codes[2] == "stack-detection"
    assert _first(report, "policy-valid") == {
        "code": "policy-valid",
        "status": "pass",
        "message": "Policy is initialized and internally consistent.",
        "remediation": None,
        "detail": None,
    }
    assert _first(report, "project-valid") == {
        "code": "project-valid",
        "status": "pass",
        "message": "Project adapter configuration is valid.",
        "remediation": None,
        "detail": None,
    }
    assert _first(report, "stack-detection") == {
        "code": "stack-detection",
        "status": "pass",
        "message": "Configured stacks match current repository detection.",
        "remediation": None,
        "detail": None,
    }
    assert _first(report, "vendored-runtime") == {
        "code": "vendored-runtime",
        "status": "pass",
        "message": f"Vendored project runtime is AQG {__version__}.",
        "remediation": None,
        "detail": None,
    }
    assert _first(report, "project-launcher") == {
        "code": "project-launcher",
        "status": "pass",
        "message": "Project-local quality/qg.py launcher is present.",
        "remediation": None,
        "detail": None,
    }
    assert _first(report, "project-command") == {
        "code": "project-command",
        "status": "pass",
        "message": "Project-local ./aqg command is present.",
        "remediation": None,
        "detail": None,
    }
    risk = _first(report, "risk-card-valid")
    assert risk["status"] == "pass"
    assert risk["message"].startswith("Risk card resolves to ")
    assert " and requires " in risk["message"]
    assert risk["remediation"] is None
    assert "gate-applicability" in codes
    positions = _core_positions(codes)
    ordered = [positions[name] for name in CORE_CODE_ORDER if name in positions]
    assert ordered == sorted(ordered)
    assert report["project"]["enforcement"]["mode"] == mode
    assert report["detected"]["python"] is True


def test_stack_drift_warning_includes_detail_and_exact_remediation(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    project_path = root / "quality" / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["stacks"]["javascript"] = True
    project_path.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
    report = diagnose(root)
    item = _first(report, "stack-drift")
    assert item == {
        "code": "stack-drift",
        "status": "warning",
        "message": "Detected repository stacks no longer match quality/project.json.",
        "remediation": (
            "Run `qg detect --write` during policy maintenance and review the resulting "
            "adapter changes."
        ),
        "detail": ["javascript: configured=True, detected=False"],
    }
    assert "stack-detection" not in _codes(report)


def test_runtime_version_drift_when_generated_by_mismatches(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    project_path = root / "quality" / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["generated_by"] = "aqg 0.0.1"
    project_path.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
    report = diagnose(root)
    item = _first(report, "runtime-version-drift")
    assert item == {
        "code": "runtime-version-drift",
        "status": "warning",
        "message": (
            f"Project configuration was generated by aqg 0.0.1; installed AQG is {__version__}."
        ),
        "remediation": "Run `qg upgrade` and review the diff.",
        "detail": None,
    }


def test_runtime_version_drift_absent_when_generated_by_matches_or_empty(
    tmp_path: Path,
) -> None:
    root = _baseline_repo(tmp_path)
    project_path = root / "quality" / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["generated_by"] = f"aqg {__version__}"
    project_path.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
    report = diagnose(root)
    assert "runtime-version-drift" not in _codes(report)

    project["generated_by"] = ""
    project_path.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
    report = diagnose(root)
    assert "runtime-version-drift" not in _codes(report)

    # Missing key must default to empty (not None/str(None)/placeholder).
    del project["generated_by"]
    project_path.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
    report = diagnose(root)
    assert "runtime-version-drift" not in _codes(report)


def test_vendored_runtime_stale_and_missing_and_source_runtime(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    constants = root / "quality" / "_aqg" / "constants.py"
    original = constants.read_text(encoding="utf-8")
    constants.write_text(original.replace(__version__, "9.9.9"), encoding="utf-8")
    stale = diagnose(root)
    assert _first(stale, "vendored-runtime-stale") == {
        "code": "vendored-runtime-stale",
        "status": "warning",
        "message": "Vendored runtime differs from the installed command.",
        "remediation": "Run `qg upgrade` during policy maintenance.",
        "detail": None,
    }
    assert "vendored-runtime" not in _codes(stale)

    import shutil

    shutil.rmtree(root / "quality" / "_aqg")
    (root / "src" / "aqg").mkdir(parents=True)
    (root / "src" / "aqg" / "constants.py").write_text(
        f'__version__ = "{__version__}"\n',
        encoding="utf-8",
    )
    source = diagnose(root)
    assert _first(source, "source-runtime") == {
        "code": "source-runtime",
        "status": "pass",
        "message": f"Source-checkout runtime is AQG {__version__}.",
        "remediation": None,
        "detail": None,
    }

    (root / "src" / "aqg" / "constants.py").write_text(
        '__version__ = "0.0.0"\n',
        encoding="utf-8",
    )
    missing = diagnose(root)
    assert _first(missing, "vendored-runtime-missing") == {
        "code": "vendored-runtime-missing",
        "status": "error",
        "message": "quality/_aqg is missing.",
        "remediation": "Run `qg upgrade` to restore the project-local runtime.",
        "detail": None,
    }
    assert missing["status"] == "error"


def test_vendored_runtime_replaces_invalid_utf8_and_still_classifies(
    tmp_path: Path,
) -> None:
    """Invalid bytes must not crash diagnose; replace errors keep classification."""
    root = _baseline_repo(tmp_path)
    constants = root / "quality" / "_aqg" / "constants.py"
    # Invalid UTF-8 payload with the correct version marker as latin-1/bytes mix.
    marker = f'__version__ = "{__version__}"'.encode()
    constants.write_bytes(b"\xff\xfe" + marker + b"\n")
    report = diagnose(root)
    assert _first(report, "vendored-runtime")["status"] == "pass"

    constants.write_bytes(b'\xff\xfe__version__ = "9.9.9"\n')
    report = diagnose(root)
    assert _first(report, "vendored-runtime-stale")["status"] == "warning"


def test_project_launcher_and_command_missing_fail_closed(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "quality" / "qg.py").unlink()
    (root / "aqg").unlink()
    report = diagnose(root)
    assert _first(report, "project-launcher-missing") == {
        "code": "project-launcher-missing",
        "status": "error",
        "message": "Project-local quality/qg.py launcher is missing or unreadable.",
        "remediation": "Run `qg upgrade`.",
        "detail": None,
    }
    assert _first(report, "project-command-missing") == {
        "code": "project-command-missing",
        "status": "error",
        "message": "Project-local ./aqg command is missing or unreadable.",
        "remediation": "Run `qg upgrade`.",
        "detail": None,
    }
    assert report["status"] == "error"
    assert report["counts"]["error"] >= 2


def test_project_launcher_and_command_require_readable_files(tmp_path: Path) -> None:
    """Presence alone is insufficient: the path must be a readable file."""
    root = _baseline_repo(tmp_path)
    launcher = root / "quality" / "qg.py"
    command = root / "aqg"
    os.chmod(launcher, 0o000)
    os.chmod(command, 0o000)
    try:
        report = diagnose(root)
    finally:
        os.chmod(launcher, 0o644)
        os.chmod(command, 0o755)
    assert _first(report, "project-launcher-missing")["status"] == "error"
    assert _first(report, "project-command-missing")["status"] == "error"
    assert "project-launcher" not in _codes(report)
    assert "project-command" not in _codes(report)

    # Directory named ./aqg is not an executable command file.
    command.unlink()
    command.mkdir()
    report = diagnose(root)
    assert _first(report, "project-command-missing")["status"] == "error"


def test_risk_card_invalid_emits_each_error_and_continues(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "quality" / "change-risk.json").write_text("{}", encoding="utf-8")
    report = diagnose(root)
    invalid = [item for item in report["diagnostics"] if item["code"] == "risk-card-invalid"]
    assert len(invalid) >= 2
    for item in invalid:
        assert item["status"] == "error"
        assert item["remediation"] == (
            "Update quality/change-risk.json in observable product terms."
        )
        assert isinstance(item["message"], str) and item["message"]
        assert item["detail"] is None
    assert "risk-card-valid" not in _codes(report)
    assert "gate-applicability" in _codes(report)
    assert report["status"] == "error"
    _assert_full_extras(report)


def test_strict_tools_default_is_false_and_promotes_when_enabled(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    # Default argument must remain non-strict so ordinary doctor stays advisory.
    default_report = diagnose(root)
    warning_report = diagnose(root, strict_tools=False)
    error_report = diagnose(root, strict_tools=True)
    default_tools = {
        item["code"]: item["status"]
        for item in default_report["diagnostics"]
        if item["code"].endswith("tools-missing")
    }
    assert default_tools == {"python-tools-missing": "warning"}
    assert all(status == "warning" for status in default_tools.values())
    assert default_report["counts"]["error"] == warning_report["counts"]["error"]
    warning_tools = {
        item["code"]: item["status"]
        for item in warning_report["diagnostics"]
        if item["code"].endswith("tools-missing")
    }
    error_tools = {
        item["code"]: item["status"]
        for item in error_report["diagnostics"]
        if item["code"].endswith("tools-missing")
    }
    assert warning_tools == {"python-tools-missing": "warning"}
    assert set(warning_tools) == set(error_tools)
    assert all(status == "warning" for status in warning_tools.values())
    assert all(status == "error" for status in error_tools.values())
    assert warning_report["status"] in {"warning", "pass"}
    assert error_report["status"] == "error"
    for code in warning_tools:
        warn_item = _first(warning_report, code)
        err_item = _first(error_report, code)
        assert warn_item["message"] == err_item["message"]
        assert warn_item["remediation"] == err_item["remediation"]
        assert warn_item["detail"] == err_item["detail"]


def test_source_date_epoch_pass_when_set(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    previous = os.environ.get("SOURCE_DATE_EPOCH")
    os.environ["SOURCE_DATE_EPOCH"] = "1700000000"
    try:
        report = diagnose(root)
    finally:
        if previous is None:
            del os.environ["SOURCE_DATE_EPOCH"]
        else:
            os.environ["SOURCE_DATE_EPOCH"] = previous
    item = _first(report, "source-date-epoch")
    assert item == {
        "code": "source-date-epoch",
        "status": "pass",
        "message": "SOURCE_DATE_EPOCH is set for reproducibility-sensitive commands.",
        "remediation": None,
        "detail": "1700000000",
    }


def test_gate_applicability_follows_risk_and_uses_stable_message(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    report = diagnose(root)
    codes = _codes(report)
    assert codes.index("risk-card-valid") < codes.index("gate-applicability")
    item = _first(report, "gate-applicability")
    assert item["status"] == "pass"
    assert item["remediation"] is None
    assert "gates are applicable" in item["message"]
    assert "are explicitly not applicable" in item["message"]
    assert isinstance(item["detail"], dict)
    assert set(item["detail"]) == {"applicable", "not_applicable"}
    assert isinstance(item["detail"]["applicable"], list)
    assert isinstance(item["detail"]["not_applicable"], list)


def test_status_prefers_error_over_warning_over_pass(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    # Warning-only path (tools missing, onboarding gaps typical for install=False).
    warning_report = diagnose(root, strict_tools=False)
    assert warning_report["counts"]["error"] == 0
    if warning_report["counts"]["warning"]:
        assert warning_report["status"] == "warning"

    (root / "aqg").unlink()
    error_report = diagnose(root, strict_tools=False)
    assert error_report["counts"]["error"] >= 1
    assert error_report["status"] == "error"


def test_doctor_cli_json_and_human_exit_semantics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Use --root so the process cwd stays on the AQG source tree. Mutmut's
    # trampoline resolves source_paths against cwd; chdir into fixture repos
    # breaks mutation campaigns without changing the public doctor contract.
    root = _baseline_repo(tmp_path)
    code = main(["--root", str(root), "doctor", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == PASS
    _assert_report_core(payload, root)
    _assert_full_extras(payload)
    assert payload["counts"]["error"] == 0

    code = main(["--root", str(root), "doctor"])
    human = capsys.readouterr().out
    assert code == PASS
    assert human.splitlines()[0] == f"AQG doctor · {payload['status']} · {payload['root']}"
    assert human.strip().endswith(
        f"{payload['counts']['pass']} passed · "
        f"{payload['counts']['warning']} warning(s) · "
        f"{payload['counts']['error']} error(s)"
    )
    for item in payload["diagnostics"]:
        symbol = {"pass": "✓", "warning": "!", "error": "✗"}[item["status"]]
        assert f"  {symbol} {item['message']}" in human
        if item["remediation"] and item["status"] != "pass":
            assert f"      {item['remediation']}" in human

    (root / "aqg").unlink()
    code = main(["--root", str(root), "doctor", "--json"])
    failed = json.loads(capsys.readouterr().out)
    assert code == CONFIGURATION_ERROR
    assert failed["status"] == "error"
    assert failed["counts"]["error"] >= 1
    assert "project-command-missing" in {item["code"] for item in failed["diagnostics"]}

    code = main(["--root", str(root), "doctor", "--strict-tools", "--json"])
    strict_payload = json.loads(capsys.readouterr().out)
    assert code == CONFIGURATION_ERROR
    assert strict_payload["status"] == "error"
    assert any(
        item["code"].endswith("tools-missing") and item["status"] == "error"
        for item in strict_payload["diagnostics"]
    )


def test_doctor_cli_policy_missing_exits_configuration_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # CLI root discovery requires quality/project.json or quality/policy.toml.
    # Keep project.json and patch discovery so the dispatcher reaches diagnose
    # without chdir (mutmut source_path resolution depends on process cwd).
    root = tmp_path / "bare"
    (root / "quality").mkdir(parents=True)
    (root / "quality" / "project.json").write_text("{}", encoding="utf-8")
    with patch("aqg.cli.find_project_root", return_value=root.resolve()):
        code = main(["doctor", "--json"])
        payload = json.loads(capsys.readouterr().out)
    assert code == CONFIGURATION_ERROR
    assert payload["diagnostics"][0]["code"] == "policy-missing"


def test_doctor_without_policy_still_rejects_default_maintenance_override(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "bare"
    (root / "quality").mkdir(parents=True)
    (root / "quality" / "project.json").write_text("{}", encoding="utf-8")
    with (
        patch("aqg.cli.find_project_root", return_value=root.resolve()),
        patch.dict(os.environ, {"AQG_POLICY_MAINTENANCE": "1"}, clear=False),
    ):
        code = main(["doctor", "--json"])
        payload = json.loads(capsys.readouterr().out)
    assert code == CONFIGURATION_ERROR
    assert payload["error"]["category"] == "configuration_error"
    assert "refuses active maintenance" in payload["error"]["message"]
    assert payload["status"] == "error"


def test_diagnostic_order_is_stable_across_repeated_runs(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    first = diagnose(root)
    second = diagnose(root)

    def public_diagnostics(report: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "code": item["code"],
                "status": item["status"],
                "message": item["message"],
                "remediation": item["remediation"],
                "detail": item["detail"],
            }
            for item in report["diagnostics"]
        ]

    assert public_diagnostics(first) == public_diagnostics(second)
    assert first["status"] == second["status"]
    assert first["counts"] == second["counts"]


def test_compare_detection_only_reports_boolean_stack_mismatches(tmp_path: Path) -> None:
    """Lock the stack-drift detail format produced through diagnose."""
    root = _baseline_repo(tmp_path)
    project_path = root / "quality" / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    # Invert python (detected true) and invent html.
    project["stacks"]["python"] = False
    project["stacks"]["html"] = True
    project_path.write_text(json.dumps(project, indent=2) + "\n", encoding="utf-8")
    report = diagnose(root)
    detail = _first(report, "stack-drift")["detail"]
    assert isinstance(detail, list)
    assert "python: configured=False, detected=True" in detail
    assert "html: configured=True, detected=False" in detail
    # Ordering follows the fixed stack walk order in doctor.
    stack_order = ("javascript", "typescript", "python", "html", "css")
    stacks_in_detail = [entry.split(":", 1)[0] for entry in detail]
    assert stacks_in_detail == [name for name in stack_order if name in stacks_in_detail]


def test_risk_card_valid_message_includes_selected_profile_and_profiles(
    tmp_path: Path,
) -> None:
    root = _baseline_repo(tmp_path)
    report = diagnose(root)
    risk = report["risk"]
    item = _first(report, "risk-card-valid")
    selected = risk["selected_risk_profile"]
    profiles = ", ".join(risk["required_execution_profiles"])
    assert item["message"] == (f"Risk card resolves to {selected} and requires {profiles}.")


def test_risk_card_valid_message_joins_multiple_execution_profiles(
    tmp_path: Path,
) -> None:
    """Join separator between required profiles is part of the public message."""
    root = _baseline_repo(tmp_path)
    risk_payload = {
        "card": {},
        "selected_risk_profile": "custom",
        "minimum_risk_profile": "standard",
        "required_execution_profiles": ["fast", "pr", "deep"],
        "required_controls": {},
        "errors": [],
    }
    with patch("aqg.doctor.risk_summary", return_value=([], risk_payload)):
        report = diagnose(root)
    item = _first(report, "risk-card-valid")
    assert item["message"] == ("Risk card resolves to custom and requires fast, pr, deep.")


def test_onboarding_explains_artifact_authority_for_high_assurance(tmp_path: Path) -> None:
    """Routine high assurance must not be blocked by ceremonial approval JSON."""
    root = _baseline_repo(tmp_path)
    card_path = root / "quality" / "change-risk.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    card["risk_profile"] = "high_assurance"
    card_path.write_text(json.dumps(card, indent=2) + "\n", encoding="utf-8")
    report = diagnose(root)
    assert report["risk"]["selected_risk_profile"] == "high_assurance"
    risk_item = _first(report, "risk-card-valid")
    assert "high_assurance" in risk_item["message"]
    authority = _first(report, "routine-approvals-not-required")
    assert authority["status"] == "pass"
    assert authority["message"] == (
        "No ceremonial human approval record is required for routine high_assurance work."
    )
    assert "Executable assurance" in authority["remediation"]


def test_module_entrypoint_path_resolution_uses_resolved_root(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    linked = tmp_path / "link-to-repo"
    linked.symlink_to(root, target_is_directory=True)
    report = diagnose(linked)
    assert report["root"] == str(root.resolve())
    assert report["root"] == str(linked.resolve())
