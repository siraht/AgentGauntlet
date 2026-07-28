# AgentQualityGauntlet.ReviewCouncil

## Requirements

- `AQG-COUNCIL-001` A council run MUST bind every member review to the same
  immutable candidate bundle, revision, change fingerprint, control
  fingerprint, and declared review purpose.
- `AQG-COUNCIL-002` Provider adapters MUST invoke explicitly configured model
  and tool identities without shell interpolation, use timeouts and
  least-privilege execution, and preserve command and version provenance
  without recording secrets.
- `AQG-COUNCIL-003` Every member MUST return a validated, versioned result that
  separates findings, cited evidence, unknowns, confidence, and its scoped
  verdict. Invalid, missing, or timed-out output MUST fail that member rather
  than become agreement.
- `AQG-COUNCIL-004` Initial member reviews MUST be independent. Reconciliation
  MAY expose anonymized disagreements in a later round but MUST preserve every
  original response and dissent.
- `AQG-COUNCIL-005` A council conclusion MUST follow deterministic quorum and
  severity rules. Majority vote MUST NOT erase a blocker, deterministic gate
  failure, missing product intent, or material unresolved dissent.
- `AQG-COUNCIL-006` The synthesizer MUST cite member findings and repository
  evidence, report residual unknowns, and MUST NOT claim authority that the
  configured council policy does not grant.
- `AQG-COUNCIL-007` Prompts, normalized candidate inputs, provider identity,
  model identity, tool version, timings, validated responses, reconciliation,
  and the conclusion MUST be stored in immutable run evidence.
- `AQG-COUNCIL-008` Council evidence is advisory by default. It MUST NOT
  impersonate a human behavior approval, code-owner approval, hosted
  branch-protection check, or release authority.
- `AQG-COUNCIL-009` Sensitive inputs MUST be minimized and explicitly
  classified before external-provider review; credentials, environment
  secrets, and unrelated repository content MUST NOT enter provider prompts.
- `AQG-COUNCIL-010` Provider diversity MUST be visible. Multiple roles executed
  by the same provider or model family MUST NOT be reported as independent
  model agreement.
- `AQG-COUNCIL-011` A fast advisory tier MAY use inexpensive reviewers, but
  high-assurance council evidence MUST include independently implemented model
  families and an adversarial role.
- `AQG-COUNCIL-012` Deterministic tests MUST cover malformed output, provider
  failure, timeout, prompt injection in candidate text, conflicting verdicts,
  blocker preservation, stale scope, and immutable evidence before a real
  provider run can be trusted.

## Related specifications

- `AgentQualityGauntlet`
- `AgentQualityGauntlet.OwnerStatus`
- `AgentQualityGauntlet.Review`
- `AgentQualityGauntlet.Execution`
