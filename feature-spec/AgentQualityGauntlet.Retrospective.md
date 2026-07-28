# AgentQualityGauntlet.Retrospective

## Requirements

- `AQG-RETRO-001` A shadow audit MUST execute every applicable measurement it
  can run, preserve the normal result category, and return success without
  blocking ordinary development solely because measured inherited debt exists.
- `AQG-RETRO-002` Shadow audit MUST NOT relabel missing evidence,
  infrastructure errors, configuration errors, or unknown product intent as a
  passing measurement.
- `AQG-RETRO-003` A debt baseline MUST record its source revision, policy and
  control fingerprints, measurement provenance, complete normalized debt
  inventory, creation state, and reviewer approval state.
- `AQG-RETRO-004` Only a current, explicitly reviewed baseline MAY authorize
  adopt-mode no-regression comparison.
- `AQG-RETRO-005` Adopt mode MUST report inherited baseline debt without
  blocking an unrelated conforming change and MUST block newly introduced,
  worsened, or unclassified debt in the changed scope.
- `AQG-RETRO-006` Changed-code enforcement MUST include untracked production
  files and MUST fail closed when its comparison revision cannot be resolved.
- `AQG-RETRO-007` Promotion MUST be monotonic through `shadow`, `ratchet`, and
  `strict`; automatic promotion MAY be proposed but MUST NOT silently alter
  protected policy.
- `AQG-RETRO-008` A retrospective report MUST separately count measured
  failures, inherited debt, regressions, missing evidence, configuration
  errors, infrastructure errors, and unknown product intent.
- `AQG-RETRO-009` A development profile MUST provide a stable seconds-scale
  changed-scope loop; deep, release, human-assurance, and stop-hook controls
  MUST remain checkpoint controls until explicitly promoted.
- `AQG-RETRO-010` Each completed run MUST contain the immutable detailed
  evidence consumed by its classifiers plus a manifest that detects later
  mutation or deletion.
- `AQG-RETRO-011` Authoritative verification MUST use a grader selected by a
  protected base or immutable release identity, never solely by the candidate.
- `AQG-RETRO-012` Policy maintenance MUST be scoped to declared paths and
  operations, fingerprinted to the candidate and controls, independently
  approved, and rejected during ordinary authoritative checking.
- `AQG-RETRO-013` High-assurance completion MUST independently validate current
  verification, behavior approval, manual QA, and rollback evidence.
- `AQG-RETRO-014` All configured and detected required test roots, including
  repository-local quality-tool contract tests, MUST be collected.
- `AQG-RETRO-015` Active requirements MUST be mapped by stable requirement ID
  to executable test or acceptance evidence; incidental substring matches MUST
  NOT satisfy traceability.
- `AQG-RETRO-016` Acceptance mutation MUST support project-declared
  domain-valid semantic mutations and record whether each mutant reached the
  application boundary and where it was killed.
- `AQG-RETRO-017` Performance governance MUST use repeatable sampling,
  aggregation, and variance limits; unstable measurements MUST be classified
  as unusable evidence rather than product pass or failure.

## Related specifications

- `AgentQualityGauntlet`
- `AgentQualityGauntlet.Execution`
- `AgentQualityGauntlet.Review`
