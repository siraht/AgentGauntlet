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
- Deep shadow run `20260728-160101-b654b690` retained complete detailed
  evidence in a manifest that verifies with no added, deleted, modified, or
  unsafe paths. It reported four measured-failure categories, one missing
  assurance category, and one mutation infrastructure error.
- The mutation infrastructure error exposed three JavaScript isolation
  defects in sequence: a copied virtual-environment symlink, zero tests from
  related-test selection, and a protected Vitest config path that did not
  cross the sandbox. After those fixes, Stryker completed all 1,107 dashboard
  mutants. All survived, producing an honest 0% measured score. The Python
  half separately refuses the 3,209-line checkpoint before execution because
  it exceeds the protected 250-line mutation scope.

The real council result is now stale because later commits fixed one of its
blockers. It remains valid historical evidence and must not be presented as a
review of the current candidate.

A later high-tier run, `council-20260728T162532Z-060cf244`, exercised every
configured model. Three ballots were valid; Kimi-K3 timed out at 180 seconds,
so the security/trust role was missing and the run remained incomplete. Its
manifest verifies. The council found that high tier had selected a fast run
despite the high-assurance risk profile and that the risk card overstated the
greenfield pilot. Both findings were reproduced and fixed. High tier now
requires deep-or-release evidence. The resulting bounded slice passed
structure, 100% changed-line coverage, and 123/123 killed mutants with zero
survivors. The council's missing manual-QA and rollback findings remain open.

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

## 2026-08-30 — structural and resource-budget implementation plan

This checkpoint converts four agent-oriented maintainability controls into
deterministic, evidenced AQG policy. Cyclomatic complexity is already enforced;
the remaining work adds whole-file limits, direct CSS/JavaScript resource
budgets, and versioned ABC metrics without weakening existing thresholds or
turning inherited brownfield debt into an unrelated development blocker.

### Outcomes

- [x] Audit the current implementation rather than relying on documentation.
- [x] Confirm Python and JavaScript/TypeScript cyclomatic-complexity enforcement.
- [x] Confirm that current `lines` evidence means function lines, not file lines.
- [x] Confirm that CSS/JavaScript byte budgets exist only as guidance today.
- [x] Confirm that no explicit Assignments-Branches-Conditions metric exists.
- [x] Add a dependency-free deterministic kernel for physical lines, nonblank
      lines, raw bytes, and SHA-256 over an explicit source/test inventory.
- [x] Add kernel-level production, CSS, and test classifications with warning
      boundaries, hard boundaries, deterministic totals, and fail-closed input
      validation.
- [x] Add a dependency-free raw and deterministic-gzip CSS/JavaScript artifact
      kernel with individual-artifact and aggregate totals, warning headroom,
      hashes, stable ordering, and explicit build roots.
- [x] Add versioned `aqg-python-abc-v1` and `aqg-javascript-abc-v1` vectors and
      magnitudes. The definitions are deliberately language-specific.
- [x] Wire all four kernels through protected project defaults, scaffolded
      projects, adapters, retrospective inventory, and the intended profiles.
      The focused integration matrix passes; whole-profile evidence remains a
      separate checkpoint below.
- [x] Preserve existing complexity, nesting, function-length, CRAP, coverage,
      acceptance, and mutation controls alongside the new metrics.
- [x] Surface exact offenders, limits, headroom, and classification in normalized
      evidence and review reports.

### Brownfield and anti-gaming requirements

- [x] Extend retrospective inventory fingerprints to file lines, file bytes,
      ABC magnitude, individual asset bytes, and aggregate resource bytes.
- [x] Treat inherited Git-base excess as visible non-blocking debt.
- [x] Block new offenders and any increase to an inherited debt value.
- [x] Require every new governed file to meet the current hard limit.
- [x] Reject missing, stale, malformed, or unexpectedly empty build evidence as
      configuration or infrastructure error rather than a pass.
- [x] Make the source-budget kernel measure generated, vendored, and minified
      inventory entries while returning their exact exclusion reasons instead
      of silently discarding them.
- [ ] Prove the adapter's path classification and governed inventory cannot be
      evaded by renaming or moving files, and keep exclusions narrow and
      visible in run evidence.
- [ ] Detect or review wrapper-chain/file-sharding responses so splitting a file
      without reducing complexity or coupling is not accepted as pruning.
- [x] Never allow ordinary feature work to raise a budget or add an exclusion;
      threshold and exclusion changes remain protected maintenance operations.

### Execution-profile design

- [x] Keep source line/byte and ABC checks in the seconds-scale fast structure
      gate.
- [x] Run fresh built-artifact budgets at PR/checkpoint scope, not after every
      edit.
- [x] Keep sampled Lighthouse/browser transfer evidence in deep and release
      profiles as a complementary diagnostic, not a substitute for byte counts.
- [x] Record metric-definition versions and exact effective thresholds in each
      run so historical comparisons remain meaningful after adapter evolution.

### Verification and dogfood checklist

- [x] Add project-schema and scaffold-default contract tests for every new
      threshold.
- [x] Add 55 focused Python contracts for the Python ABC, source-size, and
      artifact-budget kernels, plus seven Vitest contracts for JavaScript,
      TypeScript, JSX, and TSX ABC measurement.
