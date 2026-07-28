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

## 2026-07-28 — retrospective control plane implemented

The first implementation checkpoint closed the audit's principal trust gaps:

- `qg audit shadow` executes a normal profile, preserves its measured result,
  and makes only measured quality debt non-blocking. Missing evidence,
  configuration errors, infrastructure errors, and unknown intent remain
  nonzero.
- Retrospective evidence now has a normalized debt inventory and separate
  counts for measured failures, blocking failures, inherited debt,
  regressions, missing evidence, configuration errors, infrastructure errors,
  unknown product intent, new debt, resolved debt, and invalid debt.
- A debt proposal can be created only from a clean manifested shadow run over
  the exact current controls and change surface. The proposal has no authority.
  Installing `quality/baselines/debt.json` requires an explicit reviewer,
  scoped local maintenance request, protected diff, and external code-owner
  approval.
- Ratchet enforcement compares every fingerprint and value against the
  reviewed baseline. Equal inherited debt is reported but non-blocking;
  new, worsened, malformed, or unclassified debt blocks.
- Enforcement stage is explicit and monotonic:
  `shadow -> ratchet -> strict`. Promotion commands report readiness or write a
  non-authorizing proposal; they never edit protected policy.
- Every completed run snapshots classifier input, summary, and retrospective
  evidence into its run directory and finalizes a manifest. Later additions,
  deletions, byte changes, unsafe paths, malformed metadata, and identity
  mismatch are detected.
- The high-assurance gate now requires current behavior review, manual QA,
  rollback rehearsal, and independent verification records. Their
  fingerprints invalidate after a relevant change.
- The protected-base GitHub workflow checks out base controls and candidate
  source separately. Candidate changes to the grader, policy, project model,
  toolchain definitions, or launcher do not select the authoritative grader.
- Policy maintenance has exact add/modify/delete/rename scope and current
  independent approval. Local override use cannot make doctor, gates,
  conformance, or risk-selected checks pass.
- Every configured test root, including `quality/tests`, is collected.
  All 44 active requirements have exact stable-ID mappings; incidental
  substrings do not count.
- Public risk, gate, run, retrospective, manifest, baseline, and release JSON
  schemas have executable contract tests and are installed into every target
  repository by source and portable setup.
- Acceptance mutation uses declared domain-valid semantic mappings, requires
  application-boundary trace, and records kill stage. The current setup
  campaign kills all four semantic mutants after the boundary.
- Performance evidence uses one warmup plus three retained samples, median
  aggregation, and a protected spread limit. Incomplete, malformed, or
  unstable samples are infrastructure errors.

## 2026-07-28 — current dogfood evidence

The repository remains deliberately at `enforcement.stage=shadow`. Stop-hook
enforcement remains disabled.

| Evidence                                         | Result                                                                                                      |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| Inner profile `20260728-033206-93fec66d`         | pass in 21.1 seconds                                                                                        |
| Complete configured source tests                 | 414 Python and 1 JavaScript test passed in 29.2 seconds                                                     |
| Fast shadow `20260728-025824-54fea6aa`           | command pass; observed quality failure in 62.6 seconds                                                      |
| Fast-shadow taxonomy                             | 108 unreviewed structure items; 0 blocking, missing, configuration, infrastructure, or unknown-intent items |
| Shadow manifest                                  | verified, with no added, deleted, modified, or unsafe evidence                                              |
| Baseline proposal                                | `debt-20260728-025824-54fea6aa-f9adbbf355f1`; proposed only, not authority                                  |
| Stable performance `manual-2026-07-28T023019Z`   | 3/3 samples for both budgets, median 1.0, spread 0                                                          |
| Semantic acceptance mutation                     | 4/4 killed after application-boundary entry                                                                 |
| High-assurance probe `manual-2026-07-28T014047Z` | correctly reports four missing approval records                                                             |
| Strict-readiness inventory                       | 68.47% lines, 57.67% branches, 62 functions above the unchanged Standard cap                                |

The bounded production slice `require_document_contract` was measured against
`88ffec11cdb371cfafbc712a68bc06dc00560a58`:

- structure run `manual-2026-07-28T031508Z`: pass, complexity 2;
- coverage run `manual-2026-07-28T031517Z`: pass, four executable changed
  lines at 100%, CRAP 2;
- mutation run `manual-2026-07-28T031828Z`: pass, 100% selector coverage,
  10 killed, 0 survived, 0 incomplete, score 100%;
- all three run manifests verify.

