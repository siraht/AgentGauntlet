"""Characterization and property coverage for the deterministic Gherkin parser.

These tests lock the public parse_feature contract before structural extraction:
codes, severities, messages, line numbers, finding order, and IR shape must stay
stable for acceptance mutation consumers and lint_features.
"""

from __future__ import annotations

import copy
import itertools
from pathlib import Path

import pytest

from aqg.checks import parse_feature

KNOWN_ERROR_CODES = frozenset(
    {
        "multiple-features",
        "examples-outside-scenario",
        "table-outside-examples",
        "duplicate-example-header",
        "example-width",
        "step-outside-scenario",
        "unsupported-gherkin",
        "missing-feature",
        "missing-scenario",
        "incomplete-scenario",
        "missing-example-value",
        "unused-example-value",
    }
)

UNSUPPORTED_REMEDIATION = (
    "Use the deterministic subset Feature, Background, Scenario, Scenario Outline, "
    "Examples, Given, When, Then, and And."
)


def _write_feature(tmp_path: Path, text: str, name: str = "sample.feature") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _findings(path: Path) -> list[dict[str, object]]:
    _feature, findings = parse_feature(path)
    return [finding.as_dict() for finding in findings]


def _finding(
    code: str,
    message: str,
    path: Path,
    line: int | None = None,
    remediation: str | None = None,
) -> dict[str, object]:
    return {
        "code": code,
        "severity": "error",
        "message": message,
        "path": str(path),
        "line": line,
        "remediation": remediation,
        "fingerprint": None,
    }


def test_valid_basic_scenario_structure_and_no_findings(tmp_path: Path) -> None:
    path = _write_feature(
        tmp_path,
        "Feature: Hello\n"
        "  Scenario: works\n"
        "    Given a start\n"
        "    When action happens\n"
        "    Then outcome is visible\n",
    )
    feature, findings = parse_feature(path)
    assert findings == []
    assert feature == {
        "name": "Hello",
        "background": [],
        "scenarios": [
            {
                "name": "works",
                "steps": [
                    {
                        "keyword": "Given",
                        "text": "a start",
                        "line": 3,
                        "parameters": [],
                    },
                    {
                        "keyword": "When",
                        "text": "action happens",
                        "line": 4,
                        "parameters": [],
                    },
                    {
                        "keyword": "Then",
                        "text": "outcome is visible",
                        "line": 5,
                        "parameters": [],
                    },
                ],
                "examples": [],
            }
        ],
    }


def test_valid_background_outline_examples_and_placeholders(tmp_path: Path) -> None:
    path = _write_feature(
        tmp_path,
        "Feature: Setup\n"
        "  Background:\n"
        "    Given env ready\n"
        "  Scenario Outline: scope\n"
        '    Given history "<history>"\n'
        "    When setup runs\n"
        '    Then scope is "<scope>"\n'
        "  Examples:\n"
        "    | history | scope |\n"
        "    | none    | full  |\n",
    )
    feature, findings = parse_feature(path)
    assert findings == []
    assert feature == {
        "name": "Setup",
        "background": [
            {
                "keyword": "Given",
                "text": "env ready",
                "line": 3,
                "parameters": [],
            }
        ],
        "scenarios": [
            {
                "name": "scope",
                "steps": [
                    {
                        "keyword": "Given",
                        "text": 'history "<history>"',
                        "line": 5,
                        "parameters": ["history"],
                    },
                    {
                        "keyword": "When",
                        "text": "setup runs",
                        "line": 6,
                        "parameters": [],
                    },
                    {
                        "keyword": "Then",
                        "text": 'scope is "<scope>"',
                        "line": 7,
                        "parameters": ["scope"],
                    },
                ],
                "examples": [{"history": "none", "scope": "full"}],
            }
        ],
    }


def test_valid_comments_blank_lines_and_and_steps_are_skipped_or_kept(tmp_path: Path) -> None:
    path = _write_feature(
        tmp_path,
        "# comment\nFeature: X\n\n  Scenario: s\n    Given a\n    When b\n    Then c\n    And d\n",
    )
    feature, findings = parse_feature(path)
    assert findings == []
    assert feature is not None
    assert feature["name"] == "X"
    assert [step["keyword"] for step in feature["scenarios"][0]["steps"]] == [
        "Given",
        "When",
        "Then",
        "And",
    ]
    assert [step["line"] for step in feature["scenarios"][0]["steps"]] == [5, 6, 7, 8]


