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

from aqg.evidence_manifest import write_run_manifest
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

FINDING_FIELDS = frozenset({"code", "severity", "title", "detail", "paths", "action", "automated"})
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

# Stable public titles/details/actions used as regression oracles.
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
DETAILS = {
    "policy-plane-change": (
        "These files can change what counts as a pass or what agents are allowed to modify, "
        "so they require an explicit policy-maintenance review."
    ),
    "human-review-plane-change": (
        "These files describe behavior, expected output, migrations, schemas, dependencies, or QA "
        "and must be reviewed as product evidence rather than accepted as incidental code churn."
    ),
    "production-without-tests": (
        "Existing tests may cover the change, but no test diff demonstrates the new or preserved "
        "behavior and mutation evidence may be too broad to reveal the gap."
    ),
    "test-expectation-deleted": (
        "Deleting an assertion can make an implementation appear correct by reducing the oracle "
        "rather than fixing behavior."
    ),
    "focused-or-skipped-test": (
        "Suppressions directly reduce what deterministic tools can prove and are equivalent to "
        "changing a test or threshold when used without narrow justification."
    ),
    "coverage-suppression": (
        "Suppressions directly reduce what deterministic tools can prove and are equivalent to "
        "changing a test or threshold when used without narrow justification."
    ),
    "mutation-suppression": (
        "Suppressions directly reduce what deterministic tools can prove and are equivalent to "
        "changing a test or threshold when used without narrow justification."
    ),
    "lint-or-type-suppression": (
        "Suppressions directly reduce what deterministic tools can prove and are equivalent to "
        "changing a test or threshold when used without narrow justification."
    ),
    "swallowed-broad-exception": (
        "Catching a broad failure and continuing without a typed recovery, observable error, or "
        "preserved cause can convert corruption and infrastructure faults into apparent success."
    ),
    "new-production-debt-marker": (
        "A TODO, FIXME, HACK, or XXX marker in changed production code often represents an unstated "
        "requirement, deferred safety condition, or temporary branch that future agents will treat "
        "as normal behavior."
    ),
    "test-nondeterminism-introduced": (
        "Real clocks, random generators, sleeps, and live network calls make tests timing-sensitive "
        "and can let a retry mask the behavior the test was meant to prove."
    ),
    "weak-test-oracle": (
        "Truthiness, existence, nonzero-count, and bare-object assertions can pass while the "
        "returned value, state transition, side effects, ordering, or authorization behavior is wrong."
    ),
    "public-contract-without-contract-test": (
        "API routes, schemas, protocol definitions, and public data shapes can remain unit-test green "
        "while breaking consumers, compatibility, error semantics, or authorization boundaries."
    ),
    "dependency-lifecycle-script-change": (
        "Install and prepare hooks execute during dependency setup and can alter the build "
        "environment, fetch code, expose credentials, or bypass the ordinary quality command surface."
    ),
    "test-case-count-reduced": (
        "Test count alone is not quality, but a net reduction alongside production changes can shrink "
        "the behavioral oracle or remove a distinct equivalence class."
    ),
    "expected-output-change": (
        "Regenerated snapshots and goldens can approve a regression as easily as they can record an "
        "intended change."
    ),
    "dependency-change": (
        "Dependency changes alter executable supply-chain input and can invalidate cached test and "
        "mutation evidence even when application source is unchanged."
    ),
}
ACTIONS = {
    "policy-plane-change": (
        "Review the raw diff with the policy owner and confirm the change does not weaken any gate, "
        "path protection, threshold, or command indirection."
    ),
    "human-review-plane-change": (
        "Review each diff for intentional behavior, stable normalization, rollback impact, and "
        "consistency with the risk card."
    ),
    "production-without-tests": (
        "Add focused unit/property/contract/acceptance evidence, or document why existing immutable "
        "tests already prove the change and verify that claim with mutation testing."
    ),
    "test-expectation-deleted": (
        "Explain every deleted expectation, identify replacement evidence, and inspect mutation "
        "survivors around the affected behavior."
    ),
    "focused-or-skipped-test": (
        "Remove the suppression or create a narrow, expiring, owner-approved waiver with a "
        "reproduced false positive and compensating evidence."
    ),
    "coverage-suppression": (
        "Remove the suppression or create a narrow, expiring, owner-approved waiver with a "
        "reproduced false positive and compensating evidence."
    ),
    "mutation-suppression": (
        "Remove the suppression or create a narrow, expiring, owner-approved waiver with a "
        "reproduced false positive and compensating evidence."
    ),
    "lint-or-type-suppression": (
        "Remove the suppression or create a narrow, expiring, owner-approved waiver with a "
        "reproduced false positive and compensating evidence."
    ),
    "swallowed-broad-exception": (
        "Catch the narrow failure you can recover from, preserve or re-raise unexpected failures, "
        "and add a test that proves both the intended recovery and the non-recoverable path."
    ),
    "new-production-debt-marker": (
        "Resolve it now or link a concrete tracked decision with an owner, bounded impact, and "
        "removal condition; do not use a comment as a substitute for a failing test or TODO feature "
        "specification."
    ),
    "test-nondeterminism-introduced": (
        "Inject or freeze the varying dependency, wait on an observable condition instead of sleeping, "
        "and keep a separately labeled live probe only when the real dependency is the subject of the test."
    ),
    "weak-test-oracle": (
        "Assert the exact domain result and critical side effects, then confirm the assertion kills a "
        "plausible mutation rather than merely observing that some value exists."
    ),
    "public-contract-without-contract-test": (
        "Review the interface diff and add or update consumer-visible contract tests, compatibility "
        "fixtures, versioning/migration evidence, and negative authorization cases as applicable."
    ),
    "dependency-lifecycle-script-change": (
        "Inspect the exact command and transitive tools, require a deterministic offline-safe path "
        "where practical, and ensure CI and developer setup execute the same reviewed behavior."
    ),
    "test-case-count-reduced": (
        "Map every removed case to preserved or stronger evidence and inspect mutation, boundary, "
        "and failure-path coverage before accepting the reduction."
    ),
    "expected-output-change": (
        "Review the full semantic diff and its source behavior; do not approve a bulk update solely "
        "because the test command requested it."
    ),
    "dependency-change": (
        "Inspect direct and transitive changes, provenance, license/security findings, lockfile "
        "integrity, and whether mutation or golden caches were invalidated."
    ),
    "invalid-risk-card": (
        "Resolve the schema and deterministic minimum before relying on the selected execution profile."
    ),
}