The campaign first found and preserved three useful failures:

1. A refactor with unmappable executable deletions was rejected as
   configuration error instead of mutation passing vacuously.
2. The nested mutmut sandbox omitted the required `./aqg` launcher, so
   `quality/tests` failed during stats collection. AQG classified all mutants
   as unchecked infrastructure error. The sandbox now carries the launcher.
3. The first complete bounded campaign killed 9/10 mutants and exposed an
   unobserved multi-error delimiter. The assertion was strengthened; the
   rerun killed all 10.

A deliberate untracked production probe was then introduced and removed.
Structure run `manual-2026-07-28T032054Z` rejected it at complexity 11 > 10,
proved the new-file changed scope, and has a valid immutable manifest. The
worktree was clean after removal.

## Decisions and lessons

- A shadow command may be non-blocking only for measured quality debt. It must
  never erase the observed nonzero result from evidence.
- A baseline is policy authority, not generated cache. An agent may propose
  exact bytes, but cannot review or install its own proposal.
- Whole-branch changed scope is intentionally large on this productionization
  PR. Bounded implementation proofs therefore name their comparison revision;
  authoritative PR evidence still measures the complete PR against
  `origin/main`.
- Mutation must preserve the repository's complete test topology and runtime
  contract inside its nested sandbox. A partial copy is unusable evidence.
- Manifested failures are useful output. Refusing unmappable deletion scope,
  surfacing an assertion survivor, and rejecting missing assurance records are
  successes of the control system, not reasons to lower thresholds.
- Candidate-controlled and protected-base evidence remain side by side until
  the trusted workflow has landed on the default branch and the new required
  context has been observed there.

## Authority still required

The builder has not performed these human actions:

- review every item in a fresh replacement debt proposal and approve or reject
  the complete inventory;
- independently approve the protected baseline and stage changes;
- provide current behavior-review, manual-QA, rollback-rehearsal, and
  independent-verification evidence;
- merge the trusted workflow under the existing ruleset, observe it on
  `main`, then add `trusted-policy-evidence` to the live required contexts.

Until those actions occur, self-hosting remains shadow-only and no report may
claim ratchet or strict certification.

## 2026-07-28 — accessible control surface and advisory council checkpoint

- One shared owner-status model now drives CLI and dashboard Develop, Merge,
  and Release decisions. It reports exact-candidate evidence freshness,
  inherited debt, current regressions, approvals, and council advice without
  manufacturing hosted authority.
- The strict connected TypeScript/web fixture passed test integrity, unit and
  property tests, structure, changed coverage, and acceptance in 5.121
  seconds.
- A real PR-tier council run
  `council-20260728T150659Z-f5dc6c02` used Grok 4.5, Synthetic GLM-5.2, and
  OpenCode DeepSeek V4 Flash. Three valid ballots from three provider groups
  produced two blocker findings and preserved dissent in a verifying
  immutable manifest.
- That council correctly found missing explicit data classification/provider
  routing. The workflow now requires a classification and permits external
  calls only for explicitly `public` bundles. Restricted classifications fail
  before a provider call until an approved enterprise or local route exists.
- The latest fast checkpoint before final documentation passed its command
  contract in shadow mode in 80.5 seconds. It reported ten unreviewed
  structure-debt items and zero blocking regressions, missing evidence,
  configuration errors, infrastructure errors, or unknown-intent items.
- The current inner profile passes format, lint, and typing in approximately
  21 seconds. It is the editing loop; fast remains a coherent checkpoint.
- The bounded council-evidence slice passed deep structure, reached 100%
  changed-line coverage, and completed 187/187 killed mutants with 100%
  selection coverage. The mutation campaign first found two volatile triage
  timestamps and 43 assertion survivors; both failures remained visible until
  the production contract and tests were corrected.

The real council result is now stale because later commits fixed one of its
blockers. It remains valid historical evidence and must not be presented as a
review of the current candidate.

## Next checkpoint

After the final code and documentation surface settles:

1. run a fresh fast and deep shadow checkpoint and retain every non-quality
   error;
2. calibrate the advisory council on seeded defects and approved public
   bundles;
3. later obtain independent review of the proposed debt inventory and policy
   change;
4. install the reviewed baseline and promote to ratchet in one protected PR;
5. rerun fast in enforcing mode and keep stop-hook enforcement disabled until
   repeated green timing is stable;
6. retire debt without increasing any reviewed fingerprint, then propose
   strict only after a current debt-free enforcing deep pass.