def test_project_setup_feature_is_accepted_without_findings() -> None:
    path = Path("features/AgentQualityGauntlet.Setup.feature")
    feature, findings = parse_feature(path)
    assert findings == []
    assert feature is not None
    assert feature["name"] == "Portable Agent Quality Gauntlet setup"
    assert [scenario["name"] for scenario in feature["scenarios"]] == [
        "setup selects the expected enforcement scope",
        "browser binaries remain opt-in",
        "incomplete dependency inventory fails closed",
    ]
    outline = feature["scenarios"][0]
    assert outline["examples"] == [
        {"history": "none", "scope": "full"},
        {"history": "present", "scope": "changed"},
    ]
    assert outline["steps"][0]["parameters"] == ["history"]
    assert outline["steps"][2]["parameters"] == ["scope"]


def test_multiple_features_error_overwrites_name_and_keeps_order(tmp_path: Path) -> None:
    path = _write_feature(
        tmp_path,
        "Feature: One\nFeature: Two\n  Scenario: s\n    When a\n    Then b\n",
    )
    feature, findings = parse_feature(path)
    assert feature is not None
    assert feature["name"] == "Two"
    assert [item.as_dict() for item in findings] == [
        _finding(
            "multiple-features",
            "One file must contain exactly one Feature declaration.",
            path,
            line=2,
        )
    ]


def test_examples_outside_scenario_then_tables_and_missing_scenario(tmp_path: Path) -> None:
    path = _write_feature(
        tmp_path,
        "Feature: X\nExamples:\n  | a |\n  | 1 |\n",
    )
    assert _findings(path) == [
        _finding(
            "examples-outside-scenario",
            "Examples must be inside a scenario.",
            path,
            line=2,
        ),
        _finding(
            "table-outside-examples",
            "Table rows are allowed only inside Examples.",
            path,
            line=3,
        ),
        _finding(
            "table-outside-examples",
            "Table rows are allowed only inside Examples.",
            path,
            line=4,
        ),
        _finding(
            "missing-scenario",
            "At least one scenario is required.",
            path,
            line=1,
        ),
    ]


def test_table_outside_examples_error(tmp_path: Path) -> None:
    path = _write_feature(
        tmp_path,
        "Feature: X\n  Scenario: s\n    When a\n    Then b\n    | a |\n",
    )
    assert _findings(path) == [
        _finding(
            "table-outside-examples",
            "Table rows are allowed only inside Examples.",
            path,
            line=5,
        )
    ]


def test_duplicate_example_header_still_accepts_later_row_via_dict_collapse(
    tmp_path: Path,
) -> None:
    path = _write_feature(
        tmp_path,
        "Feature: X\n"
        "  Scenario Outline: s\n"
        "    When use <a>\n"
        "    Then ok\n"
        "  Examples:\n"
        "    | a | a |\n"
        "    | 1 | 2 |\n",
    )
    feature, findings = parse_feature(path)
    assert feature is not None
    assert feature["scenarios"][0]["examples"] == [{"a": "2"}]
    assert [item.as_dict() for item in findings] == [
        _finding(
            "duplicate-example-header",
            "Examples headers must be unique.",
            path,
            line=6,
        )
    ]


def test_example_width_mismatch_and_missing_placeholder_column(tmp_path: Path) -> None:
    path = _write_feature(
        tmp_path,
        "Feature: X\n"
        "  Scenario Outline: s\n"
        "    When use <a>\n"
        "    Then ok\n"
        "  Examples:\n"
        "    | a |\n"
        "    | 1 | 2 |\n",
    )
    feature, findings = parse_feature(path)
    assert feature is not None
    assert feature["scenarios"][0]["examples"] == []
    assert [item.as_dict() for item in findings] == [
        _finding(
            "example-width",
            "Examples row width does not match the header.",
            path,
            line=7,
        ),
        _finding(
            "missing-example-value",
            "Placeholder <a> has no Examples column in scenario 's'.",
            path,
            line=None,
        ),
    ]


def test_step_outside_scenario_error(tmp_path: Path) -> None:
    path = _write_feature(
        tmp_path,
        "Feature: X\n  Given orphan\n  Scenario: s\n    When a\n    Then b\n",
    )
    assert _findings(path) == [
        _finding(
            "step-outside-scenario",
            "Step is outside Background or Scenario.",
            path,
            line=2,
        )
    ]