def _assert_public_copy(finding: dict[str, Any], code: str) -> None:
    """Pin exact public title/detail/action text for a known finding code."""
    assert finding["code"] == code
    if code in TITLES:
        assert finding["title"] == TITLES[code]
    if code in DETAILS:
        assert finding["detail"] == DETAILS[code]
    if code in ACTIONS:
        assert finding["action"] == ACTIONS[code]


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)
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
        "# Feature-Spec: Product.Calculation PRODUCT-CALC-001\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )
    initialize_project(root, install=False, ci=False)
    (root / "feature-spec").mkdir(exist_ok=True)
    (root / "feature-spec" / "Product.Calculation.md").write_text(
        "# Product.Calculation\n\n## Requirements\n\n"
        "- `PRODUCT-CALC-001` The product MUST calculate a result.\n",
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
    return analyze_review(root, load_policy(root), base="HEAD", require_evidence=require_evidence)


def _by_code(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {finding["code"]: finding for finding in packet["findings"]}


def _assert_finding_shape(finding: dict[str, Any]) -> None:
    assert set(finding) >= FINDING_FIELDS
    assert finding["severity"] in SEVERITY_ORDER
    assert isinstance(finding["code"], str) and finding["code"]
    assert isinstance(finding["title"], str) and finding["title"]
    assert isinstance(finding["detail"], str) and finding["detail"]
    assert isinstance(finding["action"], str) and finding["action"]
    assert isinstance(finding["paths"], list)
    assert finding["paths"] == sorted(set(finding["paths"]))
    assert isinstance(finding["automated"], bool)


def _assert_packet_shape(packet: dict[str, Any]) -> None:
    assert set(packet) >= PACKET_FIELDS
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
    assert set(packet["summary"]) >= SUMMARY_FIELDS
    for finding in packet["findings"]:
        _assert_finding_shape(finding)


def _assert_sorted(packet: dict[str, Any]) -> None:
    keys = [(SEVERITY_ORDER.get(item["severity"], 9), item["code"]) for item in packet["findings"]]
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
    _assert_public_copy(production, "production-without-tests")
    assert production["paths"] == ["src/app.py"]
    assert production["automated"] is True
    suppress = by_code["lint-or-type-suppression"]
    assert suppress["severity"] == "blocker"
    _assert_public_copy(suppress, "lint-or-type-suppression")
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
    _assert_public_copy(policy, "policy-plane-change")
    assert policy["paths"] == ["QUALITY.md"]
    assert policy["automated"] is True
    human = by_code["human-review-plane-change"]
    assert human["severity"] == "review"
    _assert_public_copy(human, "human-review-plane-change")
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
    _assert_public_copy(debt, "new-production-debt-marker")
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
    _assert_public_copy(swallowed, "swallowed-broad-exception")
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
        _assert_public_copy(by_code[code], code)
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
        "# Feature-Spec: Product.Calculation\ndef test_remaining() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    by_code = _by_code(packet)
    deleted = by_code["test-expectation-deleted"]
    assert deleted["severity"] == "blocker"
    _assert_public_copy(deleted, "test-expectation-deleted")
    assert deleted["paths"] == ["tests/test_app.py"]
    reduced = by_code["test-case-count-reduced"]
    assert reduced["severity"] == "review"
    _assert_public_copy(reduced, "test-case-count-reduced")
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
        test_path.read_text(encoding="utf-8") + "\ndef test_external() -> None:\n"
        '    urllib.request.urlopen("https://example.com/status")\n',
        encoding="utf-8",
    )
    external = _packet(root)
    finding = _by_code(external)["test-nondeterminism-introduced"]
    assert finding["severity"] == "warning"
    _assert_public_copy(finding, "test-nondeterminism-introduced")
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
    _assert_public_copy(weak, "weak-test-oracle")
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
    _assert_public_copy(contract, "public-contract-without-contract-test")
    assert contract["paths"] == ["src/routes/api.py"]
    assert contract["automated"] is False
    expected = by_code["expected-output-change"]
    assert expected["paths"] == ["tests/__snapshots__/handler.snap"]
    assert expected["severity"] == "review"
    assert expected["automated"] is False
    _assert_public_copy(expected, "expected-output-change")
    dep = by_code["dependency-change"]
    assert "package.json" in dep["paths"]
    assert dep["automated"] is False
    _assert_public_copy(dep, "dependency-change")
    lifecycle = by_code["dependency-lifecycle-script-change"]
    assert lifecycle["severity"] == "review"
    assert lifecycle["automated"] is False
    _assert_public_copy(lifecycle, "dependency-lifecycle-script-change")
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
    by_code = _by_code(packet)
    factor = by_code["risk-factor-external_contract"]
    assert factor["severity"] == "blocker"
    assert "src/routes/api.py" in factor["paths"]
    assert factor["title"] == "Changed paths imply the external contract risk factor"
    assert factor["detail"] == (
        "The risk card marks 'external_contract' false, but path heuristics found likely affected "
        "files. This is a review prompt rather than proof, but the mismatch must be resolved explicitly."
    )
    assert factor["action"] == (
        "Set risk_factors.external_contract=true or document why these files do not affect that risk "
        "and have a human approve the classification."
    )
    assert factor["automated"] is True
    # Contract-named tests count as contract evidence for the public-interface heuristic.
    assert "public-contract-without-contract-test" not in by_code
    assert packet["risk"] is not None
    assert "selected_risk_profile" in packet["risk"]
    assert "required_execution_profiles" in packet["risk"]


def test_schema_contract_module_is_not_mistaken_for_database_migration(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "src" / "schema_contracts.py").write_text(
        "def validate_contract(value: object) -> bool:\n    return value is not None\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_schema_contracts.py").write_text(
        "# Feature-Spec: Product.Calculation PRODUCT-CALC-001\n"
        "def test_schema_contract() -> None:\n"
        "    assert validate_contract({'ok': True}) is True\n",
        encoding="utf-8",
    )
    risk_path = root / "quality" / "change-risk.json"
    risk = json.loads(risk_path.read_text(encoding="utf-8"))
    risk["risk_factors"]["external_contract"] = True
    risk_path.write_text(json.dumps(risk, indent=2) + "\n", encoding="utf-8")

    by_code = _by_code(_packet(root))

    assert "risk-factor-migration" not in by_code
    assert "risk-factor-external_contract" not in by_code


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
    assert invalid["action"] == ACTIONS["invalid-risk-card"]
    assert isinstance(invalid["detail"], str) and invalid["detail"]
    assert invalid["paths"] == ["quality/change-risk.json"]
    assert packet["risk"] is None


def test_require_evidence_without_runs_emits_blockers(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    packet = _packet(root, require_evidence=True)
    _assert_packet_shape(packet)
    by_code = _by_code(packet)
    codes = set(by_code)
    # Valid risk card still resolves required profiles; missing runs are profile-scoped.
    assert packet["risk"] is not None
    required = list(packet["risk"].get("required_execution_profiles") or [])
    assert required, "scaffold risk card must require at least one execution profile"
    assert "no-required-profile" not in codes
    for profile in required:
        code = f"missing-current-{profile}-evidence"
        assert code in by_code
        finding = by_code[code]
        assert finding["severity"] == "blocker"
        assert finding["title"] == f"No current passing {profile} evidence"
        assert finding["detail"] == (
            "A prior run is not reusable when the revision, review-surface fingerprint, or "
            "control-plane fingerprint differs from the current repository state."
        )
        assert finding["action"] == (
            f"Run `python3 quality/qg.py check {profile} --keep-going` after the final change, "
            "then regenerate the review packet."
        )
        assert finding["paths"] == [".aqg/runs"]
        assert finding["automated"] is True
    assert packet["evidence"] == [
        {"profile": profile, "status": "missing_or_stale", "run_id": None} for profile in required
    ]
    assert packet["summary"]["evidence_status"] == "missing_or_stale"
    assert packet["summary"]["approval_status"] == "not_required"
    assert "missing-or-stale-human-approval" not in by_code
    assert packet["approvals"]["required"] == []
    assert packet["approvals"]["errors"] == []
    assert review_exit_code(packet) == 1


def test_require_evidence_false_skips_evidence_and_approval_blockers(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    packet = _packet(root, require_evidence=False)
    codes = set(_by_code(packet))
    assert not any(code.startswith("missing-current-") for code in codes)
    assert "missing-or-stale-human-approval" not in codes
    assert "no-quality-evidence" not in codes
    assert "no-required-profile" not in codes


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
        finding["code"] for finding in packet["findings"] if finding["severity"] == "blocker"
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
    _assert_public_copy(finding, code)
    assert finding["paths"]
    assert all(":" in path for path in finding["paths"])


def test_suppression_markers_in_docs_do_not_emit_quality_findings(tmp_path: Path) -> None:
    """Doc/feature/text paths are documentation, not suppressible production/test surface."""
    root = _baseline_repo(tmp_path)
    (root / "NOTES.md").write_text(
        "Document how teams use pragma: no cover and # type: ignore carefully.\n"
        "Also mention @pytest.mark.skip for local debugging only.\n",
        encoding="utf-8",
    )
    (root / "guide.feature").write_text(
        "Feature: Docs\n  Scenario: mentions pragma: no mutate for humans\n",
        encoding="utf-8",
    )
    (root / "notes.txt").write_text(
        "Operators may see eslint-disable in examples; do not treat this file as code.\n",
        encoding="utf-8",
    )
    # Touch production with a real behavior change plus a matching test so the only
    # interesting question is whether documentation markers become suppressions.
    (root / "src" / "app.py").write_text(
        "def calculate(value: int) -> int:\n    return value + 2\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 3\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    codes = set(_by_code(packet))
    for code in (
        "coverage-suppression",
        "mutation-suppression",
        "lint-or-type-suppression",
        "focused-or-skipped-test",
    ):
        assert code not in codes


def test_suppression_inside_python_string_is_not_a_finding(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "src" / "app.py").write_text(
        'MESSAGE = "Teams sometimes write pragma: no cover inside docs."\n'
        "def calculate(value: int) -> int:\n"
        "    return value + 2\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 3\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    assert "coverage-suppression" not in _by_code(packet)


def test_production_assert_deletion_is_not_test_expectation_deleted(tmp_path: Path) -> None:
    """Only test-path assertion/case deletions feed test-expectation-deleted."""
    root = _baseline_repo(tmp_path)
    (root / "src" / "app.py").write_text(
        "def calculate(value: int) -> int:\n    assert value >= 0\n    return value + 1\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "with-production-assert")
    (root / "src" / "app.py").write_text(
        "def calculate(value: int) -> int:\n    return value + 1\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n"
        "def test_non_negative_docs() -> None:\n"
        "    assert calculate(0) == 1\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    assert "test-expectation-deleted" not in _by_code(packet)


def test_moved_test_expectation_is_not_reported_as_deleted(tmp_path: Path) -> None:
    """An identical test moved between test modules preserves its oracle."""
    root = _baseline_repo(tmp_path)
    original = root / "tests" / "test_app.py"
    moved = root / "tests" / "test_calculation.py"
    content = original.read_text(encoding="utf-8")
    original.unlink()
    moved.write_text(content, encoding="utf-8")

    packet = _packet(root)

    assert "test-expectation-deleted" not in _by_code(packet)


def test_module_level_test_def_deletion_is_expectation_deleted(tmp_path: Path) -> None:
    """Deleting a bare module-level test def (no assert body) is still a deleted expectation."""
    root = _baseline_repo(tmp_path)
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    value = calculate(1)\n"
        "    if value != 2:\n"
        "        raise AssertionError('bad')\n"
        "def test_secondary() -> None:\n"
        "    value = calculate(2)\n"
        "    if value != 3:\n"
        "        raise AssertionError('bad')\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "raise-style-tests")
    (root / "src" / "app.py").write_text(
        "def calculate(value: int) -> int:\n    return value + 2\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_remaining() -> None:\n"
        "    value = calculate(1)\n"
        "    if value != 3:\n"
        "        raise AssertionError('bad')\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    deleted = _by_code(packet)["test-expectation-deleted"]
    _assert_public_copy(deleted, "test-expectation-deleted")
    assert deleted["paths"] == ["tests/test_app.py"]
    assert deleted["severity"] == "blocker"


def test_weak_oracle_ignores_production_asserts(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "src" / "app.py").write_text(
        "def calculate(value: int) -> int:\n"
        "    result = value + 1\n"
        "    assert result\n"
        "    return result\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    assert "weak-test-oracle" not in _by_code(packet)


def test_proto_public_contract_without_contract_test(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "src" / "service.proto").write_text(
        'syntax = "proto3";\nmessage Ping { string id = 1; }\n',
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    contract = _by_code(packet)["public-contract-without-contract-test"]
    _assert_public_copy(contract, "public-contract-without-contract-test")
    assert contract["paths"] == ["src/service.proto"]
    assert contract["automated"] is False


def test_requirements_txt_is_dependency_surface(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "requirements.txt").write_text("requests==2.32.0\n", encoding="utf-8")
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    dep = _by_code(packet)["dependency-change"]
    _assert_public_copy(dep, "dependency-change")
    assert dep["paths"] == ["requirements.txt"]
    assert dep["severity"] == "review"


def test_swallowed_exception_in_tests_is_not_production_finding(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    try:\n"
        "        assert calculate(1) == 2\n"
        "    except Exception:\n"
        "        pass\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    assert "swallowed-broad-exception" not in _by_code(packet)


def test_production_with_tests_skips_production_without_tests_finding(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "src" / "app.py").write_text(
        "def calculate(value: int) -> int:\n    return value + 2\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 3\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    assert "production-without-tests" not in _by_code(packet)
    assert packet["summary"]["production"] >= 1
    assert packet["summary"]["tests"] >= 1


def test_invalid_risk_card_detail_preserves_exception_text(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "quality" / "change-risk.json").write_text("{not-json", encoding="utf-8")
    packet = _packet(root)
    invalid = _by_code(packet)["invalid-risk-card"]
    assert invalid["detail"] != "None"
    assert invalid["detail"].strip() != "None"
    # Something from the parse/validation path must remain observable.
    assert len(invalid["detail"]) > 4


def test_lifecycle_script_only_from_package_json(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "other.json").write_text(
        json.dumps({"scripts": {"postinstall": "echo no"}}),
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    assert "dependency-lifecycle-script-change" not in _by_code(packet)


def test_graphql_and_gql_suffixes_are_public_contracts(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    # Avoid api/route/schema path tokens so only the suffix branch classifies these.
    (root / "src" / "types.graphql").write_text("type Query { ok: Boolean }\n", encoding="utf-8")
    (root / "src" / "extra.gql").write_text("type Mutation { ok: Boolean }\n", encoding="utf-8")
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    contract = _by_code(packet)["public-contract-without-contract-test"]
    _assert_public_copy(contract, "public-contract-without-contract-test")
    assert contract["paths"] == ["src/extra.gql", "src/types.graphql"]


def test_debt_marker_after_string_todo_still_reported(tmp_path: Path) -> None:
    """A non-comment TODO must not abort scanning later genuine comment debt."""
    root = _baseline_repo(tmp_path)
    (root / "src" / "app.py").write_text(
        'NOTE = "TODO in a string must not count"\n'
        "def calculate(value: int) -> int:\n"
        "    return value + 1  # FIXME: real debt\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_app.py").write_text(
        "# Feature-Spec: Product.Calculation\n"
        "def test_calculate() -> None:\n"
        "    assert calculate(1) == 2\n",
        encoding="utf-8",
    )
    packet = _packet(root)
    debt = _by_code(packet)["new-production-debt-marker"]
    _assert_public_copy(debt, "new-production-debt-marker")
    assert debt["paths"] == ["src/app.py:3"]


def test_return_none_swallow_is_flagged(tmp_path: Path) -> None:
    root = _baseline_repo(tmp_path)
    (root / "src" / "app.py").write_text(
        "def calculate(value: int) -> int | None:\n"
        "    try:\n"
        "        return value + 1\n"
        "    except Exception:\n"
        "        return None\n",
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
    _assert_public_copy(swallowed, "swallowed-broad-exception")
    assert swallowed["paths"] == ["src/app.py:4"]


def test_current_manifested_passing_run_clears_missing_profile_evidence(tmp_path: Path) -> None:
    """AQG-OWNER-003: only a manifested fingerprint-matched pass is current."""
    from aqg.util import change_fingerprint, control_fingerprint, git_revision

    root = _baseline_repo(tmp_path)
    policy = load_policy(root)
    # Probe required profiles with a dry review, then plant a matching pass run.
    probe = analyze_review(root, policy, base="HEAD", require_evidence=True)
    required = list((probe.get("risk") or {}).get("required_execution_profiles") or [])
    assert required == ["pr"]
    profile = required[0]
    revision = git_revision(root)
    change_fp = change_fingerprint(root, "HEAD")
    control_fp = control_fingerprint(root)
    run_id = "synthetic-current-pass"
    run_dir = root / ".aqg" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "schema_version": "2",
                "run_id": run_id,
                "profile": profile,
                "status": "pass",
                "exit_code": 0,
                "revision": revision,
                "change_fingerprint": change_fp,
                "control_fingerprint": control_fp,
                "gates": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    without_manifest = analyze_review(root, policy, base="HEAD", require_evidence=True)
    assert without_manifest["evidence"] == [
        {"profile": profile, "status": "missing_or_stale", "run_id": None}
    ]
    write_run_manifest(run_dir, run_id)
    packet = analyze_review(root, policy, base="HEAD", require_evidence=True)
    assert packet["evidence"] == [{"profile": profile, "status": "current_pass", "run_id": run_id}]
    assert f"missing-current-{profile}-evidence" not in _by_code(packet)
    assert packet["summary"]["evidence_status"] == "current"
    # Functional assurance is independent of optional legacy approval records.
    assert packet["summary"]["approval_status"] == "not_required"
    assert "missing-or-stale-human-approval" not in _by_code(packet)

    # A matching summary stops being current as soon as its manifested bytes change.
    (run_dir / "summary.json").write_text(
        (run_dir / "summary.json").read_text(encoding="utf-8") + " ",
        encoding="utf-8",
    )
    tampered = analyze_review(root, policy, base="HEAD", require_evidence=True)
    assert tampered["evidence"] == [
        {"profile": profile, "status": "missing_or_stale", "run_id": None}
    ]


def test_mixed_diff_pins_public_copy_for_every_known_finding(tmp_path: Path) -> None:
    """Render-facing detail/action text stays exact even when many findings co-occur."""
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

    packet = _packet(root)
    by_code = _by_code(packet)
    for code, finding in by_code.items():
        if code in DETAILS or code in ACTIONS:
            _assert_public_copy(finding, code)
    # Markdown and HTML still carry the exact public copy.
    markdown = _markdown(packet)
    html = _html(packet)
    for code in (
        "policy-plane-change",
        "human-review-plane-change",
        "focused-or-skipped-test",
        "swallowed-broad-exception",
        "public-contract-without-contract-test",
        "dependency-change",
        "expected-output-change",
        "weak-test-oracle",
        "new-production-debt-marker",
    ):
        finding = by_code[code]
        assert finding["detail"] in markdown
        assert finding["action"] in markdown
        assert finding["title"] in html
