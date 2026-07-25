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

| ID    | Decision                                                                                         | Rationale                                                                                                                                                                            | Revisit when                                                                    |
| ----- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------- |
| D-001 | Preserve the exact recovered baseline commit and its historical generated conformance file.      | Byte-for-byte recovery provenance is more valuable than rewriting already-public history; the file contains no secret and is deleted at current `HEAD`.                              | A confirmed secret or legal issue is discovered in the historical object.       |
| D-002 | Keep the repository in `adopt` mode during remediation.                                          | Switching to strict whole-tree enforcement before inherited debt meets policy would turn known debt into permanent red CI or encourage threshold weakening.                          | Full-tree coverage, structure, and mutation evidence meet the selected profile. |
| D-003 | Make changes on `agent/productionize-v2-beta` in small reviewable commits.                       | Policy, dependency, test, refactor, release, and governance changes need separate rollback points and review surfaces.                                                               | The productionization pull request merges.                                      |
| D-004 | Treat this effort as explicit policy maintenance.                                                | The user explicitly requested CI, governance, dependency, and gauntlet improvements that necessarily touch protected control-plane files.                                            | Policy-plane work is complete.                                                  |
| D-005 | Prefer attestable automation over a locally stored private signing key.                          | Repository releases must be verifiable without creating or exposing a long-lived secret in the workspace.                                                                            | A managed organizational signing identity is provided.                          |
| D-006 | Pin third-party GitHub Actions to reviewed immutable commits and let Dependabot propose updates. | Mutable major tags allow unreviewed workflow code to change; commit pins plus automated proposals preserve integrity and maintainability.                                            | GitHub provides native immutable action references with equivalent automation.  |
| D-007 | Override Stryker's transitive `qs` dependency to `6.15.3`.                                       | Upstream pins vulnerable `6.15.1`; the patched release removes the findings without replacing the mutation engine.                                                                   | Stryker removes the dependency or ships a patched version.                      |
| D-008 | Generate explicit collection, unit, and coverage commands for every advertised test runner.      | Recognition without an executable evidence contract made Jest, Mocha, AVA, Node, and tox support aspirational rather than immediately usable.                                        | A runner changes its stable noninteractive command contract.                    |
| D-009 | Enforce Python structure at changed-function granularity in adopt mode.                          | Running Xenon against every function in a touched legacy file blocked unrelated edits and did not use AQG's configured line, complexity, or nesting limits.                          | The repository reaches strict whole-tree enforcement.                           |
| D-010 | Require c8 12 for non-Vitest JavaScript coverage.                                                | c8 10.1.3 introduced a high-severity glob/minimatch advisory chain; c8 12 removes it while retaining AQG's machine-readable evidence contract.                                       | c8 publishes a new reviewed major or a compatible native runner supersedes it.  |
| D-011 | Require both cross-platform command contracts and live disposable-project conformance.           | Static detection tests cannot expose runner discovery, module resolution, coverage-report, package-manager, browser-port, or generated-template failures.                            | The supported language or runner matrix changes.                                |
| D-012 | Decompose validators without changing diagnostic text or order.                                  | Configuration diagnostics are part of the operator and automation contract; reducing complexity must not make failures less stable or actionable.                                    | A versioned machine-readable diagnostic schema replaces text compatibility.     |
| D-013 | Make the CLI dispatcher declarative and JSON failures machine-readable.                          | A 353-line branch chain was difficult to extend safely, and plain-text exceptions made `--json` pipelines unable to distinguish configuration, quality, and infrastructure failures. | The public CLI contract advances to a new major schema version.                 |
| D-014 | Publish a deterministic, project-independent capabilities contract.                              | Agents need to discover commands, arguments, environment controls, output rules, and exit semantics from the binary instead of relying on stale external instructions.               | The contract schema needs a backwards-incompatible revision.                    |
| D-015 | Suggest corrections but never auto-execute guessed commands.                                     | Intent recovery should remove retry friction without turning an ambiguous alias into broader write authority or surprising side effects.                                             | A versioned alias becomes an explicitly documented public command.              |
| D-016 | Keep the agent operating guide embedded and project-independent.                                 | A cold agent must be able to discover safe setup and review workflows before it has a configured repository or external documentation context.                                       | Project-specific guidance needs a separate generated extension.                 |
| D-017 | Make triage a read-only aggregation over existing control models.                                | Daily orientation should collapse multiple calls without creating a second source of truth or allowing the overview command to mutate evidence.                                      | A measured hot-path bottleneck requires a cached projection.                    |

## Progress

| Phase                          | Status   | Evidence                                                                                                                                        |
| ------------------------------ | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Baseline and risk contract     | Complete | Goal created; baseline status and public remote verified; productionization branch created.                                                     |
| CI and dependencies            | Complete | Node 24 actions pinned; workflow-pin tests pass; npm audit is clean; checker conformance passes 18/18.                                          |
| Cross-stack conformance        | Complete | Six default live projects, Bun, and Playwright/axe pass; Linux/macOS/Windows CI matrix added.                                                   |
| Coverage and complexity debt   | Active   | Fresh baseline: 36.02% lines / 27.17% branches; detector, scaffold, adapter, project, and policy functions touched so far meet Standard limits. |
| End-to-end dogfood             | Pending  | —                                                                                                                                               |
| Release and provenance         | Pending  | —                                                                                                                                               |
| GitHub governance              | Pending  | —                                                                                                                                               |
| Final independent verification | Pending  | —                                                                                                                                               |

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
- A documented adapter is not production support until setup emits its collection, unit,
  coverage, and freshness contract without requiring the adopter to reverse-engineer it.
- File-level complexity checks are too coarse for legacy ratchets. Changed-function
  enforcement preserves inherited-debt visibility while requiring every touched function
  to meet the current profile.
- Real fixtures found integration failures that isolated unit tests missed: vendored test
  discovery, Jest array-option parsing, Node directory arguments, Yarn PnP artifacts, tox
  artifacts, Python src-layout imports, fixed browser ports, and protected ESM dependency
  resolution.
- Splitting configuration validation by contract dimension reduced structural risk while
  table-driven defect injection proved the exact messages operators and agents rely on.
- Public-control-surface dogfooding found an output-contract gap that internal calls hid:
  `--json` success paths were structured, but exceptions were stderr-only. Robot mode
  must cover failures as rigorously as successes.
- Deterministic-width help, explicit command sections, nested-command descriptions, and
  hidden internal verbs make human discovery and automated surface inventory more
  reliable; framework-default help formatting was not sufficient as a machine contract.
- A 277-case wrong-intent corpus is more revealing than a handful of hand-picked typos:
  it showed that global flag reordering worked, no path failed silently, and nearly every
  other mistake lacked a useful correction.

## Evidence conventions

- Record commands and immutable GitHub run or release URLs, not screenshots.
- Record a failed, skipped, stale, or inapplicable control as such; never summarize it as
  green.
- Human approvals must be completed by an actual human after final fingerprints exist.
- Temporary fixture repositories and runtime evidence live under ignored paths.
