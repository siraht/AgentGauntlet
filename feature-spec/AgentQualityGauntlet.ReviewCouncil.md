# AgentQualityGauntlet.ReviewCouncil

## Requirements

- `AQG-COUNCIL-001` A council run MUST bind every member review to the same
  immutable candidate or candidate-series identity, revision, change
  fingerprint, control fingerprint, and declared review purpose. In a bounded
  series, each ballot MUST additionally bind to exactly one manifested member
  bundle and its position in that series.
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
  original validated ballot and dissent. Raw provider streams MAY be discarded
  after their digest and validated content have been recorded, because they can
  contain hidden reasoning, provider metadata, or reflected sensitive text.
- `AQG-COUNCIL-005` A council conclusion MUST follow deterministic quorum and
  severity rules. Majority vote MUST NOT erase a blocker, deterministic gate
  failure, missing product intent, or material unresolved dissent.
- `AQG-COUNCIL-006` The synthesizer MUST cite member findings and repository
  evidence, report residual unknowns, and MUST NOT claim authority that the
  configured council policy does not grant.
- `AQG-COUNCIL-007` Prompts, normalized candidate inputs, provider identity,
  model identity, tool version, timings, validated responses, reconciliation,
  and the conclusion MUST be stored in immutable run evidence.
- `AQG-COUNCIL-008` Council evidence is advisory by default. Protected policy
  MAY assign a current, complete, exact-candidate council technical-verification
  authority, but it MUST NOT impersonate a human, erase a deterministic
  failure, fill unknown product intent, or cross a reserved human-authority
  boundary.
- `AQG-COUNCIL-009` Sensitive inputs MUST be minimized and explicitly
  classified before external-provider review; credentials, environment
  secrets, and unrelated repository content MUST NOT enter provider prompts.
  The default external route MUST accept only an explicit `public`
  classification until a protected enterprise or isolated-provider route is
  configured.
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
- `AQG-COUNCIL-013` When a complete serialized candidate exceeds the protected
  provider-bundle cap, the controller MAY create a content-addressed bounded
  series. It MUST repeat the complete shared risk, requirement, review, and
  quality context; split only the exact diff; record byte ranges, order, size,
  and digests; require every configured role to review every member bundle;
  and prove exact diff reconstruction. It MUST NOT silently raise the cap,
  truncate content, or split shared product context.
- `AQG-COUNCIL-014` A bounded-series conclusion MUST aggregate conservatively.
  A blocker, dissent, failed member, malformed response, missing quorum, or
  incomplete member bundle MUST remain visible in the series result. Provider
  diversity MUST be the intersection present on every member bundle, not the
  union observed somewhere in the series.
- `AQG-COUNCIL-015` A bounded-series plan and report MUST disclose that each
  ballot sees one diff segment rather than the entire patch and that
  cross-segment relationships remain a residual review unknown. `complete`
  means every required per-segment ballot was received and validated; it MUST
  NOT imply whole-patch comprehension, approval, or release authority.

## Related specifications

- `AgentQualityGauntlet`
- `AgentQualityGauntlet.OwnerStatus`
- `AgentQualityGauntlet.Review`
- `AgentQualityGauntlet.Execution`
