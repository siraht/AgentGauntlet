# Release readiness

> Release approval is a decision over a specific immutable revision, evidence set, artifact, rollout plan, and recovery capability.

## Required packet

- resolved risk card and applicable active requirements;
- current passing required profile with matching revision/change/control fingerprints;
- blockers resolved and human review prompts decided;
- mutation survivors triaged;
- security/dependency/secret findings triaged;
- QA and accessibility evidence as applicable;
- migration rehearsal and reconciliation plan;
- artifact digest, SBOM/provenance/attestation where required;
- observability, alert thresholds, staged rollout, kill switch, and rollback/recovery evidence;
- named approvals with independence for critical releases.

## Artifact flow

Build once from a clean protected runner, attest it, and promote the same digest through environments. Rebuilding for production creates a new unverified artifact. Verify signatures/attestations and deployment inputs before promotion.

## Rollout

Use canary, cohort, feature flag, or traffic percentage appropriate to blast radius. Define automatic and human stop conditions before starting. Observe both technical and business invariants. Rollback plans account for migrations and data written by the new version.

## Decision

`pass` means every required item is current and no unresolved blocker remains. `blocked` is distinct from fail and cannot be overridden by optimism. Any source, test, specification, dependency, control, or artifact change after approval invalidates the decision.
