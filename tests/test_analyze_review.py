"""Public-output characterization for analyze_review and review packet surfaces.

These tests lock normalized ReviewResult / finding fields, severity-code ordering,
risk recommendation payloads, human-review queue signals, Markdown/JSON/HTML/SARIF
shape, and exit semantics. They intentionally avoid private helper choreography.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from aqg.policy import load_policy
from aqg.reporting import review_to_sarif
from aqg.review import (
    _html,
    _markdown,
    analyze_review,
    review_exit_code,
    write_review_packet,
)
from aqg.scaffold import initialize_project

FINDING_FIELDS = frozenset(
    {"code", "severity", "title", "detail", "paths", "action", "automated"}
)
PACKET_FIELDS = frozenset(
    {
        "schema_version",
        "generated_at",
        "base",
        "revision",
        "change_fingerprint",
        "control_fingerprint",
        "changed_files",
        "summary",
        "risk",
        "evidence",
        "approvals",
        "latest_runs",
        "findings",
    }
)
SUMMARY_FIELDS = frozenset(
    {
        "changed",
        "changed_files",
        "production",
        "tests",
        "blockers",
        "human_review",
        "warnings",
        "evidence_status",
        "approval_status",
    }
)
SEVERITY_ORDER = {"blocker": 0, "review": 1, "warning": 2, "info": 3}

# Stable public titles/actions used as regression oracles (detail may be long).
TITLES = {
    "policy-plane-change": "Policy-plane files changed",
    "human-review-plane-change": "Behavioral or approval artifacts changed",
    "production-without-tests": "Production behavior changed without a changed executable test",
    "test-expectation-deleted": "Test assertions or cases were deleted",
    "focused-or-skipped-test": "A new quality suppression was added",
    "coverage-suppression": "A new quality suppression was added",
    "mutation-suppression": "A new quality suppression was added",
    "lint-or-type-suppression": "A new quality suppression was added",
    "swallowed-broad-exception": "A broad exception is swallowed",
    "new-production-debt-marker": "New unresolved implementation debt was added",
    "test-nondeterminism-introduced": (
        "Changed tests appear to depend on uncontrolled time, randomness, delay, or network"
    ),
    "weak-test-oracle": "Changed tests contain low-specificity assertions",
    "public-contract-without-contract-test": (
        "A likely public interface changed without changed contract evidence"
    ),
    "dependency-lifecycle-script-change": "A package lifecycle script was added or changed",
    "test-case-count-reduced": "The changed diff removes more test cases than it adds",
    "expected-output-change": "Expected-output artifacts changed",
    "dependency-change": "Dependency or lockfile surface changed",
    "invalid-risk-card": "Change-risk card is missing, invalid, or under-classified",
    "no-quality-evidence": "No AQG profile evidence exists",
}


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def _baseline_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "aqg@example.invalid")
    _git(root, "config", "user.name", "AQG Tests")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text(
        "def calculate(value: int) -> int:\n    return value + 1\n",
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )
    initialize_project(root, install=False, ci=False)
    (root / "feature-spec").mkdir(exist_ok=True)
    (root / "feature-spec" / "Product.Calculation.md").write_text(
        "# Product.Calculation\n\n## Requirements\n\n"
        "- The product MUST calculate a result.\n",
        encoding="utf-8",
    )
    (root / "package.json").write_text(
        json.dumps({"name": "sample", "version": "1.0.0"}),
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    return root


def _packet(root: Path, *, require_evidence: bool = False) -> dict[str, Any]:
    return analyze_review(
        root, load_policy(root), base="HEAD", require_evidence=require_evidence
    )


def _by_code(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {finding["code"]: finding for finding in packet["findings"]}


def _assert_finding_shape(finding: dict[str, Any]) -> None:
    assert FINDING_FIELDS <= set(finding)
    assert finding["severity"] in SEVERITY_ORDER
    assert isinstance(finding["code"], str) and finding["code"]
    assert isinstance(finding["title"], str) and finding["title"]
    assert isinstance(finding["detail"], str) and finding["detail"]
    assert isinstance(finding["action"], str) and finding["action"]
    assert isinstance(finding["paths"], list)
    assert finding["paths"] == sorted(set(finding["paths"]))
    assert isinstance(finding["automated"], bool)


def _assert_packet_shape(packet: dict[str, Any]) -> None:
    assert PACKET_FIELDS <= set(packet)
    assert packet["schema_version"] == 3
    assert packet["base"] == "HEAD"
    assert isinstance(packet["generated_at"], str) and packet["generated_at"]
    assert isinstance(packet["revision"], str) and packet["revision"]
    assert isinstance(packet["change_fingerprint"], str)
    assert isinstance(packet["control_fingerprint"], str)
    assert isinstance(packet["changed_files"], list)
    assert isinstance(packet["findings"], list)
    assert isinstance(packet["evidence"], list)
    assert isinstance(packet["latest_runs"], list)
    assert isinstance(packet["approvals"], dict)
    assert SUMMARY_FIELDS <= set(packet["summary"])
    for finding in packet["findings"]:
        _assert_finding_shape(finding)


def _assert_sorted(packet: dict[str, Any]) -> None:
    keys = [
        (SEVERITY_ORDER.get(item["severity"], 9), item["code"]) for item in packet["findings"]
    ]
    assert keys == sorted(keys)


def _assert_summary_matches_findings(packet: dict[str, Any]) -> None:
    findings = packet["findings"]
    summary = packet["summary"]
    assert summary["blockers"] == sum(item["severity"] == "blocker" for item in findings)
    assert summary["human_review"] == sum(item["severity"] == "review" for item in findings)
    assert summary["warnings"] == sum(item["severity"] == "warning" for item in findings)
    assert summary["changed"] == len(packet["changed_files"])
    assert summary["changed_files"] == len(packet["changed_files"])


def test_clean_workspace_has_no_diff_findings(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    packet = _packet(root, require_evidence=False)
    _assert_packet_shape(packet)
    _assert_sorted(packet)
    _assert_summary_matches_findings(packet)
    assert packet["changed_files"] == []
    assert packet["summary"]["production"] == 0
    assert packet["summary"]["tests"] == 0
    # Without a diff, no heuristic findings should fire.
    assert packet["findings"] == []
    assert review_exit_code(packet) == 0


def test_production_change_without_tests_and_type_suppression(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "src" / "app.py").write_text(
        "def calculate(value: int) -> int:\n    return value - 1  # type: ignore\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    _assert_packet_shape(packet)
    by_code = _by_code(packet)
    assert "production-without-tests" in by_code
    assert "lint-or-type-suppression" in by_code
    production = by_code["production-without-tests"]
    assert production["severity"] == "blocker"
    assert production["title"] == TITLES["production-without-tests"]
    assert production["paths"] == ["src/app.py"]
    assert production["automated"] is True
    suppress = by_code["lint-or-type-suppression"]
    assert suppress["severity"] == "blocker"
    assert suppress["title"] == TITLES["lint-or-type-suppression"]
    assert suppress["paths"] == ["src/app.py:2"]
    assert review_exit_code(packet) == 1


def test_policy_and_human_review_plane_detection(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    quality = root / "QUALITY.md"
    quality.write_text(quality.read_text(encoding="utf-8") + "\n# agent note\n", encoding="utf-8")
    feature = root / "feature-spec" / "Product.Calculation.md"
    feature.write_text(
        "# Product.Calculation\n\n## Requirements\n\n- The product MUST calculate carefully.\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    by_code = _by_code(packet)
    policy = by_code["policy-plane-change"]
    assert policy["severity"] == "blocker"
    assert policy["title"] == TITLES["policy-plane-change"]
    assert policy["paths"] == ["QUALITY.md"]
    assert policy["automated"] is True
    human = by_code["human-review-plane-change"]
    assert human["severity"] == "review"
    assert human["title"] == TITLES["human-review-plane-change"]
    assert human["automated"] is False
    assert "feature-spec/Product.Calculation.md" in human["paths"]


def test_debt_marker_only_in_python_comments(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "src" / "app.py").write_text(
        'MESSAGE = "Create a TODO feature specification."\n'
        "def calculate(value: int) -> int:\n"
        "    return value + 1\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )
    string_packet = _packet(root)
    assert "new-production-debt-marker" not in _by_code(string_packet)

    (root / "src" / "app.py").write_text(
        "def calculate(value: int) -> int:\n"
        "    return value + 1  # TODO: replace the temporary rule\n",
        encoding="utf-8",
    )
    comment_packet = _packet(root)
    debt = _by_code(comment_packet)["new-production-debt-marker"]
    assert debt["severity"] == "warning"
    assert debt["title"] == TITLES["new-production-debt-marker"]
    assert debt["paths"] == ["src/app.py:2"]
    assert debt["automated"] is True


def test_swallowed_exceptions_python_and_javascript(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "src" / "app.py").write_text(
        "def calculate(value: int) -> int:\n"
        "    try:\n"
        "        return value + 1\n"
        "    except Exception:\n"
        "        pass\n",
        encoding="utf-8",
    )
    (root / "src" / "client.js").write_text(
        "export function run() { try { doThing() } catch (e) {} }\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    swallowed = _by_code(packet)["swallowed-broad-exception"]
    assert swallowed["severity"] == "blocker"
    assert swallowed["title"] == TITLES["swallowed-broad-exception"]
    assert swallowed["paths"] == ["src/app.py:4", "src/client.js:1"]
    assert swallowed["automated"] is True


def test_quality_suppressions_are_blockers_with_locations(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "src" / "app.py").write_text(
        "def calculate(value: int) -> int:  # pragma: no cover\n"
        "    return value + 1  # pragma: no mutate\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "import pytest\n"
        "@pytest.mark.skip\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    by_code = _by_code(packet)
    assert by_code["coverage-suppression"]["paths"] == ["src/app.py:1"]
    assert by_code["mutation-suppression"]["paths"] == ["src/app.py:2"]
    assert by_code["focused-or-skipped-test"]["paths"] == ["tests/test_app.py:3"]
    for code in (
        "coverage-suppression",
        "mutation-suppression",
        "focused-or-skipped-test",
    ):
        assert by_code[code]["severity"] == "blocker"
        assert by_code[code]["title"] == TITLES[code]
        assert by_code[code]["automated"] is True


def test_deleted_test_expectations_and_case_count_reduction(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    # Establish two executable cases so a later net reduction is visible in the diff.
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n"
        "def test_secondary() -> None:\n"
        "    assert calculate(2) == 3\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "two-cases")
    (root / "src" / "app.py").write_text(
        "def calculate(value: int) -> int:\n    return value + 2\n",
        encoding="utf-8",
    )
    # Net reduction: remove both original cases, keep one renamed remnant.
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_remaining() -> None:\n"
        "    assert True\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    by_code = _by_code(packet)
    deleted = by_code["test-expectation-deleted"]
    assert deleted["severity"] == "blocker"
    assert deleted["title"] == TITLES["test-expectation-deleted"]
    assert deleted["paths"] == ["tests/test_app.py"]
    reduced = by_code["test-case-count-reduced"]
    assert reduced["severity"] == "review"
    assert reduced["title"] == TITLES["test-case-count-reduced"]
    assert reduced["automated"] is False
    assert any(path.startswith("tests/test_app.py:") for path in reduced["paths"])


def test_loopback_network_is_allowed_external_is_flagged(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    test_path = root / "tests" / "test_network.py"
    test_path.write_text(
        "import urllib.request\n\n"
        "def test_loopback(port: int) -> None:\n"
        '    base = f"http://127.0.0.1:{port}"\n'
        '    request = urllib.request.Request(base + "/health")\n'
        '    urllib.request.urlopen(base + "/status")\n'
        "    urllib.request.urlopen(request)\n",
        encoding="utf-8",
    )
    loopback = _packet(root)
    assert "test-nondeterminism-introduced" not in _by_code(loopback)

    test_path.write_text(
        test_path.read_text(encoding="utf-8")
        + '\ndef test_external() -> None:\n'
        '    urllib.request.urlopen("https://example.com/status")\n',
        encoding="utf-8",
    )
    external = _packet(root)
    finding = _by_code(external)["test-nondeterminism-introduced"]
    assert finding["severity"] == "warning"
    assert finding["title"] == TITLES["test-nondeterminism-introduced"]
    assert any("test_network.py" in path for path in finding["paths"])
    assert finding["automated"] is True


def test_weak_oracle_detection(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    result = calculate(1)\n"
        "    assert result\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    weak = _by_code(packet)["weak-test-oracle"]
    assert weak["severity"] == "warning"
    assert weak["title"] == TITLES["weak-test-oracle"]
    assert weak["paths"] == ["tests/test_app.py:4"]


def test_public_contract_snapshot_dependency_and_lifecycle_surface(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "src" / "routes").mkdir(parents=True)
    (root / "src" / "routes" / "api.py").write_text(
        "def handler() -> dict[str, bool]:\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "sample",
                "version": "1.0.1",
                "scripts": {"postinstall": "node setup.js"},
            }
        ),
        encoding="utf-8",
    )
    snap_dir = root / "tests" / "__snapshots__"
    snap_dir.mkdir(parents=True)
    # Avoid contract/api/route tokens in the snapshot path so it is not treated as
    # contract evidence for the public-interface heuristic.
    (snap_dir / "handler.snap").write_text("expected\n", encoding="utf-8")
    # Keep a non-contract test change so production-without-tests is not the focus.
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n"
        "def test_handler_exists() -> None:\n"
        "    assert True\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    by_code = _by_code(packet)
    contract = by_code["public-contract-without-contract-test"]
    assert contract["severity"] == "review"
    assert contract["title"] == TITLES["public-contract-without-contract-test"]
    assert contract["paths"] == ["src/routes/api.py"]
    assert contract["automated"] is False
    assert by_code["expected-output-change"]["paths"] == ["tests/__snapshots__/handler.snap"]
    assert by_code["expected-output-change"]["severity"] == "review"
    assert by_code["expected-output-change"]["automated"] is False
    assert "package.json" in by_code["dependency-change"]["paths"]
    assert by_code["dependency-change"]["automated"] is False
    lifecycle = by_code["dependency-lifecycle-script-change"]
    assert lifecycle["severity"] == "review"
    assert lifecycle["automated"] is False
    assert any(path.startswith("package.json:") for path in lifecycle["paths"])


def test_risk_factor_mismatch_for_public_api_paths(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "src" / "routes").mkdir(parents=True)
    (root / "src" / "routes" / "api.py").write_text(
        "def handler() -> dict[str, bool]:\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_contract_api.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_api_contract() -> None:\n"
        "    assert handler()['ok'] is True\n",
        encoding="utf-8",
    )
    risk_path = root / "quality" / "change-risk.json"
    risk = json.loads(risk_path.read_text(encoding="utf-8"))
    risk["risk_factors"]["external_contract"] = False
    risk_path.write_text(json.dumps(risk, indent=2) + "\n", encoding="utf-8")
    packet = _packet(root)
    factor = _by_code(packet)["risk-factor-external_contract"]
    assert factor["severity"] == "blocker"
    assert "src/routes/api.py" in factor["paths"]
    assert "external contract" in factor["title"]
    assert factor["automated"] is True
    assert packet["risk"] is not None
    assert "selected_risk_profile" in packet["risk"]
    assert "required_execution_profiles" in packet["risk"]


def test_invalid_risk_card_is_blocker(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "quality" / "change-risk.json").write_text("{not-json", encoding="utf-8")
    (root / "src" / "app.py").write_text(
        "def calculate(value: int) -> int:\n    return value + 1\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    invalid = _by_code(packet)["invalid-risk-card"]
    assert invalid["severity"] == "blocker"
    assert invalid["title"] == TITLES["invalid-risk-card"]
    assert invalid["paths"] == ["quality/change-risk.json"]
    assert packet["risk"] is None


def test_require_evidence_without_runs_emits_blockers(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    packet = _packet(root, require_evidence=True)
    _assert_packet_shape(packet)
    codes = {finding["code"] for finding in packet["findings"]}
    # Either profile-specific missing evidence or the empty-run fallback.
    assert codes & {
        "no-quality-evidence",
        "no-required-profile",
    } or any(code.startswith("missing-current-") for code in codes)
    assert packet["summary"]["evidence_status"] == "missing_or_stale"
    assert review_exit_code(packet) == 1


def test_mixed_diff_ordering_summary_and_render_surfaces(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "QUALITY.md").write_text(
        (root / "QUALITY.md").read_text(encoding="utf-8") + "\n# tweak\n",
        encoding="utf-8",
    )
    (root / "feature-spec" / "Product.Calculation.md").write_text(
        "# Product.Calculation\n\n## Requirements\n\n- The product MUST calculate carefully.\n",
        encoding="utf-8",
    )
    (root / "src" / "app.py").write_text(
        "def calculate(value: int) -> int:\n"
        "    try:\n"
        "        return value + 1\n"
        "    except Exception:\n"
        "        pass  # TODO: temporary swallow\n",
        encoding="utf-8",
    )
    (root / "src" / "routes").mkdir(parents=True)
    (root / "src" / "routes" / "api.py").write_text(
        "def handler() -> dict[str, bool]:\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    (root / "src" / "client.js").write_text(
        "export function run() { try { doThing() } catch (e) {} }\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "import pytest\n"
        "@pytest.mark.skip\n"
        "def test_calculate() -> None:\n"
        "    value = object()\n"
        "    assert value\n",
        encoding="utf-8",
    )
    (root / "package.json").write_text(
        json.dumps(
            {
                "name": "sample",
                "version": "1.0.1",
                "scripts": {"postinstall": "echo hi"},
            }
        ),
        encoding="utf-8",
    )
    snap = root / "tests" / "__snapshots__"
    snap.mkdir(parents=True)
    (snap / "x.snap").write_text("old\n", encoding="utf-8")
    risk_path = root / "quality" / "change-risk.json"
    risk = json.loads(risk_path.read_text(encoding="utf-8"))
    risk["risk_factors"]["external_contract"] = False
    risk_path.write_text(json.dumps(risk, indent=2) + "\n", encoding="utf-8")

    packet = _packet(root, require_evidence=False)
    _assert_packet_shape(packet)
    _assert_sorted(packet)
    _assert_summary_matches_findings(packet)

    codes = [finding["code"] for finding in packet["findings"]]
    # Full mixed-diff order is severity then code — pin the known blocker prefix.
    blocker_codes = [
        finding["code"]
        for finding in packet["findings"]
        if finding["severity"] == "blocker"
    ]
    assert blocker_codes == sorted(blocker_codes)
    assert codes == sorted(
        codes,
        key=lambda code: (
            SEVERITY_ORDER[_by_code(packet)[code]["severity"]],
            code,
        ),
    )
    expected_subset = {
        "focused-or-skipped-test",
        "policy-plane-change",
        "risk-factor-external_contract",
        "swallowed-broad-exception",
        "test-expectation-deleted",
        "dependency-change",
        "dependency-lifecycle-script-change",
        "expected-output-change",
        "human-review-plane-change",
        "public-contract-without-contract-test",
        "new-production-debt-marker",
        "weak-test-oracle",
    }
    assert expected_subset <= set(codes)
    assert packet["summary"]["blockers"] >= 5
    assert packet["summary"]["human_review"] >= 4
    assert packet["summary"]["warnings"] >= 2
    assert review_exit_code(packet) == 1

    markdown = _markdown(packet)
    assert markdown.startswith("# AQG review packet")
    assert "**Decision:** BLOCKED" in markdown
    assert "| Revision |" in markdown
    assert "## Findings" in markdown
    assert "## Evidence matrix" in markdown
    assert "## Human approval matrix" in markdown
    for finding in packet["findings"]:
        assert finding["title"] in markdown
        assert finding["code"] in markdown
        assert finding["detail"] in markdown
        assert finding["action"] in markdown

    html = _html(packet)
    assert "AQG review packet" in html
    assert 'class="decision blocker"' in html
    assert "Findings" in html
    for finding in packet["findings"]:
        assert finding["code"] in html
        assert finding["title"] in html

    artifacts = write_review_packet(root, packet)
    assert Path(artifacts["json"]).is_file()
    assert Path(artifacts["markdown"]).is_file()
    assert Path(artifacts["html"]).is_file()
    written = json.loads(Path(artifacts["json"]).read_text(encoding="utf-8"))
    # Normalize only the clock-ish field when comparing packet identity.
    written_cmp = dict(written)
    packet_cmp = dict(packet)
    written_cmp["generated_at"] = packet_cmp["generated_at"] = "STABLE"
    assert written_cmp == packet_cmp
    assert Path(artifacts["markdown"]).read_text(encoding="utf-8") == markdown + "\n"
    assert Path(artifacts["html"]).read_text(encoding="utf-8") == html

    sarif = review_to_sarif(packet)
    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    rule_ids = {rule["id"] for rule in run["tool"]["driver"]["rules"]}
    assert expected_subset <= rule_ids
    # One SARIF result per finding path (or one when paths empty).
    expected_results = sum(len(finding["paths"]) or 1 for finding in packet["findings"])
    assert len(run["results"]) == expected_results
    for result in run["results"]:
        assert result["ruleId"]
        assert result["level"] in {"error", "warning", "note"}
        assert "text" in result["message"]
        assert "automated" in result["properties"]
        assert "action" in result["properties"]


def test_finding_paths_are_sorted_and_unique_for_multi_location(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "src" / "a.py").write_text(
        "def one() -> None:\n    try:\n        x = 1\n    except Exception:\n        pass\n",
        encoding="utf-8",
    )
    (root / "src" / "b.py").write_text(
        "def two() -> None:\n    try:\n        x = 1\n    except Exception:\n        return None\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    paths = _by_code(packet)["swallowed-broad-exception"]["paths"]
    assert paths == sorted(set(paths))
    assert paths == ["src/a.py:4", "src/b.py:4"]


def test_deterministic_rerun_preserves_normalized_fields(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "src" / "app.py").write_text(
        "def calculate(value: int) -> int:\n    return value - 1  # type: ignore\n",
        encoding="utf-8",
    )
    first = _packet(root)
    second = _packet(root)

    def normalize(packet: dict[str, Any]) -> dict[str, Any]:
        clone = json.loads(json.dumps(packet))
        clone["generated_at"] = "STABLE"
        return clone

    assert normalize(first) == normalize(second)
    _assert_sorted(first)
    for finding in first["findings"]:
        if finding["code"] in TITLES:
            assert finding["title"] == TITLES[finding["code"]]


@pytest.mark.parametrize(
    ("filename", "content", "code"),
    [
        (
            "src/app.py",
            "def calculate(value: int) -> int:\n    return value + 1  # noqa: F401\n",
            "lint-or-type-suppression",
        ),
        (
            "src/app.py",
            "def calculate(value: int) -> int:  # pragma: no cover\n    return value + 1\n",
            "coverage-suppression",
        ),
        (
            "src/app.py",
            "def calculate(value: int) -> int:\n    return value + 1  # pragma: no mutate\n",
            "mutation-suppression",
        ),
    ],
)
def test_suppression_families_parametrized(
    tmp_path: Path, filename: str, content: str, code: str
) -> None:
    root = _baseline_repo(tmp_path)
    (root / filename).write_text(content, encoding="utf-8")
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    finding = _by_code(packet)[code]
    assert finding["severity"] == "blocker"
    assert finding["title"] == TITLES[code]
    assert finding["paths"]
    assert all(":" in path for path in finding["paths"])
