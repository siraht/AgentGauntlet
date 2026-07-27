"""Conformance fixtures proving that AQG and installed checkers fail on known defects."""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .checks import lint_features, scan_secrets, scan_test_integrity
from .constants import PASS, QUALITY_FAILURE
from .doctor import _js_bin, _venv_bin
from .golden import run_goldens
from .review import analyze_review
from .util import atomic_write, run_command, utc_now, write_json


@dataclass(slots=True)
class ConformanceCase:
    name: str
    status: str
    detail: str
    expected: str
    observed: Any = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _project(stacks: dict[str, bool] | None = None) -> dict[str, Any]:
    values = {
        "javascript": False,
        "typescript": False,
        "python": False,
        "html": False,
        "css": False,
    }
    values.update(stacks or {})
    applicable = bool(values["javascript"] or values["python"])
    gates = {
        "format": {"applicable": applicable, "reason": "No supported source was detected."},
        "lint": {"applicable": applicable, "reason": "No supported source was detected."},
        "typecheck": {"applicable": applicable, "reason": "No typed source was detected."},
        "test_integrity": {"applicable": applicable, "reason": "No supported source was detected."},
        "unit": {"applicable": applicable, "reason": "No supported source was detected."},
        "structure": {"applicable": applicable, "reason": "No supported source was detected."},
        "coverage": {"applicable": applicable, "reason": "No coverable source was detected."},
        "contracts": {
            "applicable": False,
            "reason": "No contract fixtures in the conformance project.",
        },
        "acceptance": {"applicable": True, "reason": "Conformance exercises Gherkin directly."},
        "golden": {"applicable": True, "reason": "Conformance configures one golden scenario."},
        "mutation_changed": {"applicable": applicable, "reason": "No mutable source was detected."},
        "mutation_acceptance": {
            "applicable": True,
            "reason": "Conformance exercises example mutation.",
        },
        "review": {"applicable": True, "reason": "Review analysis is always applicable."},
        "secrets": {"applicable": True, "reason": "Secret scanning is always applicable."},
        "security_fast": {"applicable": applicable, "reason": "No supported source was detected."},
        "security_deep": {"applicable": applicable, "reason": "No supported source was detected."},
        "supply_chain": {
            "applicable": applicable,
            "reason": "No supported dependency ecosystem was detected.",
        },
        "performance": {
            "applicable": False,
            "reason": "No runnable web surface in the conformance project.",
        },
        "reproducible_build": {
            "applicable": False,
            "reason": "No build command in the conformance project.",
        },
        "release_readiness": {
            "applicable": True,
            "reason": "Release evidence is always applicable.",
        },
    }
    return {
        "schema_version": 2,
        "name": "aqg-conformance",
        "stacks": values,
        "paths": {
            "source": ["src"],
            "tests": ["tests"],
            "html": [],
            "css": [],
            "exclude": [".git/**", ".aqg/**", "quality/**"],
        },
        "javascript": {"test_runner": "vitest", "unit_command": None, "build_command": None},
        "python": {"source_paths": ["src"], "test_paths": ["tests"], "pytest_args": []},
        "web": {"base_url": None, "start_command": None},
        "enforcement": {
            "mode": "adopt",
            "scope": "changed",
            "base_ref": "HEAD",
            "new_code_must_meet_current_policy": True,
            "existing_debt_must_not_increase": True,
        },
        "gates": gates,
        "thresholds": {
            "coverage": {
                "lines": 85,
                "branches": 75,
                "functions": 80,
                "statements": 85,
                "changed_lines": 90,
                "allow_missing": False,
            },
            "structure": {
                "max_function_lines": 50,
                "max_cyclomatic_complexity": 10,
                "max_crap": 15,
                "max_nesting_depth": 4,
            },
            "mutation": {
                "minimum_score": 70,
                "maximum_survivors": 0,
                "minimum_selection_coverage": 80,
                "changed_only": True,
            },
            "security": {"audit_level": "high", "allow_unreviewed_ignores": False},
            "performance": {"lighthouse_performance": 0.8, "lighthouse_accessibility": 0.95},
        },
        "profile_thresholds": {"fast": {}, "pr": {}, "deep": {}, "release": {}},
    }


