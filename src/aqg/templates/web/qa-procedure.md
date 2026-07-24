# QA procedure: Web behavior

Use `qg new qa "<descriptive name>"` to generate the full controlled-test-method template. This repository-level starter records the minimum web review that must be expanded for the affected feature.

## Metadata

- Procedure ID:
- Linked Feature-Spec:
- Linked Gherkin scenario:
- Risk profile:
- Owner:
- Revision / artifact:
- Environment / browser / device / assistive technology:

## Applicability and controlled risk

State exactly when this method applies, what user-visible failure it detects, and why automated checks alone cannot settle the question. A failed prerequisite is **blocked**, not passed.

## Safety and stop conditions

Stop on unexpected external side effects, data corruption, privilege or cross-tenant exposure, secret/personal-data leakage, unbounded retries, or loss of rollback/monitoring.

## Cases

| ID | Technique | Preconditions | Action | Exact expected result | Evidence | Result |
|---|---|---|---|---|---|---|
| WEB-001 | Primary journey | | | Output, state, side effects, telemetry | | pending |
| WEB-002 | Boundaries / invalid input | | | Stable rejection; protected state unchanged | | pending |
| WEB-003 | Authorization | | | Denial without protected disclosure | | pending |
| WEB-004 | Retry / interruption | | | Idempotent recovery; no duplicate effect | | pending |
| WEB-005 | Keyboard / focus | | | Complete journey; logical focus; no trap | | pending |
| WEB-006 | Semantics / announcements | | | Correct name/role/state/error/status | | pending |
| WEB-007 | Reflow / visual state | | | Required zoom, spacing, contrast, motion, target behavior | | pending |
| WEB-008 | Failure / rollback | | | Bounded failure, useful telemetry, rehearsed recovery | | pending |

Allowed results: `pass`, `fail`, `blocked`, `inapplicable`. Every pass requires retained evidence.

## Cleanup and approval

- Cleanup / reconciliation:
- Failed or blocked cases:
- Evidence index:
- Executed by / at:
- Independent reviewer / decision:
- Residual risk:
