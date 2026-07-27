# AgentQualityGauntlet

## Requirements

- AQG MUST install and run on Python 3.11 or newer without runtime third-party dependencies.
- AQG MUST support JavaScript, TypeScript, HTML, CSS, and Python project detection and adapter configuration.
- AQG MUST return exit `0` only when the requested measurement completed and passed.
- AQG MUST distinguish quality failure, configuration failure, and infrastructure failure with exits `1`, `2`, and `3`.
- AQG MUST NOT treat a missing, stale, malformed, timed-out, crashed, or unexpectedly empty measurement as passing evidence.
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

## Related specifications

- `AgentQualityGauntlet.Setup`
- `AgentQualityGauntlet.Execution`
- `AgentQualityGauntlet.Review`
- `AgentQualityGauntlet.SupplyChain`
