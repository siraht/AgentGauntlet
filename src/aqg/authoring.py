"""Templates for durable product specifications, executable features, and manual QA procedures."""

from __future__ import annotations

import re
from pathlib import Path

from .errors import ConfigurationError
from .util import atomic_write, slugify

FEATURE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z][A-Za-z0-9-]*)*$")


def validate_feature_name(name: str) -> str:
    value = name.strip()
    if not FEATURE_NAME_RE.fullmatch(value):
        raise ConfigurationError(
            "feature name must use dot-separated ASCII segments beginning with a letter"
        )
    return value


def create_feature_spec(root: Path, name: str, *, todo: bool = False, force: bool = False) -> Path:
    """Create a Keystone-compatible behavior contract with explicit review surfaces."""

    name = validate_feature_name(name)
    filename = f"TODO.{name}.md" if todo else f"{name}.md"
    path = root / "feature-spec" / filename
    if path.exists() and not force:
        raise ConfigurationError(f"feature specification already exists: {path}")
    state = (
        "intended behavior that is not implemented yet"
        if todo
        else "implemented, supported behavior that must remain true"
    )
    implementation_note = (
        "Before removing the `TODO.` prefix, implement every applicable requirement, connect executable evidence, and reconcile any active specification with the same feature name."
        if todo
        else "A mismatch between this active specification and the product is a defect; do not weaken this document merely to make an implementation pass."
    )
    content = f"""# {name}

This document defines **{state}**. Replace every bracketed instruction with concrete, observable product language before treating the specification as approved.

{implementation_note}

## Purpose and scope

Describe the user or system outcome this feature owns, the surfaces where it is visible, and the boundary beyond which another feature contract applies. Avoid class names, source paths, frameworks, database choices, and other implementation detail.

## Actors and observable surfaces

- **Primary actor:** [person, service, administrator, scheduled process, or device]
- **Other actors:** [roles or systems whose permissions or outcomes differ]
- **Surfaces:** [web page, API, command, file, event, notification, database-visible state, or operational signal]
- **Out of scope:** [closely related behavior governed elsewhere]

## Requirements

Use one durable requirement per item. Each requirement should identify a trigger or state, an observable outcome, and any forbidden outcome that matters.

- When [precondition and trigger], the product MUST [observable successful outcome].
- The product MUST preserve [invariant] before, during, and after [operation].
- The product MUST NOT [forbidden outcome, cross-tenant effect, silent data loss, privilege increase, or ambiguous success].
- When [invalid or boundary condition], the product MUST reject the operation with [stable error category and recoverable user guidance] and MUST leave [protected state] unchanged.
- When [dependency, timeout, interruption, or partial-failure condition], the product MUST [retry, roll back, compensate, or expose a recoverable state] without duplicating [side effect].

## Invariants and state transitions

State the rules that must remain true across every path, including failures and retries.

- [Entity or aggregate] MUST transition only from [allowed starting states] to [allowed resulting states].
- Repeating [operation] with the same idempotency identity MUST [produce the same result or refuse a duplicate] without duplicating side effects.
- Updating one [tenant/user/entity] MUST NOT change another [tenant/user/entity].
- Persisted state, emitted events, returned output, and audit records MUST agree on [critical fact].

## Boundaries and invalid input

Define exact lower, upper, empty, malformed, duplicate, stale, and unsupported cases. State whether values are rejected, normalized, truncated, defaulted, or accepted; never leave coercion implicit.

- [Minimum valid value] MUST [result].
- [Maximum valid value] MUST [result].
- [First invalid value below/above the boundary] MUST [result].
- Missing, malformed, duplicated, stale, and unsupported input MUST [result] without [forbidden side effect].

## Authorization, privacy, and abuse resistance

Delete this section only when the feature genuinely has no identity, permission, personal-data, secret, or abuse surface.

- Only [role/owner/service identity] MUST be able to [sensitive operation].
- A denied actor MUST receive [observable denial] and MUST NOT learn [protected existence or value].
- Logs, analytics, errors, notifications, and test evidence MUST NOT expose [secret or personal data].
- Rate, replay, enumeration, automation, or resource-exhaustion behavior MUST [defined protection or bounded response].

## Failure, recovery, and reversibility

- On [dependency failure], the product MUST expose [state/error/telemetry] within [observable bound].
- A retry after [failure point] MUST [resume safely, restart safely, or remain idempotent].
- Operators MUST be able to detect [failure] through [metric/log/alert/status] and recover using [rollback, compensation, replay, restore, or kill switch].
- Recovery MUST preserve [critical data and authorization invariant].

## Accessibility and interaction semantics

For user interfaces, define keyboard, focus, name/role/value, error association, status announcement, zoom/reflow, contrast, motion, and touch-target expectations that are specific to this behavior. Reference the project accessibility contract for shared requirements.

- A keyboard-only user MUST be able to [complete or cancel the journey] without focus loss or a keyboard trap.
- Errors and state changes MUST be programmatically associated with [control/region] and announced without relying only on color, position, sound, or animation.

## Performance and operational bounds

Specify only bounds that protect a user or system outcome. Include data scale and measurement conditions.

- Under [representative load/data size/environment], [operation] SHOULD complete within [bound] at [percentile or budget].
- Failure to meet the bound MUST [degrade safely, queue work, reject early, or alert] rather than [unbounded resource behavior].

## Compatibility and public contracts

- Existing consumers that satisfy [versioned contract] MUST continue to [observable compatibility guarantee].
- Any schema, API, event, CLI, or stored-data change MUST follow [versioning/migration/deprecation rule].
- Unknown fields or versions MUST [defined behavior].

## Acceptance examples

List the canonical scenarios that must become executable Gherkin, contract tests, or golden sessions. Cover at least:

1. primary success;
2. lower and upper boundaries;
3. invalid or malformed input;
4. unauthorized or cross-scope access;
5. duplicate, replay, or retry;
6. dependency failure and recovery;
7. persistence and side-effect consistency;
8. accessibility behavior where a user interface is involved.

## Verification and traceability

- **Feature identifier used by tests:** `{name}`
- **Gherkin feature:** `features/{slugify(name)}.feature`
- **Manual QA procedure:** `qa/procedures/{slugify(name)}.md`
- **Contract/schema evidence:** [path or not applicable with rationale]
- **Golden-session evidence:** [path or not applicable with rationale]
- **Operational/recovery evidence:** [path or not applicable with rationale]

Tests SHOULD reference the exact identifier using the language-appropriate form `Feature-Spec: {name}`. Evidence paths are navigation aids, not substitutes for the normative requirements above.

## Exceptions

Use this section only for a narrow, justified exception to an inherited active requirement. Each exception must identify the applicable ancestor, state the narrower behavior, explain why it is necessary, and retain the rest of the inherited rule.

### [Exception title]

Source: `[Applicable.Parent]`

Exception: [narrow exception]

Rationale: [why the inherited rule cannot be satisfied and how risk is bounded]

## Related specifications

- Add only non-parent behavior contracts that must be read before changing this feature.
"""
    atomic_write(path, content)
    return path