def _record(
    cases: list[ConformanceCase],
    name: str,
    condition: bool,
    expected: str,
    observed: Any,
    detail: str = "",
) -> None:
    cases.append(
        ConformanceCase(
            name,
            "pass" if condition else "fail",
            detail
            or (
                "Checker behaved as required."
                if condition
                else "Checker did not exhibit the required failure behavior."
            ),
            expected,
            observed,
        )
    )


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)


def run_internal_conformance() -> dict[str, Any]:
    cases: list[ConformanceCase] = []
    with tempfile.TemporaryDirectory(prefix="aqg-conformance-") as temp:
        root = Path(temp)
        (root / "src").mkdir()
        (root / "tests").mkdir()
        (root / "quality" / "golden").mkdir(parents=True)
        (root / "quality" / "waivers").mkdir(parents=True)
        (root / "quality" / "baselines").mkdir(parents=True)
        (root / "features").mkdir()

        atomic_write(root / "src" / "app.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
        atomic_write(root / "tests" / "test_app.py", "def test_add():\n    assert 1 + 1 == 2\n")
        project = _project({"python": True})

        clean = scan_test_integrity(root, project)
        _record(
            cases,
            "test-integrity-clean",
            clean["errors"] == 0,
            "clean tests pass integrity scan",
            clean,
        )
        atomic_write(
            root / "tests" / "test_focus.py",
            "import pytest\n\n@pytest.mark.skip(reason='hidden')\ndef test_hidden():\n    assert False\n",
        )
        skipped = scan_test_integrity(root, project)
        _record(
            cases,
            "test-integrity-skip-detected",
            any(item["code"] == "skipped-test" for item in skipped["findings"]),
            "skip marker is detected",
            skipped,
        )

        value = "".join(chr(code) for code in (103, 104, 112, 95)) + "A" * 40
        atomic_write(root / "src" / "secret.py", "TOKEN = " + repr(value) + "\n")
        secrets = scan_secrets(root, project)
        _record(
            cases,
            "secret-detected",
            secrets["errors"] > 0,
            "credential-like material fails the scan",
            secrets,
        )

        atomic_write(
            root / "features" / "bad.feature",
            "Feature: Example\nScenario: bad\n  Givven a value\n  When it runs\n  Then it works\n",
        )
        gherkin = lint_features(root)
        _record(
            cases,
            "gherkin-unknown-syntax-rejected",
            gherkin["errors"] > 0
            and any(item["code"] == "unsupported-gherkin" for item in gherkin["findings"]),
            "unknown Gherkin syntax fails closed",
            gherkin,
        )
        atomic_write(
            root / "features" / "bad.feature",
            "Feature: Example\nScenario Outline: disconnected\n  When input <value> is processed\n  Then output is valid\nExamples:\n  | value | unused |\n  | 1 | x |\n",
        )
        disconnected = lint_features(root)
        _record(
            cases,
            "gherkin-disconnected-example-rejected",
            any(item["code"] == "unused-example-value" for item in disconnected["findings"]),
            "unused Examples data is rejected",
            disconnected,
        )

        scenarios = {
            "schema_version": 1,
            "scenarios": [
                {
                    "name": "deterministic",
                    "command": ["python3", "-c", "print('hello')"],
                    "expected": "quality/golden/expected/deterministic.json",
                    "normalize": [],
                    "capture_files": [],
                }
            ],
        }
        write_json(root / "quality" / "golden" / "scenarios.json", scenarios)
        try:
            code, golden = run_goldens(root, update=True)
            protected = code != PASS
        except Exception as exc:
            code, golden, protected = 2, {"error": str(exc)}, True
        _record(
            cases,
            "golden-update-protected",
            protected
            and not (root / "quality" / "golden" / "expected" / "deterministic.json").exists(),
            "golden update is refused without explicit authorization",
            golden,
        )
        old = os.environ.get("AQG_ALLOW_GOLDEN_UPDATE")
        os.environ["AQG_ALLOW_GOLDEN_UPDATE"] = "1"
        try:
            update_code, _ = run_goldens(root, update=True)
            compare_code, compare = run_goldens(root)
        finally:
            if old is None:
                os.environ.pop("AQG_ALLOW_GOLDEN_UPDATE", None)
            else:
                os.environ["AQG_ALLOW_GOLDEN_UPDATE"] = old
        _record(
            cases,
            "golden-authorized-update-and-compare",
            update_code == PASS and compare_code == PASS,
            "authorized update creates deterministic evidence that compares cleanly",
            compare,
        )

        # Review conformance uses a real Git diff so it exercises the same path as a PR.
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "aqg@example.invalid")
        _git(root, "config", "user.name", "AQG Conformance")
        atomic_write(root / "quality" / "policy.toml", _minimal_policy())
        write_json(root / "quality" / "project.json", project)
        write_json(root / "quality" / "change-risk.json", _risk_card())
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "baseline")
        atomic_write(root / "src" / "app.py", "def add(a: int, b: int) -> int:\n    return a - b\n")
        policy = _read_toml(root / "quality" / "policy.toml")
        packet = analyze_review(root, policy, base="HEAD", require_evidence=False)
        codes = {item["code"] for item in packet["findings"]}
        _record(
            cases,
            "review-production-without-tests",
            "production-without-tests" in codes,
            "review flags production changes without changed tests",
            packet["summary"],
        )

    failures = [case for case in cases if case.status != "pass"]
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "suite": "internal",
        "status": "pass" if not failures else "fail",
        "cases": [case.as_dict() for case in cases],
        "summary": {
            "total": len(cases),
            "passed": len(cases) - len(failures),
            "failed": len(failures),
        },
    }


