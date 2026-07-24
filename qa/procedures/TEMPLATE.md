# QA procedure: <behavior>

## Purpose and risk

State what this procedure verifies and which failure it is intended to catch.

## Preconditions

- Environment:
- Build/version:
- Test account or fixture:
- Required permissions:
- Existing data state:
- Feature flags:
- Observability/log location:

## Procedure

1. Perform one concrete action.
   - Expected: state the observable result.
   - Evidence: screenshot, log event, response, or stored record.
2. Exercise the primary negative case.
   - Expected: state both the error and what must remain unchanged.
3. Exercise retry, cancellation, timeout, or recovery behavior where relevant.
   - Expected: state the recovery outcome.

## Cleanup

Describe how to remove test data and restore the environment.

## Rollback check

Describe how to prove the previous safe version or state can be restored.

## Result

- Executed by:
- Date:
- Build/revision:
- Pass/fail:
- Evidence:
- Follow-up:
