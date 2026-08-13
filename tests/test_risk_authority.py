# Feature-Spec: AgentQualityGauntlet AQG-CORE-007 AQG-CORE-008
from __future__ import annotations

import json
from pathlib import Path

import pytest

from aqg.policy import AUTHORITY_TRIGGER_NAMES, load_policy, risk_card_errors
from aqg.schema_contracts import validate_instance, validate_named_schema


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src" / "aqg" / "templates" / "common" / "change-risk.json"
TEMPLATE_SCHEMA = (
    ROOT
    / "src"
    / "aqg"
    / "templates"
    / "common"
    / "schemas"
    / "change-risk.schema.json"
)


def _template_card() -> dict[str, object]:
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def test_new_template_declares_every_human_authority_trigger_false() -> None:
    card = _template_card()
    assert card["authority_triggers"] == {
        name: False for name in AUTHORITY_TRIGGER_NAMES
    }
    assert risk_card_errors(card, load_policy(ROOT)) == []
    assert validate_named_schema(ROOT, "change-risk", card) == []


def test_legacy_v1_card_without_authority_triggers_remains_valid() -> None:
    card = _template_card()
    del card["authority_triggers"]
    assert card["schema_version"] == "1"
    assert risk_card_errors(card, load_policy(ROOT)) == []
    assert validate_named_schema(ROOT, "change-risk", card) == []


@pytest.mark.parametrize(
    ("triggers", "runtime_error", "schema_error"),
    [
        (
            {"guardrail_weakening": False},
            "risk card is missing authority trigger 'paid_external_action'",
            "$.authority_triggers: missing required property 'paid_external_action'",
        ),
        (
            {name: "false" for name in AUTHORITY_TRIGGER_NAMES},
            "authority trigger 'guardrail_weakening' must be boolean",
            "$.authority_triggers.guardrail_weakening: expected type 'boolean'",
        ),
        (
            {**{name: False for name in AUTHORITY_TRIGGER_NAMES}, "surprise": False},
            "unknown authority trigger 'surprise'",
            "$.authority_triggers: unexpected property 'surprise'",
        ),
    ],
)
def test_declared_authority_triggers_fail_closed(
    triggers: dict[str, object], runtime_error: str, schema_error: str
) -> None:
    card = _template_card()
    card["authority_triggers"] = triggers
    assert runtime_error in risk_card_errors(card, load_policy(ROOT))
    assert schema_error in validate_named_schema(ROOT, "change-risk", card)


def test_installed_and_source_change_risk_schemas_remain_identical() -> None:
    installed_schema = json.loads(
        (ROOT / "quality" / "schemas" / "change-risk.schema.json").read_text(
            encoding="utf-8"
        )
    )
    template_schema = json.loads(TEMPLATE_SCHEMA.read_text(encoding="utf-8"))
    assert installed_schema == template_schema
    assert validate_instance(_template_card(), template_schema) == []
