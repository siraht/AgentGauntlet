# Self-hosting progress

This record tracks the staged AgentGauntlet-on-AgentGauntlet rollout. It is an
engineering log, not an approval artifact.

## 2026-07-27 — verified starting state

- Candidate revision audited: `51173c2ed9cf38d0c1882db2c344aac90d6f1386`.
- The repository is honestly in adopt mode and not strict-ready.
- Changed-function structure, changed-line coverage, and changed-code mutation
  selection exist, but the configured whole-tree debt flags have no comparison
  implementation.
- There is no first-class non-blocking shadow audit or reviewed metric baseline
  lifecycle.
- Candidate CI executes the candidate-controlled grader; its control
  fingerprint is not an external trust anchor.
- `quality/tests` contains three launcher contracts but is omitted from the
  authoritative pytest roots.
- High-assurance policy advertises a read-only verifier but does not require
  verifier evidence.
- Gate summaries are run-scoped, while detailed adapter reports are overwritten
  under `.aqg/work`.
- Traceability accepts incidental feature-name substrings, acceptance mutation
  is generic, and Lighthouse performance is single-shot.
- The current seven-gate fast profile measured roughly 85 seconds locally. Stop
  hook enforcement remains disabled and will stay disabled until a genuinely
  fast profile is green, stable, and reasonably quick.

## Decisions

- Treat the user request as explicit policy maintenance, but never fabricate
  the independent human/code-owner approval needed for authoritative adoption.
- Preserve threshold values. Baseline inherited debt; do not redefine it as
  quality.
- Implement and prove one narrow vertical slice at a time, keeping full deep
  checks at checkpoints instead of after each edit.
- Use the current branch and live evidence as authority; the recovered session
  archive had no indexed historical record for this work.
- Use Grok CLI for independent read-only audits and bounded implementation
  assistance, then reproduce every finding and verify every patch locally.

## Next checkpoint

Specify and test the shadow report, debt-baseline state machine, result
taxonomy, and promotion rules before enabling any blocking ratchet.
