# QA procedure: advisory review council

## Purpose and risk

Verify that multi-model review is exact-candidate, independent, fail-closed,
tamper-evident, privacy-conscious, and unmistakably advisory.

## Preconditions

- Environment: disposable checkout with Grok and OpenCode authenticated.
- Build/version: record the exact Git revision and comparison base.
- Required permissions: outbound provider access approved for the candidate's
  data classification.
- Evidence: current manifested quality run with a passing secret gate.

## Procedure

1. Run `python3 quality/qg.py council doctor`.
   - Expected: exact tool versions and model identifiers are shown without
     credentials.
2. Run `python3 quality/qg.py council plan --tier pr`.
   - Expected: no provider is called.
   - Expected: the plan names revision, comparison base, change/control
     fingerprints, quality run, bundle digest/size, roles, models, and provider
     groups.
3. Inspect the planned input classification before approving provider access.
   - Expected: unrelated repository content is absent and the bundle is below
     the protected size cap.
4. Run `python3 quality/qg.py council run --tier pr`.
   - Expected: each member runs in isolation and either produces a validated
     cited ballot or a distinct configuration/infrastructure failure.
   - Expected: a timeout, malformed payload, or missing provider does not enter
     quorum.
5. Run `python3 quality/qg.py council verify` and `council report`.
   - Expected: the manifest verifies; quorum, role coverage, blockers, dissent,
     limitations, and advisory authority are explicit.
6. Copy the run, modify one ballot byte, and verify the copy.
   - Expected: verification fails and `latest` is not repointed to the
     tampered copy.
7. Change the candidate without rerunning the council and open owner status.
   - Expected: the council result is stale and cannot describe the new
     candidate.
8. Inspect stored execution evidence.
   - Expected: prompt/response/command/error digests, timings, models, provider
     groups, and tool versions are present.
   - Expected: raw stdout, stderr, credentials, and environment secrets are
     absent.

## Cleanup

Delete only disposable tamper copies. Keep the original council run immutable.
Do not promote advisory evidence into a human approval record.

## Rollback check

Re-run the plan against the previous safe revision. Confirm that its bundle
digest and scope differ and that neither council result can be reused across
candidates.

## Result

- Executed by:
- Date:
- Build/revision:
- Pass/fail:
- Evidence:
- Follow-up:
