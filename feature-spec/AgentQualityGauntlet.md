# AgentQualityGauntlet

## Requirements

- AQG MUST install and run on Python 3.11 or newer without runtime third-party dependencies.
- AQG MUST support JavaScript, TypeScript, HTML, CSS, and Python project detection and adapter configuration.
- AQG MUST return exit `0` only when the requested measurement completed and passed.
- AQG MUST distinguish quality failure, configuration failure, and infrastructure failure with exits `1`, `2`, and `3`.
- AQG MUST NOT treat a missing, stale, malformed, timed-out, crashed, or unexpectedly empty measurement as passing evidence.
- AQG MUST compute a deterministic minimum risk profile and MUST NOT accept a weaker selected profile.
- AQG MUST keep policy-plane and human-review-plane changes visible and separately governed.
- AQG MUST create a project-local runtime and stable command surface during setup.
- AQG MUST keep ordinary golden comparison separate from explicitly authorized expected-output updates.
- AQG MUST generate review and evidence artifacts from the same normalized state used by its CLI, TUI, dashboard, and CI.
- AQG MUST fail the supply-chain gate when declared JavaScript or Python dependencies lack a supported reproducible lock input.
- Rebuilding an unchanged AQG portable release in the same environment MUST produce byte-identical zipapp and portable archives.

## Related specifications

- `AgentQualityGauntlet.Setup`
- `AgentQualityGauntlet.Execution`
- `AgentQualityGauntlet.Review`
- `AgentQualityGauntlet.SupplyChain`
