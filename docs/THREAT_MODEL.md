# Threat model for agent-authored code

## Protected assets

- product requirements and acceptance expectations;
- user data and authorization boundaries;
- source and release artifacts;
- quality policy and thresholds;
- CI credentials and deployment permissions;
- evidence used to approve changes.

## Adversaries and failure sources

The coding agent is not assumed malicious, but it is treated as an untrusted optimizer that may take the easiest path to satisfy a prompt. It may misunderstand intent, overfit tests, weaken assertions, game metrics, reuse stale artifacts, hide uncertainty, or modify the checks that judge it. Dependencies, test frameworks, caches, and CI infrastructure can also fail.

Indirect policy changes count as policy changes. Redefining an `npm`, Make, Gradle, Maven, or task-runner alias; changing test discovery or coverage exclusions; updating a mutation manifest without executing mutations; or regenerating a baseline without review can weaken a gate while leaving the top-level policy file untouched.

## Primary controls

- human-owned observable contracts;
- risk-tiered gates;
- protected policy plane;
- clean CI and branch protection;
- deterministic hooks;
- read-only verifier;
- test-integrity checks;
- source and acceptance mutation;
- content-hashed evidence;
- hashes that cover the full behavior-relevant execution surface rather than generated entrypoints alone;
- infrastructure-error status;
- least-privilege sandbox and network;
- canary, telemetry, and rollback.

## Residual risk

No finite test suite proves absence of defects. The system reduces the probability and impact of errors by combining independent forms of evidence and operational recovery. Critical scopes retain human code review and independent release approval.
