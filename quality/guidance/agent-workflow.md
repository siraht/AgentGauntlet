# Agent workflow

> Use one repeatable sequence: resolve intent and risk, create independent evidence, implement narrowly, run the required profile, and hand humans a reviewable decision packet.

## Before editing

1. Run `python3 quality/qg.py status` and `python3 quality/qg.py doctor`.
2. Read `QUALITY.md`, `KEYSTONE.md`, `quality/change-risk.json`, and the most specific applicable active feature specification. Read TODO specifications only when the task explicitly concerns future behavior.
3. List observable behavior that will change and behavior that must remain unchanged. Add these to the risk card before implementation.
4. Identify affected boundaries: API, persistence, identity, permissions, money, privacy, files, queues, clocks, randomness, external services, browser UI, build/release, and rollback.
5. Select evidence before code. At minimum, name the unit or property test, boundary contract, acceptance scenario, and QA step that would fail if the implementation were wrong.

## During implementation

- Work in small vertical slices. Each slice should change one behavioral claim and its evidence together.
- Run `check fast` after a coherent slice, not after dozens of unrelated edits.
- Do not change policy, thresholds, tool commands, baselines, expected outputs, approvals, or suppressions to make a failing change pass.
- Do not use time sleeps, random production data, real network calls, shared mutable fixtures, or order-dependent setup in required CI tests. Inject and control those dependencies.
- When a test fails, classify the failure before editing: product defect, test defect, specification conflict, fixture problem, tool/configuration problem, or infrastructure failure.
- When behavior is intentionally changed, update the active/TODO specification and acceptance evidence first enough that the intended diff is visible to the reviewer.

## Before completion

1. Run `python3 quality/qg.py acceptance lint`.
2. Run `python3 quality/qg.py check-risk --keep-going` after the final source, tests, specifications, and fixtures are in place.
3. Run `python3 quality/qg.py review --write --sarif` after the final profile run. Any subsequent change invalidates evidence and approvals.
4. Inspect raw evidence for skipped or inapplicable gates, missing reports, surviving mutants, warnings, and flaky retries. A green summary is insufficient when the underlying scope is wrong.
5. Produce a completion statement containing: behavior changed, behavior preserved, tests added, required profile and run ID, mutation survivors, manual review required, failure detection, and rollback.

## Stop and escalate

Stop implementation and report the conflict when an active requirement contradicts another active requirement, a test can only pass by weakening an oracle, required evidence cannot be generated, destructive testing lacks isolation or rollback, or the risk card implies a stricter profile than the task permits. Do not silently reinterpret the requirement.
