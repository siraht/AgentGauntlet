# AgentQualityGauntlet

## Requirements

- AQG MUST install and run on Python 3.11 or newer without runtime third-party dependencies.
- AQG MUST support JavaScript, TypeScript, HTML, CSS, and Python project detection and adapter configuration.
- AQG MUST return exit `0` only when the requested measurement completed and passed.
- AQG MUST distinguish quality failure, configuration failure, and infrastructure failure with exits `1`, `2`, and `3`.
- AQG MUST NOT treat a missing, stale, malformed, timed-out, crashed, or unexpectedly empty measurement as passing evidence.
- Changed-code mutation MUST account for executable deletions and MUST NOT pass
  vacuously when comparison-side production behavior was removed but no current
  mutation selector can represent that change.
- AQG MUST compute a deterministic minimum risk profile and MUST NOT accept a weaker selected profile.
- AQG MUST keep policy-plane and human-review-plane changes visible and separately governed.
- AQG MUST create an executable project-local `./aqg` command and retain
  `python3 quality/qg.py` as its portable fallback during setup and upgrade.
- Invoking the project-local runtime and Python test tools MUST NOT dirty a
  clean repository with interpreter or checker cache artifacts.
- AQG MUST keep ordinary golden comparison separate from explicitly authorized expected-output updates.
- AQG MUST generate review and evidence artifacts from the same normalized state used by its CLI, TUI, dashboard, and CI.
- AQG MUST fail the supply-chain gate when declared JavaScript or Python dependencies lack a supported reproducible lock input.
- Rebuilding an unchanged AQG portable release in the same environment MUST produce byte-identical zipapp and portable archives.
- Ignored or untracked runtime caches MUST NOT enter release payloads or provenance materials.
- Equivalent GitHub origin URL spellings MUST resolve to one canonical provenance repository identity.
- Release building MUST remain functional in isolated source and mutation copies without repository metadata.
- A release built from an isolated source copy MUST NOT inherit revision, remote,
  dirty-state, or commit-time provenance from an unrelated parent repository.
- A manually dispatched hosted quality run MUST compare against the authoritative
  default branch and MUST NOT fall back to the candidate's previous commit.
- Release attestation or publication MUST NOT proceed unless the authoritative
  risk-selected policy run and required test matrix succeed.
- An authoritative verifier MUST execute from an immutable trust anchor outside
  the candidate-controlled grading surface.
- Existing repositories MUST support a non-blocking retrospective shadow audit,
  a reviewed debt baseline, no-regression comparison, changed-code enforcement,
  and explicit promotion through adopt and strict enforcement states.
- AQG MUST distinguish inherited debt, current-change regressions, missing
  evidence, infrastructure errors, and unknown product intent in retrospective
  reports without converting an unknown measurement into a pass.
- Detailed evidence used to classify a gate MUST be copied into its run
  directory and protected by a deterministic manifest before the run completes.
- High-assurance policy MUST require independently fingerprinted verification,
  behavior approval, manual QA, and rollback evidence.
- Protected policy maintenance MUST require a scoped, fingerprinted approval
  record and MUST NOT make authoritative evidence pass while maintenance
  overrides are active.
- Active requirements MUST have stable identifiers that tests and acceptance
  scenarios can reference directly.

## Related specifications

- `AgentQualityGauntlet.Setup`
- `AgentQualityGauntlet.Execution`
- `AgentQualityGauntlet.Review`
- `AgentQualityGauntlet.Retrospective`
- `AgentQualityGauntlet.SupplyChain`
