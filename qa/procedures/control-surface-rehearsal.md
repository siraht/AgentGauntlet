# QA procedure: AgentGauntlet control-surface rehearsal

## Identity

- Procedure: `QA-AQG-CONTROL-SURFACES-001`
- Execution mode: agent-operated executable procedure
- Evidence producer: `scripts/dogfood_control_surfaces.py`

## Purpose

Exercise the installed product through public setup, CLI, review, conformance,
dashboard, and TUI boundaries, then prove cleanup and exact rollback. This is
the required executed QA procedure for High assurance and Critical AQG work;
an unexecuted checklist or prose approval is not evidence.

## Preconditions

- A clean candidate revision and installed quality toolchains.
- A disposable temporary directory.
- No real user data, credentials, external deployment, or paid action.

## Executed cases

1. Cold-start the candidate and inspect version, help, and guidance discovery.
2. Install the candidate into a generated disposable project and run doctor.
3. Exercise status, review generation, and deterministic conformance.
4. Exercise dashboard read routes, disabled actions, token rejection, a valid
   local action, and an unknown action.
5. Exercise the guided TUI through its public process boundary.
6. Change the disposable installed state, restore the content-addressed prior
   state, and prove both identity and observable operation output are equal.
7. Remove the temporary workspace and prove cleanup completed.

## Pass conditions

Every named case must retain non-empty structured evidence. The candidate must
be exact-revision bound and clean. Rollback must restore the prior digest and
observable output. Cleanup must be proven. Any missing, malformed, stale,
failed, or partially executed case fails the assurance gate.
