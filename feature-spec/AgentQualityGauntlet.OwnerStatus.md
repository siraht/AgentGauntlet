# AgentQualityGauntlet.OwnerStatus

## Requirements

- `AQG-OWNER-001` CLI, dashboard, TUI, reports, and CI summaries MUST derive
  owner guidance from one schema-versioned, read-only status model rather than
  independently interpreting partial evidence.
- `AQG-OWNER-002` The model MUST answer Develop, Merge, and Release as separate
  decisions and MUST distinguish locally allowed work from readiness for an
  authoritative external check.
- `AQG-OWNER-003` Run evidence is current only when its revision, change
  fingerprint, and control fingerprint match the candidate and its complete
  run manifest verifies.
- `AQG-OWNER-004` A stored review packet MUST be classified as stale, missing,
  invalid, or current from its recorded provenance; a prior clear review MUST
  NOT silently remain current after its review surface changes.
- `AQG-OWNER-005` Ratchet status MUST show inherited reviewed debt separately
  from new, worsened, invalid, or unclassified regressions. Inherited debt
  alone MUST NOT be described as a current-change failure.
- `AQG-OWNER-006` Missing review-council evidence MUST be represented as
  `not_configured` or `missing`, never as consensus or approval.
- `AQG-OWNER-007` The model MUST rank a deterministic next action from the
  blocking or unknown evidence and identify the actor or authority responsible
  for it.
- `AQG-OWNER-008` Local evidence MUST NOT be described as merge permission or
  release permission when authoritative CI, branch-protection, or release
  authority is not represented by current trusted evidence.
- `AQG-OWNER-009` Missing, malformed, stale, or tampered evidence MUST remain
  visible with its actual classification and MUST NOT be collapsed into an
  ordinary quality failure or pass.

## Related specifications

- `AgentQualityGauntlet`
- `AgentQualityGauntlet.Execution`
- `AgentQualityGauntlet.Review`
- `AgentQualityGauntlet.Retrospective`
- `AgentQualityGauntlet.ReviewCouncil`