def _read_toml(path: Path) -> dict[str, Any]:
    import tomllib

    with path.open("rb") as handle:
        return tomllib.load(handle)


def _minimal_policy() -> str:
    return """version = 2
initialized = true
default_risk_profile = "standard"
default_execution_profile = "fast"
[policy]
owner = "conformance"
protected_paths = ["quality/**"]
human_review_paths = ["features/**", "feature-spec/**", "qa/procedures/**"]
blocked_command_regex = []
[risk_rules.minimum_profile_by_factor]
data_loss = "high_assurance"
authentication = "high_assurance"
authorization = "high_assurance"
privacy = "high_assurance"
money = "high_assurance"
external_contract = "high_assurance"
migration = "high_assurance"
concurrency = "high_assurance"
irreversible_action = "high_assurance"
supply_chain = "high_assurance"
safety = "critical"
[risk_profiles.experiment]
required_execution_profiles=["fast"]
[risk_profiles.standard]
required_execution_profiles=["fast"]
[risk_profiles.high_assurance]
required_execution_profiles=["fast"]
[risk_profiles.critical]
required_execution_profiles=["fast"]
[profiles.fast]
gates=["review"]
[gates.review]
command="true"
timeout_seconds=5
clean_paths=[]
quality_failure_exit_codes=[1]
"""


def _risk_card() -> dict[str, Any]:
    return {
        "schema_version": "1",
        "summary": "Conformance change",
        "risk_profile": "standard",
        "production_scope": True,
        "reversible": True,
        "blast_radius": "local",
        "behavior_changes": ["test"],
        "behavior_preserved": ["other behavior"],
        "risk_factors": {
            "data_loss": False,
            "authentication": False,
            "authorization": False,
            "privacy": False,
            "money": False,
            "external_contract": False,
            "migration": False,
            "concurrency": False,
            "irreversible_action": False,
            "supply_chain": False,
            "safety": False,
        },
        "failure_detection": "Conformance assertion",
        "rollback": "Discard temporary directory",
        "human_review": [],
    }