def create_gherkin_feature(root: Path, name: str, *, force: bool = False) -> Path:
    """Create a strict, mutation-friendly Gherkin suite whose Examples are all connected."""

    name = validate_feature_name(name)
    path = root / "features" / f"{slugify(name)}.feature"
    if path.exists() and not force:
        raise ConfigurationError(f"Gherkin feature already exists: {path}")
    title = name.replace(".", " ")
    content = f"""# Feature-Spec: {name}
# Replace the vocabulary and values below with domain terms. Every Examples column
# must be consumed by a step so acceptance mutation can prove that the data matters.
Feature: {title}

  Scenario Outline: The primary journey produces the intended observable result
    Given an actor with role <actor_role> and starting state <starting_state>
    When the actor requests <operation> using value <input_value>
    Then the request outcome is <expected_outcome>
    And the resulting state is <expected_state>
    And the recorded side effect count is <expected_side_effect_count>

    Examples:
      | actor_role | starting_state | operation       | input_value | expected_outcome | expected_state | expected_side_effect_count |
      | permitted  | ready          | primary-action  | normal      | accepted         | completed      | 1                          |

  Scenario Outline: Boundary values have explicit behavior
    Given an actor with role <actor_role> and starting state <starting_state>
    When the actor requests <operation> using value <boundary_value>
    Then the request outcome is <expected_outcome>
    And the resulting state is <expected_state>

    Examples:
      | actor_role | starting_state | operation      | boundary_value | expected_outcome | expected_state |
      | permitted  | ready          | primary-action | minimum-valid  | accepted         | completed      |
      | permitted  | ready          | primary-action | maximum-valid  | accepted         | completed      |
      | permitted  | ready          | primary-action | first-invalid  | rejected         | ready          |

  Scenario Outline: Invalid input is rejected without a protected side effect
    Given an actor with role <actor_role> and starting state <starting_state>
    When the actor requests <operation> using malformed input <malformed_input>
    Then the request outcome is <expected_outcome>
    And the stable error category is <expected_error>
    And the resulting state is <expected_state>
    And the recorded side effect count is <expected_side_effect_count>

    Examples:
      | actor_role | starting_state | operation      | malformed_input | expected_outcome | expected_error | expected_state | expected_side_effect_count |
      | permitted  | ready          | primary-action | missing          | rejected         | invalid-input  | ready          | 0                          |
      | permitted  | ready          | primary-action | unsupported      | rejected         | invalid-input  | ready          | 0                          |

  Scenario Outline: Unauthorized and cross-scope access is denied
    Given an actor with role <actor_role> and starting state <starting_state>
    When the actor requests <operation> for scope <target_scope>
    Then the request outcome is <expected_outcome>
    And the stable error category is <expected_error>
    And the resulting state is <expected_state>
    And the protected value visibility is <expected_visibility>

    Examples:
      | actor_role | starting_state | operation      | target_scope | expected_outcome | expected_error | expected_state | expected_visibility |
      | denied     | ready          | primary-action | own          | rejected         | unauthorized   | ready          | hidden              |
      | permitted  | ready          | primary-action | another      | rejected         | forbidden      | ready          | hidden              |

  Scenario Outline: Duplicate or replayed requests are idempotent
    Given an actor with role <actor_role> and starting state <starting_state>
    And the idempotency identity is <request_identity>
    When the actor repeats <operation> a total of <attempt_count> times
    Then the request outcome is <expected_outcome>
    And the resulting state is <expected_state>
    And the recorded side effect count is <expected_side_effect_count>

    Examples:
      | actor_role | starting_state | request_identity | operation      | attempt_count | expected_outcome | expected_state | expected_side_effect_count |
      | permitted  | ready          | same-request     | primary-action | 2             | accepted         | completed      | 1                          |

  Scenario Outline: Dependency failure remains recoverable
    Given an actor with role <actor_role> and starting state <starting_state>
    And dependency <dependency_name> fails at <failure_point>
    When the actor requests <operation> using value <input_value>
    Then the request outcome is <failure_outcome>
    And the resulting state is <failure_state>
    When dependency <dependency_name> recovers and the actor retries <operation>
    Then the request outcome is <recovery_outcome>
    And the resulting state is <recovery_state>
    And the recorded side effect count is <expected_side_effect_count>

    Examples:
      | actor_role | starting_state | dependency_name | failure_point | operation      | input_value | failure_outcome | failure_state | recovery_outcome | recovery_state | expected_side_effect_count |
      | permitted  | ready          | required-service | before-commit | primary-action | normal      | retryable       | ready         | accepted         | completed      | 1                          |
"""
    atomic_write(path, content)
    return path