def test_unsupported_gherkin_error_includes_remediation(tmp_path: Path) -> None:
    path = _write_feature(
        tmp_path,
        "Feature: X\n  Scenario: s\n    Givven bad\n    When a\n    Then b\n",
    )
    assert _findings(path) == [
        _finding(
            "unsupported-gherkin",
            "Unsupported or misspelled Gherkin syntax: Givven bad",
            path,
            line=3,
            remediation=UNSUPPORTED_REMEDIATION,
        )
    ]


def test_missing_feature_declaration_error(tmp_path: Path) -> None:
    path = _write_feature(
        tmp_path,
        "Scenario: s\n  When a\n  Then b\n",
    )
    feature, findings = parse_feature(path)
    assert feature is not None
    assert feature["name"] == ""
    assert [item.as_dict() for item in findings] == [
        _finding(
            "missing-feature",
            "Feature declaration is required.",
            path,
            line=1,
        )
    ]


def test_missing_scenario_error(tmp_path: Path) -> None:
    path = _write_feature(tmp_path, "Feature: X\n")
    assert _findings(path) == [
        _finding(
            "missing-scenario",
            "At least one scenario is required.",
            path,
            line=1,
        )
    ]


@pytest.mark.parametrize(
    ("body", "scenario_name"),
    [
        ("Feature: X\n  Scenario: only given\n    Given a\n", "only given"),
        ("Feature: X\n  Scenario: only when\n    When a\n", "only when"),
        ("Feature: X\n  Scenario: only then\n    Then b\n", "only then"),
    ],
)
def test_incomplete_scenario_requires_when_and_then(
    tmp_path: Path, body: str, scenario_name: str
) -> None:
    path = _write_feature(tmp_path, body)
    assert _findings(path) == [
        _finding(
            "incomplete-scenario",
            f"Scenario {scenario_name!r} needs at least one When and Then.",
            path,
            line=None,
        )
    ]


def test_examples_after_background_without_scenario_are_rejected(tmp_path: Path) -> None:
    path = _write_feature(
        tmp_path,
        "Feature: X\n  Background:\n    Given prep\n  Examples:\n    | a |\n    | 1 |\n",
    )
    assert _findings(path) == [
        _finding(
            "examples-outside-scenario",
            "Examples must be inside a scenario.",
            path,
            line=4,
        ),
        _finding(
            "table-outside-examples",
            "Table rows are allowed only inside Examples.",
            path,
            line=5,
        ),
        _finding(
            "table-outside-examples",
            "Table rows are allowed only inside Examples.",
            path,
            line=6,
        ),
        _finding(
            "missing-scenario",
            "At least one scenario is required.",
            path,
            line=1,
        ),
    ]


def test_scenario_name_keeps_text_after_first_colon(tmp_path: Path) -> None:
    path = _write_feature(
        tmp_path,
        "Feature: X\n  Scenario: name: with colon\n    When a\n    Then b\n",
    )
    feature, findings = parse_feature(path)
    assert findings == []
    assert feature is not None
    assert feature["scenarios"][0]["name"] == "name: with colon"


def test_missing_and_unused_example_values_are_sorted_and_ordered(tmp_path: Path) -> None:
    path = _write_feature(
        tmp_path,
        "Feature: X\n"
        "  Scenario Outline: s\n"
        "    When use <value>\n"
        "    Then ok <other>\n"
        "  Examples:\n"
        "    | value | unused |\n"
        "    | 1 | x |\n",
    )
    assert _findings(path) == [
        _finding(
            "missing-example-value",
            "Placeholder <other> has no Examples column in scenario 's'.",
            path,
            line=None,
        ),
        _finding(
            "unused-example-value",
            "Examples column 'unused' is not connected to a step in scenario 's'.",
            path,
            line=None,
        ),
    ]


def test_unused_example_value_alone(tmp_path: Path) -> None:
    path = _write_feature(
        tmp_path,
        "Feature: X\n"
        "  Scenario Outline: s\n"
        "    When use <value>\n"
        "    Then ok\n"
        "  Examples:\n"
        "    | value | unused |\n"
        "    | 1 | x |\n",
    )
    assert _findings(path) == [
        _finding(
            "unused-example-value",
            "Examples column 'unused' is not connected to a step in scenario 's'.",
            path,
            line=None,
        )
    ]


