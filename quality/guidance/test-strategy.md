# Test strategy

> Build a set of independent oracles around each important behavior; avoid duplicating the same assertion through several frameworks and calling that depth.

## Start from claims, not files

For every change, write a small claim table:

| Claim                                | Failure mode                     | Best oracle           | Why independent                                                          |
| ------------------------------------ | -------------------------------- | --------------------- | ------------------------------------------------------------------------ |
| A calculation preserves an invariant | wrong branch or boundary         | unit + property       | generated values exercise paths not chosen by examples                   |
| An API rejects an unauthorized role  | missing policy check             | contract + acceptance | validates both response contract and real policy integration             |
| A browser journey remains operable   | DOM or state integration failure | Playwright + QA       | user-facing locator and human keyboard/assistive check                   |
| A complex trace does not drift       | unanticipated side effect        | golden session        | broad stable-state diff catches unasserted changes                       |
| Tests notice plausible faults        | weak assertion                   | mutation              | changes production/acceptance input instead of repeating expected values |

A test layer is justified when it observes a distinct boundary or failure mechanism. Remove redundant tests that exercise the same code path with the same fixture and same oracle unless they document materially different behavior.

## Required dimensions

At least one applicable test must cover each of these dimensions:

- normal success;
- exact lower and upper boundaries, plus just outside each boundary;
- invalid shape, missing value, wrong type, and semantically invalid value;
- permission and tenant/ownership boundaries;
- repeated request, retry, cancellation, timeout, and partial failure;
- persistence and side effects, including absence of forbidden side effects;
- ordering and concurrency where state can race;
- serialization and compatibility at external boundaries;
- recovery and rollback for stateful or destructive operations;
- observability: the failure produces a usable signal without leaking secrets or personal data.

## Scope by risk

**Experiment:** fast deterministic tests and test-integrity checks are enough only when the change is disposable and isolated from real users and data.

**Standard:** changed-code coverage, contracts, acceptance behavior, security checks, and human behavior review are required.

**High assurance:** add affected-system mutation, manual QA, rollback rehearsal, threat analysis, and an independent read-only verifier.

**Critical:** add independent human code review, full relevant mutation, release rehearsal, staged deployment, kill switch, and explicit release approval.

## Avoid false confidence

Coverage proves execution, not correctness. Snapshots prove equality to an approved artifact, not semantic validity. Mocks prove behavior against the mock contract, not the real service. End-to-end tests prove a few integrated journeys, not combinatorial edge cases. Mutation improves confidence in assertions but can include equivalent mutants and cannot model every defect. Combine the mechanisms and preserve their limits in the review packet.