def create_qa_procedure(root: Path, name: str, *, force: bool = False) -> Path:
    """Create an ACT-style, evidence-producing manual QA procedure."""

    slug = slugify(name)
    path = root / "qa" / "procedures" / f"{slug}.md"
    if path.exists() and not force:
        raise ConfigurationError(f"QA procedure already exists: {path}")
    content = f"""# QA procedure: {name}

This is a controlled test method, not a free-form checklist. Replace every bracketed field, assign stable case IDs, and preserve the completed execution record as release evidence.

## Procedure metadata

- **Procedure ID:** `QA-{slug.upper().replace("-", "_")}-001`
- **Version:** 1
- **Status:** draft
- **Owner:** [named human or accountable team]
- **Independent reviewer:** [required for High-assurance/Critical changes]
- **Linked active feature specification:** `[Product.Feature]`
- **Linked Gherkin feature/scenarios:** `[features/example.feature :: scenario names]`
- **Risk profile:** [standard / high_assurance / critical]
- **Required execution cadence:** [per change / release / scheduled / incident reproduction]
- **Last method review:** [ISO date]

## Purpose and risk controlled

State the user-visible or operational failure this method is designed to detect, why deterministic automated evidence is insufficient, and which requirement or recovery claim it independently checks.

## Applicability

Run this procedure when all of these conditions are true:

- [surface, feature flag, deployment mode, data shape, role, or environment condition]

This procedure is **inapplicable**, rather than passed, when:

- [precise condition and the alternative evidence that applies]

A blocked environment, missing account, unavailable dependency, or failed setup is **blocked**, never passed or inapplicable.

## Assumptions and limitations

- [Assumption the method depends on]
- [Behavior intentionally outside this method]
- [Known class of defects this method cannot detect]
- [Required complementary automated, accessibility, security, performance, or recovery evidence]

## Safety and stop conditions

Stop immediately, preserve evidence, and escalate when any of these occurs:

- unexpected production or third-party side effects;
- data corruption, destructive migration behavior, or loss of rollback capability;
- privilege escalation, cross-tenant visibility, secret exposure, or unapproved personal-data access;
- unbounded retries, resource exhaustion, uncontrolled message/email/payment creation, or an inability to identify the test data;
- monitoring, audit logging, or the kill switch is unavailable when the procedure requires it.

Do not improvise past a stop condition. Mark the affected case **blocked** or **failed** and record the point reached.

## Controlled environment

| Field | Required value / record |
|---|---|
| Repository revision | [full commit SHA plus dirty/clean state] |
| Build or artifact identity | [digest, version, attestation, or deployment ID] |
| Environment | [isolated environment name and region] |
| Configuration and feature flags | [exact values affecting behavior] |
| Browser, device, runtime, assistive technology | [versions where applicable] |
| Account and role | [synthetic identity and effective permissions] |
| Dataset / fixture version | [identifier and provenance] |
| External dependencies | [real, sandbox, simulated, degraded, or disconnected] |
| Clock / timezone / locale | [controlled values where behavior depends on them] |
| Monitoring and rollback access | [confirmed by whom and when] |

Never use live secrets, unapproved production personal data, or irreversible external systems merely because they are convenient.

## Test data and cleanup

Describe exact data creation, ownership, uniqueness markers, retention, and deletion. Identify every expected database row, file, event, notification, payment, message, or external side effect and the cleanup/reconciliation procedure for each.

## Evidence rules

Retain enough evidence to reproduce the result without collecting unnecessary secrets or personal data:

- revision, artifact, environment, actor role, and timestamp;
- complete structured request/response or command output where practical;
- screenshots or recordings only when visual layout, focus, animation, or rendering matters;
- console/network logs and trace IDs for the exact test journey;
- before/after state or stable hashes for persisted artifacts;
- accessibility tree, keyboard focus order, and announcement evidence when applicable;
- monitoring/alert and rollback evidence for recovery cases.

Redact only unstable or sensitive fields using explicit placeholders. Do not crop away surrounding state that could reveal an unexpected change.

## Test cases

Use equivalence classes, exact boundaries, decision-table combinations, state transitions, pairwise combinations, error guessing, and abuse cases deliberately. Add or remove rows to match the actual risk; do not leave a technique named without a concrete case.

| Case ID | Design technique | Preconditions and data | Action | Exact expected result | Evidence | Result |
|---|---|---|---|---|---|---|
| QA-001 | Primary journey | [valid actor/state/data] | [complete user-visible action] | [output, state, side effects, telemetry] | [paths/IDs] | pending |
| QA-002 | Lower boundary | [minimum valid state/value] | [action] | [accepted behavior] | [paths/IDs] | pending |
| QA-003 | Upper boundary | [maximum valid state/value] | [action] | [accepted behavior] | [paths/IDs] | pending |
| QA-004 | First invalid boundary | [value immediately outside boundary] | [action] | [stable rejection; protected state unchanged] | [paths/IDs] | pending |
| QA-005 | Invalid/malformed | [missing, malformed, duplicate, stale, unsupported] | [action] | [specific error category and no forbidden side effect] | [paths/IDs] | pending |
| QA-006 | Authorization matrix | [denied role / other scope] | [sensitive action] | [deny without protected disclosure; audit result] | [paths/IDs] | pending |
| QA-007 | Retry/idempotency | [same request identity] | [repeat/interruption/retry] | [one committed side effect and consistent result] | [paths/IDs] | pending |
| QA-008 | Dependency failure | [inject failure at named point] | [action] | [bounded failure, observable telemetry, recoverable state] | [paths/IDs] | pending |
| QA-009 | Recovery/rollback | [failed or partially completed state] | [retry/rollback/restore] | [defined recovered state and preserved invariants] | [paths/IDs] | pending |
| QA-010 | Accessibility | [keyboard and assistive-technology setup] | [complete journey, errors, cancellation] | [focus, names, announcements, reflow, contrast, motion behavior] | [paths/IDs] | pending |
| QA-011 | Concurrency/replay | [two actors or concurrent requests] | [race/reorder/replay] | [defined winner/order/conflict and no corruption] | [paths/IDs] | pending |
| QA-012 | Observability | [known request/test identity] | [success and failure paths] | [useful, correlated logs/metrics/traces without sensitive data] | [paths/IDs] | pending |

Allowed result values are `pass`, `fail`, `blocked`, and `inapplicable`:

- **pass:** every expected result was observed and required evidence was retained;
- **fail:** any expected result was absent, any forbidden behavior occurred, or evidence contradicts the claim;
- **blocked:** setup or execution could not complete, including a failed prerequisite or stop condition;
- **inapplicable:** the documented applicability condition is false and the alternative evidence is identified.

## Accessibility execution detail

For web interfaces, complete these checks in addition to automated scanning:

1. Operate the complete journey using only the keyboard, including opening, cancelling, recovering from errors, and returning focus.
2. Inspect accessible names, roles, states, values, descriptions, error associations, and live-region announcements.
3. Verify zoom/reflow, text spacing, contrast, non-color cues, reduced motion, target size, orientation, and responsive layouts relevant to the feature.
4. Use at least one representative screen-reader/browser combination for High-assurance or Critical changes.
5. Record defects against the user task and applicable requirement, not merely against a scanner rule ID.

## Failure injection and recovery detail

State exactly how each failure is injected, how the injection is proven active, what telemetry should appear, how retries are bounded, how partial state is inspected, and how normal operation is restored. A test that never proves the failure was actually injected is invalid.

## Cleanup and reconciliation

1. Remove or reconcile every identified test artifact and external side effect.
2. Confirm no background worker, retry, scheduled job, notification, or delayed write remains pending.
3. Restore configuration and feature flags.
4. Capture final cleanup evidence and list anything intentionally retained with owner and expiry.

## Execution record

- **Executed by:**
- **Execution started / finished:**
- **Revision and artifact:**
- **Environment:**
- **Overall result:** pending
- **Failed or blocked case IDs:**
- **Unexpected observations:**
- **Defect / incident links:**
- **Evidence index:**
- **Cleanup confirmed by:**
- **Rollback or recovery result:**

## Review and approval

The reviewer confirms that the procedure was applicable, the environment and data were controlled, every claimed pass has supporting evidence, failures were not reclassified as inapplicable, cleanup completed, and the evidence still matches the unchanged revision/artifact.

- **Reviewed by:**
- **Reviewed at:**
- **Decision:** pending
- **Rationale / residual risk:**
"""
    atomic_write(path, content)
    return path