def test_missing_example_value_alone(tmp_path: Path) -> None:
    path = _write_feature(
        tmp_path,
        "Feature: X\n"
        "  Scenario Outline: s\n"
        "    When use <value>\n"
        "    Then ok\n"
        "  Examples:\n"
        "    | other |\n"
        "    | 1 |\n",
    )
    assert _findings(path) == [
        _finding(
            "missing-example-value",
            "Placeholder <value> has no Examples column in scenario 's'.",
            path,
            line=None,
        ),
        _finding(
            "unused-example-value",
            "Examples column 'other' is not connected to a step in scenario 's'.",
            path,
            line=None,
        ),
    ]


def test_public_signature_returns_feature_dict_and_finding_list(tmp_path: Path) -> None:
    path = _write_feature(
        tmp_path,
        "Feature: Hello\n  Scenario: works\n    When action happens\n    Then outcome is visible\n",
    )
    result = parse_feature(path)
    assert isinstance(result, tuple)
    assert len(result) == 2
    feature, findings = result
    assert isinstance(feature, dict)
    assert isinstance(findings, list)
    assert all(hasattr(item, "as_dict") for item in findings)


@pytest.mark.parametrize(
    ("body", "expected_codes"),
    [
        (
            "Feature: One\nFeature: Two\n  Scenario: s\n    When a\n    Then b\n",
            ["multiple-features"],
        ),
        (
            "Feature: X\nExamples:\n  | a |\n",
            ["examples-outside-scenario", "table-outside-examples", "missing-scenario"],
        ),
        (
            "Feature: X\n  Scenario: s\n    When a\n    Then b\n    | a |\n",
            ["table-outside-examples"],
        ),
        (
            "Feature: X\n  Scenario Outline: s\n    When use <a>\n    Then ok\n"
            "  Examples:\n    | a | a |\n    | 1 | 2 |\n",
            ["duplicate-example-header"],
        ),
        (
            "Feature: X\n  Scenario Outline: s\n    When use <a>\n    Then ok\n"
            "  Examples:\n    | a |\n    | 1 | 2 |\n",
            ["example-width", "missing-example-value"],
        ),
        (
            "Feature: X\n  Given orphan\n  Scenario: s\n    When a\n    Then b\n",
            ["step-outside-scenario"],
        ),
        (
            "Feature: X\n  Scenario: s\n    Givven bad\n    When a\n    Then b\n",
            ["unsupported-gherkin"],
        ),
        (
            "Scenario: s\n  When a\n  Then b\n",
            ["missing-feature"],
        ),
        (
            "Feature: X\n",
            ["missing-scenario"],
        ),
        (
            "Feature: X\n  Scenario: only given\n    Given a\n",
            ["incomplete-scenario"],
        ),
        (
            "Feature: X\n  Scenario Outline: s\n    When use <value>\n    Then ok\n"
            "  Examples:\n    | other |\n    | 1 |\n",
            ["missing-example-value", "unused-example-value"],
        ),
        (
            "Feature: X\n  Scenario Outline: s\n    When use <value>\n    Then ok\n"
            "  Examples:\n    | value | unused |\n    | 1 | x |\n",
            ["unused-example-value"],
        ),
    ],
)
def test_every_supported_error_family_code_order(
    tmp_path: Path, body: str, expected_codes: list[str]
) -> None:
    path = _write_feature(tmp_path, body)
    codes = [item["code"] for item in _findings(path)]
    assert codes == expected_codes
    assert set(codes) <= KNOWN_ERROR_CODES


def test_property_parse_is_deterministic_for_fixed_texts(tmp_path: Path) -> None:
    samples = [
        "Feature: Hello\n  Scenario: works\n    When action happens\n    Then outcome is visible\n",
        "Feature: X\n  Scenario: s\n    Givven bad\n    When a\n    Then b\n",
        "Feature: X\n  Scenario Outline: s\n    When use <value>\n    Then ok\n"
        "  Examples:\n    | value | unused |\n    | 1 | x |\n",
        "Feature: One\nFeature: Two\n  Scenario: s\n    When a\n    Then b\n",
        "# c\n\nFeature: X\n  Background:\n    Given prep\n  Scenario: s\n"
        "    Given a <x>\n    When b\n    Then c <x>\n  Examples:\n    | x |\n    | 1 |\n",
    ]
    for index, text in enumerate(samples):
        path = _write_feature(tmp_path, text, name=f"det-{index}.feature")
        first = parse_feature(path)
        second = parse_feature(path)
        assert first[0] == second[0]
        assert [item.as_dict() for item in first[1]] == [item.as_dict() for item in second[1]]