def run_tool_conformance(root: Path) -> dict[str, Any]:
    """Exercise installed tools against one known-good and one known-bad fixture."""

    cases: list[ConformanceCase] = []
    with tempfile.TemporaryDirectory(prefix="aqg-tool-conformance-") as temp:
        fixture = Path(temp)
        (fixture / "src").mkdir()
        (fixture / "tests").mkdir()
        (fixture / "quality" / "config" / "python").mkdir(parents=True)

        js_tools = {
            "prettier": _js_bin(root, "prettier"),
            "eslint": _js_bin(root, "eslint"),
            "stylelint": _js_bin(root, "stylelint"),
            "html-validate": _js_bin(root, "html-validate"),
            "tsc": _js_bin(root, "tsc"),
            "vitest": _js_bin(root, "vitest"),
        }
        if all(path.exists() for path in js_tools.values()):
            atomic_write(
                fixture / "bad.js",
                "const x={a:1}; eval('x')\n",  # AQG_REVIEWED_SECURITY: fault fixture
            )
            prettier = run_command([str(js_tools["prettier"]), "--check", "bad.js"], cwd=fixture)
            _record(
                cases,
                "prettier-rejects-unformatted",
                prettier.code != 0,
                "Prettier rejects unformatted source",
                prettier.as_dict(),
            )
            eslint = run_command(
                [
                    str(js_tools["eslint"]),
                    "--no-config-lookup",
                    "--rule",
                    "no-eval:error",
                    "bad.js",
                ],
                cwd=fixture,
            )
            _record(
                cases,
                "eslint-rejects-eval",
                eslint.code != 0,
                "ESLint rejects forbidden eval",
                eslint.as_dict(),
            )
            atomic_write(fixture / "bad.css", "a { color: red; color: blue; }\n")
            stylelint = run_command(
                [
                    str(js_tools["stylelint"]),
                    "--config",
                    str(root / "quality/tools/js/config/stylelint.config.mjs"),
                    "bad.css",
                ],
                cwd=fixture,
                quality_exit_codes=(1, 2),
            )
            _record(
                cases,
                "stylelint-rejects-duplicate-property",
                stylelint.status == "quality_failure",
                "Stylelint classifies duplicate declarations as a quality failure",
                stylelint.as_dict(),
            )
            atomic_write(
                fixture / "bad.html",
                "<!doctype html><html><body><input><div id='x'></div><p id='x'></p></body></html>\n",
            )
            html = run_command(
                [
                    str(js_tools["html-validate"]),
                    "--config",
                    str(root / "quality/tools/js/config/htmlvalidate.json"),
                    "bad.html",
                ],
                cwd=fixture,
            )
            _record(
                cases,
                "html-validate-rejects-invalid-markup",
                html.code != 0,
                "HTML validator rejects duplicate IDs and unlabeled input",
                html.as_dict(),
            )
            atomic_write(fixture / "bad.ts", "const value: string = null;\n")
            tsc = run_command(
                [
                    str(js_tools["tsc"]),
                    "--strict",
                    "--noEmit",
                    "--skipLibCheck",
                    "--target",
                    "ES2022",
                    "bad.ts",
                ],
                cwd=fixture,
                quality_exit_codes=(1, 2),
            )
            _record(
                cases,
                "typescript-strict-rejects-null",
                tsc.status == "quality_failure",
                "TypeScript classifies a strict type error as a quality failure",
                tsc.as_dict(),
            )
            atomic_write(
                fixture / "tests" / "math.test.js",
                "test('fails', () => expect(1).toBe(2));\n",
            )
            vitest = run_command(
                [
                    str(js_tools["vitest"]),
                    "run",
                    "--root",
                    str(fixture),
                    "--globals",
                    "tests/math.test.js",
                    "--passWithNoTests=false",
                ],
                cwd=fixture,
                env={"CI": "1"},
                timeout=120,
            )
            _record(
                cases,
                "vitest-propagates-failure",
                vitest.status == "quality_failure"
                and "1 failed" in (vitest.stdout + vitest.stderr)
                and "No test files found" not in (vitest.stdout + vitest.stderr),
                "Vitest executes the fixture and classifies its failed assertion as a quality failure",
                vitest.as_dict(),
            )
        else:
            missing = [name for name, path in js_tools.items() if not path.exists()]
            cases.append(
                ConformanceCase(
                    "javascript-toolchain",
                    "skip",
                    "JavaScript toolchain is not installed.",
                    "Run qg tools install",
                    missing,
                )
            )

        py_tools = {name: _venv_bin(root, name) for name in ("pytest", "ruff", "mypy", "bandit")}
        if all(path.exists() for path in py_tools.values()):
            atomic_write(
                fixture / "src" / "bad.py",
                "import os\n\ndef value() -> str:\n    return 1\n\ndef dangerous(x: str):\n    return eval(x)\n",  # AQG_REVIEWED_SECURITY: fault fixture
            )
            atomic_write(
                fixture / "tests" / "test_bad.py", "def test_failure():\n    assert 1 == 2\n"
            )
            pytest = run_command(
                [str(py_tools["pytest"]), "-q", str(fixture / "tests")], cwd=fixture, timeout=120
            )
            _record(
                cases,
                "pytest-propagates-failure",
                pytest.code != 0,
                "pytest returns nonzero for a failed assertion",
                pytest.as_dict(),
            )
            ruff = run_command(
                [str(py_tools["ruff"]), "check", str(fixture / "src")], cwd=fixture, timeout=120
            )
            _record(
                cases,
                "ruff-rejects-defects",
                ruff.code != 0,
                "Ruff rejects lint defects",
                ruff.as_dict(),
            )
            mypy = run_command(
                [str(py_tools["mypy"]), "--strict", str(fixture / "src" / "bad.py")],
                cwd=fixture,
                timeout=120,
            )
            _record(
                cases,
                "mypy-strict-rejects-type-error",
                mypy.code != 0,
                "mypy strict mode rejects return-type mismatch",
                mypy.as_dict(),
            )
            bandit = run_command(
                [str(py_tools["bandit"]), "-q", "-r", str(fixture / "src")],
                cwd=fixture,
                timeout=120,
            )
            _record(
                cases,
                "bandit-rejects-eval",
                bandit.code != 0,
                "Bandit flags eval",
                bandit.as_dict(),
            )
        else:
            missing = [name for name, path in py_tools.items() if not path.exists()]
            cases.append(
                ConformanceCase(
                    "python-toolchain",
                    "skip",
                    "Python toolchain is not installed.",
                    "Run qg tools install",
                    missing,
                )
            )

    failed = [case for case in cases if case.status == "fail"]
    passed = [case for case in cases if case.status == "pass"]
    skipped = [case for case in cases if case.status == "skip"]
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "suite": "tools",
        "status": "pass" if not failed else "fail",
        "cases": [case.as_dict() for case in cases],
        "summary": {
            "total": len(cases),
            "passed": len(passed),
            "failed": len(failed),
            "skipped": len(skipped),
        },
    }


def run_conformance(root: Path | None = None, *, tools: bool = False) -> tuple[int, dict[str, Any]]:
    internal = run_internal_conformance()
    report: dict[str, Any] = {"schema_version": 1, "generated_at": utc_now(), "internal": internal}
    failed = internal["status"] != "pass"
    if tools:
        if root is None:
            raise ValueError("tool conformance requires a project root")
        tool_report = run_tool_conformance(root)
        report["tools"] = tool_report
        failed = failed or tool_report["status"] != "pass"
    report["status"] = "fail" if failed else "pass"
    report["exit_code"] = QUALITY_FAILURE if failed else PASS
    if root is not None:
        write_json(root / ".aqg" / "conformance" / "report.json", report)
    return report["exit_code"], report
