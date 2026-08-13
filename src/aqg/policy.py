"""Policy loading, validation, risk resolution, and path protection."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover
    raise RuntimeError("AQG requires Python 3.11+") from exc

from .constants import PLACEHOLDER, RISK_ORDER
from .errors import ConfigurationError
from .util import read_json

AUTHORITY_TRIGGER_NAMES = (
    "guardrail_weakening",
    "paid_external_action",
    "private_data_exposure",
    "irreversible_execution",
)

POLICY_TEMPLATE = r"""version = 2
initialized = true
default_risk_profile = "standard"
default_execution_profile = "fast"

[policy]
owner = "{owner}"
policy_maintenance_env = "AQG_POLICY_MAINTENANCE"
maintenance_request_env = "AQG_MAINTENANCE_REQUEST"
golden_update_env = "AQG_ALLOW_GOLDEN_UPDATE"

protected_paths = [
  "AGENTS.md",
  "CLAUDE.md",
  "QUALITY.md",
  "KEYSTONE.md",
  "aqg",
  "quality/policy.toml",
  "quality/project.json",
  "quality/onboarding.json",
  "quality/qg.py",
  "quality/_aqg/**",
  "quality/config/**",
  "quality/tools/**/package.json",
  "quality/tools/**/package-lock.json",
  "quality/tools/**/requirements.lock.txt",
  "quality/tools/**/requirements*.txt",
  "quality/adapters/**",
  "quality/baselines/**",
  "quality/waivers/**",
  "quality/approvals/**",
  "quality/guidance/**",
  "quality/golden/expected/**",
  "quality/schemas/**",
  "quality/conformance/**",
  "quality/github/**",
  ".agents/skills/quality-gauntlet/**",
  ".claude/settings.json",
  ".claude/skills/quality-gauntlet/**",
  ".claude/agents/quality-verifier.md",
  ".codex/hooks.json",
  ".codex/agents/quality-verifier.toml",
  ".github/workflows/**",
  ".github/CODEOWNERS",
]

human_review_paths = [
  "quality/change-risk.json",
  "KEYSTONE.md",
  "feature-spec/**",
  "features/**",
  "qa/procedures/**",
  "**/golden/**",
  "**/goldens/**",
  "**/snapshots/**",
  "**/__snapshots__/**",
  "**/migrations/**",
  "**/schema/**",
  "**/openapi/**",
  "**/package-lock.json",
  "**/pnpm-lock.yaml",
  "**/yarn.lock",
  "**/uv.lock",
  "**/requirements*.txt",
]

blocked_command_regex = [
  "\\bAQG_POLICY_MAINTENANCE\\s*=",
  "\\bAQG_ALLOW_GOLDEN_UPDATE\\s*=",
  "(^|[;&|])\\s*rm\\s+-[^\\n]*r[^\\n]*f",
  "\\bgit\\s+reset\\s+--hard\\b",
  "\\bgit\\s+clean\\s+-[^\\n]*f",
  "\\bgit\\s+(checkout|restore)\\s+--\\s+",
  "\\b(drop\\s+database|drop\\s+table|truncate\\s+table)\\b",
  "\\bcurl\\b[^\\n|]*\\|\\s*(sh|bash)\\b",
  "\\bwget\\b[^\\n|]*\\|\\s*(sh|bash)\\b",
]

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

[hooks]
enforce_on_stop = false
stop_profile = "fast"

[risk_profiles.experiment]
required_execution_profiles = ["fast"]
requires_human_behavior_review = false
requires_read_only_verifier = false
requires_human_code_review = false
requires_manual_qa = false

[risk_profiles.standard]
required_execution_profiles = ["pr"]
requires_human_behavior_review = true
requires_read_only_verifier = false
requires_human_code_review = false
requires_manual_qa = false

[risk_profiles.high_assurance]
required_execution_profiles = ["deep"]
requires_human_behavior_review = true
requires_read_only_verifier = true
requires_human_code_review = false
requires_manual_qa = true

[risk_profiles.critical]
required_execution_profiles = ["release"]
requires_human_behavior_review = true
requires_read_only_verifier = true
requires_human_code_review = true
requires_manual_qa = true

[profiles.inner]
gates = ["format", "lint", "typecheck"]
max_total_seconds = 60

[profiles.fast]
gates = ["format", "lint", "typecheck", "test_integrity", "unit", "structure", "secrets"]
max_total_seconds = 600

