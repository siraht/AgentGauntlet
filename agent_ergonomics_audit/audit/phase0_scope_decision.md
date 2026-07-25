# Phase 0 scope decision

- Target: `/data/projects/AgentGauntlet`
- Primary executable: `python3 quality/qg.py` (source-checkout authority)
- Mode: `full`
- Primary agent profile: Codex CLI
- Triangulation: `none` during implementation; the repository's required independent
  read-only verifier remains the final High-assurance review boundary.
- Prior-session mining: skipped because the recovered source conversation and current
  productionization ledger already supply the relevant failure corpus.
- Toolchain: use the existing isolated Python and JavaScript toolchains; install no
  unrelated global dependencies.
- Branch: remain on the user-requested `agent/productionize-v2-beta` branch.
- Compatibility guardrail: preserve all documented commands, flags, exit-code meanings,
  JSON success payloads, and human-readable behavior unless a change is explicitly
  versioned and tested.
- Safety guardrail: do not weaken AQG policy, tests, thresholds, approval boundaries,
  or fail-closed behavior to improve convenience.
- Delivery guardrail: keep CLI-ergonomics changes in granular commits and finish the
  broader productionization goal before release handoff.

The user explicitly requested complete implementation, dogfooding, granular commits,
and autonomous progress. That supplies the intake confirmations for a full pass without
pausing for another interview.