- [x] Exercise source and artifact warning/hard boundaries, UTF-8 and empty
      input, CSS/JavaScript totals, excluded generated/minified entries, stable
      ordering, missing/unreadable files, path escape, symlink hazards, stale
      artifacts, and invalid thresholds in focused kernel tests.
- [x] Prove at kernel level that two individually acceptable CSS files can fail
      their aggregate budget, so simple file splitting does not erase download
      size.
- [ ] Prove through the complete adapter that missing output, stale output,
      malformed configuration, and failed builds retain the correct 2/3 exit
      category and immutable detailed evidence.
- [x] Prove an inherited oversized file is reported but an unrelated conforming
      change remains unblocked.
- [x] Prove increasing that inherited file by one unit is rejected.
- [x] Prove a new oversized source file is rejected; built JS/CSS rejection is
      proved at the asset kernel and resource-adapter boundary.
- [x] Prove deliberate file splitting cannot erase aggregate asset-budget debt
      in the deterministic artifact kernel.
- [x] Run focused tests after each completed kernel slice. The committed kernel
      set currently has 55 passing Python tests and seven passing Vitest tests.
- [x] Refactor the source-size and artifact engines to pass their own starter
      caps: maximum cyclomatic complexity is 10 and 7 respectively; maximum
      ABC magnitude is 18.25 and 19.85 respectively.
- [x] Run the fast gauntlet after integration and retain immutable evidence.
      Clean-checkout enforced run `20260831-002818-77db63a1` passed in 51.4
      seconds and its manifest verifies.
- [x] Run the risk-selected deep checkpoint only after the implementation
      surface settles. Shadow run `20260831-000424-e49aef17` retained every
      result: implementation gates passed while inherited security findings,
      missing performance-service evidence, and assurance evidence remained
      explicitly non-green.
- [x] Dogfood the structure and resource adapters on AgentGauntlet in
      ratchet-compatible mode: both pass after the integration refactors.
      Whole-profile proof remains open because a pre-existing uncommitted README
      fails formatting/workspace-integrity and was deliberately not overwritten.
- [x] Revert every deliberate fault automatically through temporary test
      repositories rather than leaving fault files in the checkout.
- [x] Update adapter-catalog, project-status, and self-hosting guidance.
- [x] Produce granular commits and push only after local evidence is complete;
      GitHub Actions stayed disabled and was not invoked.

### Initial policy values to validate, not silently weaken

The first fixtures will exercise production source at 300-line warning/500-line
hard-cap, CSS at 300/450, tests at 600/800, and hand-written files at 75/100 KiB.
Built-web starter caps are 250 KiB gzip per JavaScript artifact, 400 KiB total
JavaScript, 75 KiB per CSS artifact, and 100 KiB total CSS. ABC magnitude starts
in shadow calibration with candidate caps of 20 for normal checks, 15 for deep,
and 10 for release. Project-specific changes to these starter values remain
protected policy maintenance and must be evidence-backed; existing thresholds
must not be lowered merely to obtain green output.

### Decisions and lessons

- File maintainability and user-download performance are different controls:
  source line/byte limits belong in structure, while compiled resource budgets
  require a fresh build and their own provenance.
- A direct byte count is deterministic. Lighthouse remains useful but a score
  can vary or conceal a large bundle on fast hardware.
- ABC terminology varies across ecosystems. AQG will publish versioned
  per-language counting rules and retain the full `<A, B, C>` vector instead of
  presenting an unexplained scalar as universal truth.
- Approaching a budget should generate ranked pruning guidance. Crossing the
  hard limit blocks growth; acceptable remediation must preserve behavioral
  contracts and pass tests, coverage, and mutation where applicable.

### Kernel evidence and current limitation

The completed kernels are recorded by commits `bc01c8c` (Python ABC),
`dd0c9b3` (source-file budgets), `a55f6cd` (web artifact budgets), `fec40a5`
(JavaScript/TypeScript ABC), and `6c625fe` (self-cap refactoring). Their focused
contracts prove deterministic measurement and failure behavior in isolation.

Commits `2489d5b`, `8f39461`, and `2fe0e11` integrate the kernels, add genuine
Git-base ratchets and focused adapter contracts, and keep conformance fixtures
aligned with canonical defaults. The project/schema/scaffold matrix reports 173
passing tests plus 80 subtests; the full unit adapter reports 768 passing Python
tests and 16 passing Vitest tests; AgentGauntlet's structure and static-resource
adapters both pass.

The rollout has now crossed the self-hosting boundary. Deep shadow run
`20260831-000424-e49aef17` produced proposal
`debt-20260831-000424-e49aef17-9d85bc4bf0c7`; verified council
`council-20260831T000637Z-94847c30` cleared that exact measured floor across all
five roles and three provider groups. Commit `5398f93` installed the reviewed
baseline through a scoped one-file maintenance request. Clean-checkout enforced
fast run `20260831-002818-77db63a1` then passed with six inherited items, zero
new debt, zero regressions, and a verified immutable manifest.

The risk-selected deep profile is not green and is not described as green:
security debt, missing performance-service evidence, and final assurance
evidence remain open. The generic policy-maintenance council also blocked the
baseline diff because it compared the baseline's intentional pre-install
measurement scope to the post-install candidate, exposing a self-reference
integration gap. That blocked council is retained immutably as
`council-20260831T002002Z-51787807`; the specialized baseline workflow itself
was authorized by the exact maintenance request and exact debt council. The
owner's unrelated README edit remains untouched.
