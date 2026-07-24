# QA procedures

> Write QA procedures as reproducible test methods: identity, scope, applicability, assumptions, exact inputs, controlled steps, observable outcomes, evidence, cleanup, and stop conditions.

## Required header

Every procedure records a stable ID, title, version, owner, linked feature requirements, risk factors, applicable platforms/configurations/roles, exclusions, revision/build fingerprint, environment, dataset, accounts, feature flags, and prerequisite automated evidence.

## Case structure

Use one table row or numbered case per distinct outcome:

| Field | Required content |
|---|---|
| Case ID / design technique | e.g. boundary, decision-table row, recovery |
| Preconditions | exact state, identity, data, configuration |
| Action | one reproducible user/system action |
| Expected outcome | exact visible result, state change, side effect, and forbidden effect |
| Observed outcome | filled during execution, never pre-populated as pass |
| Evidence | command output, trace, screenshot for visual claims, logs with redaction |
| Result | pass / fail / blocked / inapplicable with reason |

A case passes only when every required observation matches. “Looks good” is not an outcome. A blocked case does not count as pass and must name the missing prerequisite.

## Required journeys

Include primary success, boundary, invalid input, unauthorized role, retry/duplicate, interruption/partial failure, persistence after restart/reload, observability, cleanup, and rollback/recovery according to risk. Web procedures add keyboard, focus, zoom/reflow, accessibility name/error, and responsive checks.

## Safety

Use isolated disposable environments and synthetic data. Define stop conditions before destructive steps: unexpected privilege, data corruption, secret exposure, uncontrolled external notification/payment, or lost rollback. Never ask an agent to improvise destructive production QA.

## Review and execution separation

An agent may draft the procedure. A human reviews behavior and safety before execution. High-assurance execution records the named human, timestamp, exact revision, evidence paths, deviations, findings, cleanup, and rollback result. Any source/spec/control change invalidates the approval fingerprint.