[profiles.pr]
gates = ["format", "lint", "typecheck", "test_integrity", "unit", "structure", "coverage", "contracts", "acceptance", "review", "security_fast", "policy_maintenance", "assurance"]
max_total_seconds = 1800

[profiles.deep]
gates = ["format", "lint", "typecheck", "test_integrity", "unit", "structure", "coverage", "contracts", "acceptance", "golden", "mutation_changed", "mutation_acceptance", "review", "security_fast", "security_deep", "supply_chain", "performance", "policy_maintenance", "assurance"]
max_total_seconds = 10800

[profiles.release]
gates = ["format", "lint", "typecheck", "test_integrity", "reproducible_build", "unit", "structure", "coverage", "contracts", "acceptance", "golden", "mutation_changed", "mutation_acceptance", "review", "security_fast", "security_deep", "supply_chain", "performance", "policy_maintenance", "assurance", "release_readiness"]
max_total_seconds = 14400

{gates}
"""

GATE_NAMES = [
    "format",
    "lint",
    "typecheck",
    "test_integrity",
    "unit",
    "structure",
    "coverage",
    "contracts",
    "acceptance",
    "golden",
    "mutation_changed",
    "mutation_acceptance",
    "review",
    "policy_maintenance",
    "assurance",
    "secrets",
    "security_fast",
    "security_deep",
    "supply_chain",
    "performance",
    "reproducible_build",
    "release_readiness",
]

GATE_TIMEOUTS = {
    "format": 180,
    "lint": 300,
    "typecheck": 600,
    "test_integrity": 300,
    "unit": 1200,
    "structure": 600,
    "coverage": 1800,
    "contracts": 1200,
    "acceptance": 2400,
    "golden": 2400,
    "mutation_changed": 7200,
    "mutation_acceptance": 7200,
    "review": 300,
    "policy_maintenance": 300,
    "assurance": 300,
    "secrets": 300,
    "security_fast": 900,
    "security_deep": 3600,
    "supply_chain": 900,
    "performance": 3600,
    "reproducible_build": 3600,
    "release_readiness": 1800,
}


def render_policy(owner: str) -> str:
    blocks: list[str] = []
    for name in GATE_NAMES:
        clean = f'clean_paths = [".aqg/work/{name}"]'
        blocks.append(
            f"[gates.{name}]\n"
            f'command = "python3 quality/qg.py adapter {name}"\n'
            f"timeout_seconds = {GATE_TIMEOUTS[name]}\n"
            f"{clean}\n"
            "quality_failure_exit_codes = [1]\n"
        )
    return POLICY_TEMPLATE.format(owner=owner.replace('"', "'"), gates="\n".join(blocks))


def load_policy(root: Path) -> dict[str, Any]:
    trusted = os.environ.get("AQG_TRUSTED_POLICY_PATH")
    if os.environ.get("AQG_TRUSTED_MODE") == "1" and trusted:
        path = Path(trusted)
        if not path.is_absolute():
            raise ConfigurationError("AQG_TRUSTED_POLICY_PATH must be absolute")
    else:
        path = root / "quality" / "policy.toml"
    try:
        with path.open("rb") as handle:
            policy = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"missing policy: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"invalid TOML in {path}: {exc}") from exc
    if policy.get("version") not in {1, 2}:
        raise ConfigurationError("quality policy version must be 1 or 2")
    return policy


def _profile_references(
    profile_name: str, profile: Any, gates: dict[str, Any]
) -> tuple[list[str], set[str]]:
    gate_names = profile.get("gates") if isinstance(profile, dict) else None
    if not isinstance(gate_names, list) or not gate_names:
        return [f"profile {profile_name!r} has no gates"], set()
    errors: list[str] = []
    referenced: set[str] = set()
    for gate_name in gate_names:
        if not isinstance(gate_name, str):
            errors.append(f"profile {profile_name!r} has a non-string gate")
        else:
            referenced.add(gate_name)
            if gate_name not in gates:
                errors.append(f"profile {profile_name!r} references missing gate {gate_name!r}")
    return errors, referenced


def _profile_gate_references(
    profiles: Any, gates: Any
) -> tuple[list[str], dict[str, Any], dict[str, Any], set[str]]:
    errors: list[str] = []
    if not isinstance(profiles, dict) or not profiles:
        errors.append("no execution profiles are configured")
        profiles = {}
    if not isinstance(gates, dict) or not gates:
        errors.append("no gates are configured")
        gates = {}
    referenced: set[str] = set()
    for profile_name, profile in profiles.items():
        profile_errors, profile_references = _profile_references(profile_name, profile, gates)
        errors.extend(profile_errors)
        referenced.update(profile_references)
    return errors, profiles, gates, referenced


def _gate_contract_errors(name: str, gate: Any) -> list[str]:
    mapping = gate if isinstance(gate, dict) else {}
    errors: list[str] = []
    command = mapping.get("command")
    if not isinstance(command, str) or not command.strip() or PLACEHOLDER in command:
        errors.append(f"gate {name!r} has an unconfigured command")
    timeout = mapping.get("timeout_seconds", 0)
    if not isinstance(timeout, int) or timeout <= 0:
        errors.append(f"gate {name!r} needs a positive timeout_seconds")
    clean_paths = mapping.get("clean_paths", [])
    if not isinstance(clean_paths, list) or not all(
        isinstance(value, str) for value in clean_paths
    ):
        errors.append(f"gate {name!r} clean_paths must be a string array")
    return errors


def _validate_referenced_gates(gates: dict[str, Any], referenced: set[str]) -> list[str]:
    errors: list[str] = []
    for name in sorted(referenced):
        errors.extend(_gate_contract_errors(name, gates.get(name)))
    return errors


def _validate_policy_controls(policy_cfg: Any) -> list[str]:
    mapping = policy_cfg if isinstance(policy_cfg, dict) else {}
    errors: list[str] = []
    for key in ("protected_paths", "human_review_paths", "blocked_command_regex"):
        values = mapping.get(key, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            errors.append(f"policy.{key} must be a string array")
    expressions = mapping.get("blocked_command_regex", [])
    if not isinstance(expressions, list):
        return errors
    for expression in expressions:
        if not isinstance(expression, str):
            continue
        try:
            re.compile(expression, re.IGNORECASE)
        except re.error as exc:
            errors.append(f"invalid blocked command regex {expression!r}: {exc}")
    return errors


def _validate_risk_profiles(risk_profiles: Any, profiles: dict[str, Any]) -> list[str]:
    mapping = risk_profiles if isinstance(risk_profiles, dict) else {}
    errors: list[str] = []
    for name in RISK_ORDER:
        config = mapping.get(name)
        if not isinstance(config, dict):
            errors.append(f"missing risk profile {name!r}")
            continue
        required = config.get("required_execution_profiles")
        if not isinstance(required, list) or not required:
            errors.append(f"risk profile {name!r} has no required execution profiles")
        elif any(profile not in profiles for profile in required):
            errors.append(f"risk profile {name!r} references a missing execution profile")
    return errors


def validate_policy(policy: dict[str, Any], *, require_initialized: bool = True) -> list[str]:
    errors = (
        ["policy initialized=false; run qg init or qg bootstrap"]
        if require_initialized and not policy.get("initialized", False)
        else []
    )
    reference_errors, profiles, gates, referenced = _profile_gate_references(
        policy.get("profiles"), policy.get("gates")
    )
    errors.extend(reference_errors)
    errors.extend(_validate_referenced_gates(gates, referenced))
    policy_cfg = policy.get("policy", {})
    errors.extend(_validate_policy_controls(policy_cfg))
    errors.extend(_validate_risk_profiles(policy.get("risk_profiles"), profiles))
    return errors


def safe_remove(root: Path, configured_path: str) -> None:
    target = (root / configured_path).resolve()
    resolved = root.resolve()
    try:
        target.relative_to(resolved)
    except ValueError as exc:
        raise ConfigurationError(
            f"refusing to clean path outside repository: {configured_path}"
        ) from exc
    if target == resolved:
        raise ConfigurationError("refusing to clean repository root")
    if target.is_symlink() or target.is_file():
        target.unlink(missing_ok=True)
    elif target.is_dir():
        shutil.rmtree(target)


def load_risk_card(root: Path, card_path: str) -> dict[str, Any]:
    path = Path(card_path)
    if not path.is_absolute():
        path = root / path
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ConfigurationError("change-risk card must be a JSON object")
    return payload


def _risk_factor_errors(factors: Any, policy: dict[str, Any]) -> list[str]:
    if not isinstance(factors, dict):
        return []
    known = policy.get("risk_rules", {}).get("minimum_profile_by_factor", {})
    errors: list[str] = []
    for name, value in factors.items():
        if name not in known:
            errors.append(f"unknown risk factor {name!r}")
        if not isinstance(value, bool):
            errors.append(f"risk factor {name!r} must be boolean")
    errors.extend(
        f"risk card is missing risk factor {name!r}" for name in known if name not in factors
    )
    return errors


def _authority_trigger_errors(card: dict[str, Any]) -> list[str]:
    if "authority_triggers" not in card:
        return []
    triggers = card["authority_triggers"]
    if not isinstance(triggers, dict):
        return ["risk card field 'authority_triggers' must be dict"]
    errors: list[str] = []
    for name, value in triggers.items():
        if name not in AUTHORITY_TRIGGER_NAMES:
            errors.append(f"unknown authority trigger {name!r}")
        if not isinstance(value, bool):
            errors.append(f"authority trigger {name!r} must be boolean")
    errors.extend(
        f"risk card is missing authority trigger {name!r}"
        for name in AUTHORITY_TRIGGER_NAMES
        if name not in triggers
    )
    return errors


def risk_card_errors(card: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    required: dict[str, type] = {
        "schema_version": str,
        "summary": str,
        "risk_profile": str,
        "production_scope": bool,
        "reversible": bool,
        "blast_radius": str,
        "behavior_changes": list,
        "behavior_preserved": list,
        "risk_factors": dict,
        "failure_detection": str,
        "rollback": str,
        "human_review": list,
    }
    errors = [
        f"risk card field {name!r} must be {expected.__name__}"
        for name, expected in required.items()
        if not isinstance(card.get(name), expected)
    ]
    if card.get("schema_version") != "1":
        errors.append("risk card schema_version must be '1'")
    if card.get("risk_profile") not in RISK_ORDER:
        errors.append(f"risk_profile must be one of: {', '.join(RISK_ORDER)}")
    if card.get("blast_radius") not in {
        "local",
        "single_service",
        "multi_service",
        "organization",
        "public",
    }:
        errors.append("blast_radius has an invalid value")
    for field in ("summary", "failure_detection", "rollback"):
        if isinstance(card.get(field), str) and not card[field].strip():
            errors.append(f"risk card field {field!r} must not be blank")
    errors.extend(_risk_factor_errors(card.get("risk_factors"), policy))
    errors.extend(_authority_trigger_errors(card))
    return errors


def minimum_risk_profile(card: dict[str, Any], policy: dict[str, Any]) -> str:
    minimum = "experiment"
    if card.get("production_scope"):
        minimum = "standard"
    blast = card.get("blast_radius")
    if blast in {"multi_service", "organization", "public"}:
        minimum = "high_assurance"
    if card.get("reversible") is False:
        minimum = "high_assurance"
    factor_rules = policy.get("risk_rules", {}).get("minimum_profile_by_factor", {})
    for factor, value in card.get("risk_factors", {}).items():
        if value and factor in factor_rules:
            candidate = factor_rules[factor]
            if RISK_ORDER.index(candidate) > RISK_ORDER.index(minimum):
                minimum = candidate
    return minimum


def risk_summary(
    root: Path, policy: dict[str, Any], card_path: str
) -> tuple[list[str], dict[str, Any]]:
    card = load_risk_card(root, card_path)
    errors = risk_card_errors(card, policy)
    selected = card.get("risk_profile", "experiment")
    minimum = minimum_risk_profile(card, policy)
    if selected in RISK_ORDER and RISK_ORDER.index(selected) < RISK_ORDER.index(minimum):
        errors.append(f"selected profile {selected!r} is below deterministic minimum {minimum!r}")
    risk_cfg = policy.get("risk_profiles", {}).get(selected, {}) if selected in RISK_ORDER else {}
    return errors, {
        "card": card,
        "selected_risk_profile": selected,
        "minimum_risk_profile": minimum,
        "required_execution_profiles": risk_cfg.get("required_execution_profiles", []),
        "required_controls": {
            key: value for key, value in risk_cfg.items() if key.startswith("requires_")
        },
        "errors": errors,
    }


def policy_override_enabled(policy: dict[str, Any]) -> bool:
    name = str(policy.get("policy", {}).get("policy_maintenance_env", "AQG_POLICY_MAINTENANCE"))
    return os.environ.get(name) == "1"


def protected_patterns(policy: dict[str, Any]) -> list[str]:
    return [str(value) for value in policy.get("policy", {}).get("protected_paths", [])]


def human_review_patterns(policy: dict[str, Any]) -> list[str]:
    return [str(value) for value in policy.get("policy", {}).get("human_review_paths", [])]
