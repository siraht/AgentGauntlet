# Productionization execution log

This is the durable progress, decision, evidence, and lessons ledger for taking Agent
Quality Gauntlet 2.0.0 from its recovered beta/ratchet state to a governed beta release.
Update it in the same commit as each material decision or completed slice.

## Objective

Complete every follow-up identified by the recovery audit:

1. require authoritative GitHub checks and review governance;
2. upgrade deprecated CI integrations and address actionable dependency advisories;
3. prove supported adapters in representative disposable projects;
4. reduce the highest-risk coverage and complexity debt without weakening thresholds;
5. dogfood the installed and source control surfaces end to end;
6. publish reproducible, checksummed, inventoried, and verifiable beta artifacts.

## Starting state

Recorded from public `main` at `431bdaa` on 2026-07-25:

- source CI passed on Python 3.11, 3.12, and 3.13;
- the deterministic release job passed;
- the local High-assurance `deep` profile passed against a clean `HEAD`;
- 27 Python source/acceptance tests and one JavaScript dashboard contract test passed;
- internal conformance passed 8/8 and installed-tool conformance passed 10/10;
- aggregate Python coverage was approximately 35% with branch coverage approximately 26%;
- changed-code ratcheting was active, so the clean deep pass did not certify inherited debt;
- human behavior review, manual QA, and rollback rehearsal records were absent;
- two moderate npm advisories remained below the configured high-severity audit threshold;
- GitHub Actions warned that several pinned action majors still used the deprecated Node 20 runtime;
- no branch ruleset or required-check policy protected `main`.

## Decisions

| ID    | Decision                                                                                         | Rationale                                                                                                                                                   | Revisit when                                                                    |
| ----- | ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| D-001 | Preserve the exact recovered baseline commit and its historical generated conformance file.      | Byte-for-byte recovery provenance is more valuable than rewriting already-public history; the file contains no secret and is deleted at current `HEAD`.     | A confirmed secret or legal issue is discovered in the historical object.       |
| D-002 | Keep the repository in `adopt` mode during remediation.                                          | Switching to strict whole-tree enforcement before inherited debt meets policy would turn known debt into permanent red CI or encourage threshold weakening. | Full-tree coverage, structure, and mutation evidence meet the selected profile. |
| D-003 | Make changes on `agent/productionize-v2-beta` in small reviewable commits.                       | Policy, dependency, test, refactor, release, and governance changes need separate rollback points and review surfaces.                                      | The productionization pull request merges.                                      |
| D-004 | Treat this effort as explicit policy maintenance.                                                | The user explicitly requested CI, governance, dependency, and gauntlet improvements that necessarily touch protected control-plane files.                   | Policy-plane work is complete.                                                  |
| D-005 | Prefer attestable automation over a locally stored private signing key.                          | Repository releases must be verifiable without creating or exposing a long-lived secret in the workspace.                                                   | A managed organizational signing identity is provided.                          |
| D-006 | Pin third-party GitHub Actions to reviewed immutable commits and let Dependabot propose updates. | Mutable major tags allow unreviewed workflow code to change; commit pins plus automated proposals preserve integrity and maintainability.                   | GitHub provides native immutable action references with equivalent automation.  |
| D-007 | Override Stryker's transitive `qs` dependency to `6.15.3`.                                       | Upstream pins vulnerable `6.15.1`; the patched release removes the findings without replacing the mutation engine.                                          | Stryker removes the dependency or ships a patched version.                      |

## Progress

| Phase                          | Status   | Evidence                                                                                               |
| ------------------------------ | -------- | ------------------------------------------------------------------------------------------------------ |
| Baseline and risk contract     | Complete | Goal created; baseline status and public remote verified; productionization branch created.            |
| CI and dependencies            | Complete | Node 24 actions pinned; workflow-pin tests pass; npm audit is clean; checker conformance passes 18/18. |
| Cross-stack conformance        | Pending  | —                                                                                                      |
| Coverage and complexity debt   | Pending  | —                                                                                                      |
| End-to-end dogfood             | Pending  | —                                                                                                      |
| Release and provenance         | Pending  | —                                                                                                      |
| GitHub governance              | Pending  | —                                                                                                      |
| Final independent verification | Pending  | —                                                                                                      |

## Lessons

- A clean changed-code profile proves control execution and current-diff health, not the
  quality of inherited code. Whole-tree metrics must remain visible beside ratchet status.
- Exact recovery provenance and clean current-tree hygiene are compatible when generated
  historical artifacts are retained only in the recovery commit and ignored thereafter.
- Release reproducibility is incomplete unless the final source state, embedded license,
  checksums, and published artifacts are all tied to the same revision.
- An exact transitive tool dependency can prevent normal audit remediation; a narrow root
  override is safer than accepting the advisory when conformance proves the tool still
  starts and propagates failures.
- Immutable action pins need an update mechanism. Dependabot keeps the review boundary
  explicit without freezing security patches indefinitely.

## Evidence conventions

- Record commands and immutable GitHub run or release URLs, not screenshots.
- Record a failed, skipped, stale, or inapplicable control as such; never summarize it as
  green.
- Human approvals must be completed by an actual human after final fingerprints exist.
- Temporary fixture repositories and runtime evidence live under ignored paths.