def test_property_valid_keyword_permutations_remain_finding_free(tmp_path: Path) -> None:
    step_orders = [
        ("Given", "When", "Then"),
        ("When", "Then"),
        ("Given", "When", "Then", "And"),
        ("When", "And", "Then", "And"),
    ]
    for index, keywords in enumerate(step_orders):
        steps = "\n".join(f"    {keyword} step {offset}" for offset, keyword in enumerate(keywords))
        text = f"Feature: F{index}\n  Scenario: S{index}\n{steps}\n"
        path = _write_feature(tmp_path, text, name=f"valid-{index}.feature")
        feature, findings = parse_feature(path)
        assert findings == []
        assert feature is not None
        assert feature["name"] == f"F{index}"
        assert [step["keyword"] for step in feature["scenarios"][0]["steps"]] == list(keywords)


def test_property_findings_are_errors_with_known_codes_and_stable_path(
    tmp_path: Path,
) -> None:
    invalid_bodies = [
        "Feature: X\n  Scenario: s\n    Givven bad\n",
        "Feature: X\n",
        "Scenario: s\n  When a\n  Then b\n",
        "Feature: X\n  Scenario Outline: s\n    When use <a>\n    Then ok\n"
        "  Examples:\n    | b |\n    | 1 |\n",
        "Feature: A\nFeature: B\n  Scenario: s\n    When a\n    Then b\n",
    ]
    for index, body in enumerate(invalid_bodies):
        path = _write_feature(tmp_path, body, name=f"invalid-{index}.feature")
        _feature, findings = parse_feature(path)
        assert findings, body
        for finding in findings:
            payload = finding.as_dict()
            assert payload["severity"] == "error"
            assert payload["code"] in KNOWN_ERROR_CODES
            assert payload["path"] == str(path)
            assert payload["fingerprint"] is None
            assert isinstance(payload["message"], str) and payload["message"]


def test_property_placeholder_column_alignment_matrix(tmp_path: Path) -> None:
    placeholders = ("alpha", "beta")
    columns = ("alpha", "beta", "gamma")
    for present in itertools.product([False, True], repeat=len(columns)):
        active_columns = [name for name, keep in zip(columns, present, strict=True) if keep]
        header = " | ".join(active_columns) if active_columns else "noop"
        row = " | ".join("1" for _ in active_columns) if active_columns else "1"
        if not active_columns:
            # A no-column Examples table is not a supported empty form; keep one dummy column.
            header = "noop"
            row = "1"
            active_columns = ["noop"]
        text = (
            "Feature: Matrix\n"
            "  Scenario Outline: aligned\n"
            '    When values "<alpha>" and "<beta>"\n'
            "    Then done\n"
            "  Examples:\n"
            f"    | {header} |\n"
            f"    | {row} |\n"
        )
        path = _write_feature(
            tmp_path,
            text,
            name=f"matrix-{''.join('1' if flag else '0' for flag in present)}.feature",
        )
        codes = [item["code"] for item in _findings(path)]
        missing = [name for name in placeholders if name not in active_columns]
        unused = [name for name in active_columns if name not in placeholders]
        expected = ["missing-example-value" for _ in sorted(missing)]
        expected.extend("unused-example-value" for _ in sorted(unused))
        assert codes == expected


def test_property_deep_copy_of_returned_feature_is_independent(tmp_path: Path) -> None:
    path = _write_feature(
        tmp_path,
        "Feature: Hello\n  Scenario: works\n    When action happens\n    Then outcome is visible\n",
    )
    feature, _findings_list = parse_feature(path)
    assert feature is not None
    cloned = copy.deepcopy(feature)
    feature["name"] = "mutated"
    feature["scenarios"][0]["steps"].clear()
    again, _ = parse_feature(path)
    assert again is not None
    assert again["name"] == "Hello"
    assert again["scenarios"][0]["steps"]
    assert cloned["name"] == "Hello"
