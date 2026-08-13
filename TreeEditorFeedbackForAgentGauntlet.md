# Tree Editor feedback for AgentGauntlet

## Context

This feedback comes from applying AgentGauntlet to the public TypeScript Obsidian plugin
`ObsidianTreeEditor`. The product change was deliberately narrow: harden one Markdown-row parser
and add executable evidence without replacing Obsidian's native editor. The final candidate had 50
passing tests, 100% coverage of the 43 changed executable lines, 150 production mutants with zero
survivors, and 50 acceptance-data mutants with zero survivors. It was also exercised in an isolated
official Obsidian 1.13.7 host.

AgentGauntlet materially improved the plugin. Mutation testing found real weak boundaries, and the
review packet forced missing acceptance and recovery claims to become executable. The experience
also exposed several places where the evaluator can currently produce misleading or unnecessarily
difficult results for a normal third-party application.

## What worked especially well

1. **Changed-code mutation was useful rather than ceremonial.** Surviving mutants led directly to
   better tests for list markers, inline code, malformed percent escapes, local versus external
   links, subpaths, titles, and source ordering.
2. **Acceptance-data mutation exposed shallow scenario handlers.** The first runner did not prove
   that every Gherkin value influenced application behavior. Requiring mutations to reach the
   application boundary produced a much stronger runner.
3. **The risk card correctly elevated frontmatter writes and concurrent updates.** Treating these as
   data-loss and concurrency risks was appropriate even for a small plugin.
4. **Evidence classification was generally honest.** Configuration, infrastructure, and product
   failures were kept distinct, and the council did not turn missing host evidence into approval.
5. **The immutable run directories made diagnosis possible.** Detailed gate JSON and logs allowed
   every headline number to be checked after the run.

## Highest-priority improvements

### 1. Make assurance surfaces project-configurable

The high-assurance validator currently hard-codes AgentGauntlet's own public surfaces:

```python
_QA_CHECKS = {"cold_start", "setup", "review", "conformance", "dashboard", "tui"}
```

It also hard-codes matching duration keys. An Obsidian plugin has no AgentGauntlet dashboard or TUI,
so its honest plugin-specific rehearsal is rejected even when it proves exact-candidate startup,
frontmatter writes, rollback, cleanup, and host behavior. This was the sole non-passing gate in the
final Tree Editor deep run.

Recommended design:

- define named public surfaces and required evidence in `quality/project.json`;
- validate a generic map of configured checks rather than one product's names;
- retain universal requirements for exact revision, source digest, disposable cleanup, rollback,
  timings, and result identity;
- report an incompatible evaluator schema as `not_applicable` or configuration error, rather than a
  product quality failure;
- ship AgentGauntlet's own dashboard/TUI list as its dogfood configuration, not evaluator code.

### 2. Provide a first-class external-control mode

Vendoring AgentGauntlet into the subject worktree added roughly 39,000 evaluator lines to the review
surface. It made product diffs noisy and initially allowed candidate-owned configuration to affect
the grader. We ultimately created separate baseline, candidate, and control worktrees and excluded
the evaluator from the clean deliverable.

A supported command such as the following would make the trust boundary explicit:

```text
aqg evaluate --subject /path/to/candidate --base <revision> --evidence /outside/path
```

It should execute from a pinned control checkout, install only adapters in an isolated work area,
write evidence outside the subject repository, and bind subject revision, subject tree digest,
control digest, policy digest, and base revision. The subject should never need to commit the
evaluator runtime merely to be evaluated.

### 3. Detect vacuous production mutation caused by path classification

The generated project configuration classified `src` as a test root. Changed-code mutation then
excluded the changed production file and could appear to pass without mutating product behavior.
After correcting the roots, the same code produced 203 real mutants and many survivors.

AgentGauntlet should fail configuration when:

- a test root contains production files selected by source detection;
- a changed executable production file is excluded solely because it sits beneath a broad test
  root;
- the coverage report names a changed production file but mutation selects none;
- `paths.tests`, stack-native include patterns, and production discovery disagree;
- the mutation gate is applicable but the final mutation target list is empty.

The run summary should always print the exact production files selected for coverage and mutation.

### 4. Replace regex-based dynamic-code detection with syntax-aware detection

The deep security scanner treated ordinary JavaScript/TypeScript `RegExp.exec()` calls as dynamic
program execution. That creates a false incentive to rewrite normal code for the scanner.

At minimum, `exec(` should only match the free function form, not a property call such as
`matcher.exec(`. Preferably use a JavaScript/TypeScript parser and distinguish:

- `eval(...)`, `new Function(...)`, and actual dynamic execution;
- `child_process.exec(...)`, which is shell execution and needs its own rule;
- `RegExp.prototype.exec(...)`, which is ordinary parsing.

Every security finding should include rule ID, language, exact construct, and a safe/unsafe example.

### 5. Remove the assurance/council dependency cycle

The assurance gate required a current clear council result, while the council blocked because the
deep run was not green at assurance and because host evidence was not in that earlier run. This
creates a cycle:

```text
deep run needs council -> council needs passing deep evidence -> deep run needs council
```

Recommended staged workflow:

1. run deterministic pre-assurance gates and produce a manifested candidate packet;
2. execute and ingest functional/manual host evidence;
3. run the independent council against that exact packet;
4. finalize assurance without rerunning or changing the candidate;
5. seal one aggregate manifest.

The CLI should expose these stages and report the next exact command.

### 6. Ingest manual and external-host evidence into the run manifest

The Obsidian host evidence had exact host and bundle hashes, screenshots, before/after files,
geometry, restart results, and empty error logs. AgentGauntlet had no standard mechanism to ingest
it after execution. Files placed under `.aqg/manual` were ignored and invisible to the previous
council bundle.

Add a command such as:

```text
aqg evidence add --type host-qa --procedure QA-OTE-LP-001 --from /outside/evidence
```

It should:

- copy evidence into an immutable run-owned directory;
- hash every artifact;
- bind it to the exact product and host identities;
- distinguish `pass`, `partial_pass`, `blocked`, `fail`, and `not_run` per procedure case;
- prevent an overall pass when only a subset of cases has evidence;
- make the evidence available to review, council, owner status, and assurance.

### 7. Report mutation outcomes without compressing uncertainty into “100%”

The final production campaign generated 150 mutants: 105 were killed, 6 timed out, and 39 caused
compile errors. Stryker displayed a 100% mutation score because no executable mutant survived, but
“100%” is easy to misread as “all 150 were behaviorally killed.”

The top-level summary should always show all outcome classes and two scores:

- behavioral score: killed / executed valid mutants;
- disposition coverage: mutants with a reviewed terminal classification / all generated mutants.

Timeout and compile-error budgets should be configurable. Exceeding them should yield incomplete or
unusable evidence, not silently improve the headline score.

### 8. Preserve applicability in every owner-facing summary

The Tree Editor performance gate appeared as `pass`, but its details said `not_applicable`; no
1,000-line/200-row host performance fixture had run. A lay reader will understandably interpret the
headline as a performance test passing.

Use distinct display states everywhere:

- `pass (executed)`
- `pass (inherited debt comparison)`
- `not applicable`
- `not run`
- `infrastructure error`
- `quality failure`

Never render an inapplicable gate with a green checkmark identical to an executed pass.

## Additional improvements

### Acceptance mutation quality

The Tree Editor campaign generated 50 generic string corruptions and zero domain-semantic mutants.
The generic mutations were useful, but values such as `rxtry after file error` mostly prove strict
string matching. AgentGauntlet should warn when a high-assurance acceptance campaign has
`semantic_total = 0`, offer examples for project-defined semantic mutation rules, and distinguish
schema-invalid mutations from valid but behaviorally different examples.

### Finished-run metadata

The final deep run had all gate artifacts but `finished_at: null`. A completed or aborted run should
always receive a terminal timestamp and reason before the manifest is sealed.

### Faster iterative mutation

The full changed-parser campaign took roughly 100 seconds per final run, and several iterations were
needed. A documented “survivors only” continuation, content-addressed mutant cache, or stable
per-file campaign resume would preserve rigor while improving the development loop. Cached results
must remain bound to source, tests, toolchain, configuration, and control fingerprints.

### Concise diagnostics

Some JSON details expanded into tens of thousands of lines. Keep complete immutable artifacts, but
add a concise diagnostic view containing target files, thresholds, counts, survivors, timeouts,
compile errors, first actionable error, and reproduction command.

### Make external verifier results importable without pretending they are release authority

The independent read-only verifier was useful, but its conclusion could not satisfy the expected
council JSON shape. AgentGauntlet should support a manifested external-verifier evidence type with
clear authority metadata: technical verification can satisfy a configured separation-of-duties
control while still granting no human approval, merge permission, or release authority.

## Suggested acceptance tests for AgentGauntlet

1. A TypeScript subject with `src/foo.ts` and `src/foo.test.ts` must mutate `foo.ts`, even when setup
   was given an overly broad test hint.
2. `regex.exec(text)` must not trigger the dynamic-code rule; `eval(text)`, `new Function(text)`, and
   `child_process.exec(text)` must trigger their appropriate rules.
3. A plugin declaring host surfaces `load`, `edit`, `restart`, and `rollback` must pass the generic
   rehearsal validator without supplying dashboard/TUI evidence.
4. An inapplicable performance gate must never appear as an executed pass in JSON, CLI, TUI,
   dashboard, Markdown review, or CI summary.
5. A run with only 105 killed mutants out of 150 generated must display 105 killed, 6 timeout, 39
   compile error, and zero survived beside any calculated score.
6. A host-QA evidence import marked partial must remain partial through review, council, assurance,
   and owner-status views.
7. The staged council workflow must have no circular dependency and must finalize only when every
   artifact is exact-candidate and manifest-current.
8. A completed keep-going run must always have `finished_at`, terminal status, and a verified
   manifest.

## Bottom line

AgentGauntlet found real problems and made the Tree Editor candidate better. Its strongest ideas are
changed-code mutation, acceptance-boundary mutation, explicit risk selection, immutable evidence,
and fail-closed classification. The main architectural improvement is to separate universal
assurance invariants from AgentGauntlet's own dogfood surfaces. With a first-class external-control
mode and standard host-evidence ingestion, the tool would be much easier to apply honestly to
plugins, desktop applications, services, and other products whose public interfaces are not a CLI,
dashboard, and TUI.

---

## Follow-up campaign: immediate multi-select and calculated fields (2026-08-13)

This section records a second full application of AgentGauntlet to the code added after the first
campaign. The reviewed product delta added immediately persisted multi-select controls, virtual
calculated fields, and calculated values synchronized to frontmatter. The final cleaned candidate
builds, type-checks, passes all 60 unit/component tests, passes AgentGauntlet's deep lint and
structure adapters, and passed focused testing in an isolated official Obsidian 1.13.7 host. The
host test proved immediate multi-select persistence, repeated-reference refresh, virtual and saved
recalculation, cold-start persistence, plugin disable/rollback, unchanged source Markdown, and
empty console/page-error logs.

AgentGauntlet again found useful product defects. Its complexity limits drove the formula tokenizer,
parser/evaluator, CodeMirror decoration builder, field widgets, schema normalization, and Obsidian
modal/plugin initialization into smaller typed units. The review also led to a concrete undo bug:
an automatic saved-calculation write replaced the user's undo checkpoint. Automatic derived writes
now bypass user undo history, with a regression test and a real-host test proving that Undo restores
the user's field while keeping the current calculated output. Formula modulo-by-zero handling was
also made explicit, and the parser no longer depends on a monolithic numeric regular expression.

### New evaluator issues found in this campaign

#### 1. Diagnose a missing ratchet baseline before running the gates

Every measured fast gate passed, yet the command finished as `configuration_error` because ratchet
mode required a current reviewed debt baseline. `doctor` did not identify that specific prerequisite,
and the ordinary command summary did not print the reason; it was discoverable only in the run's
retrospective JSON.

Before an expensive check, `doctor`, `status`, `triage`, and `check` should all preflight the exact
baseline required by the selected enforcement stage. If it is missing or stale, print the reason
and the legitimate next command. The measured-gate result should remain separately visible as
“all executed gates passed; certification unavailable because …” rather than being collapsed into
one confusing status.

#### 2. Make “changes since the last successful run” a first-class review scope

This follow-up was explicitly about code added since the previous gauntlet. Reconstructing that
scope required an isolated worktree and manually replaying the intervening commits. The configured
long-lived base still selected large previously reviewed files, including the whole Obsidian host
entrypoint, so changed-line coverage and mutation measured the wrong-sized surface.

Add a scope selector such as `--since-run <run-id>` or `--since-evidence latest-passing`, bound to
the prior run's exact candidate tree and control fingerprints. `changed-files`, coverage, mutation,
review, council, and assurance must all consume the same sealed scope. The CLI should display that
scope before execution.

#### 3. Do not demand headless line coverage for a host-only entrypoint without an integration path

The deep coverage adapter reported 55.1% changed-line coverage against a 95% threshold. It counted
992 changed executable lines and assigned `src/main.ts` and `src/obsidian-adapter.ts` 0% because the
Vitest adapter cannot load the real Obsidian Electron API. That is neither evidence that the host
code is bad nor evidence that it works; it is an applicability mismatch. A real Obsidian run did
exercise the critical paths, but AgentGauntlet could not ingest or credit it.

Coverage policy should support explicit per-surface evidence routes: unit coverage for pure modules,
component coverage for CodeMirror widgets, and manifested host/integration evidence for Electron
entrypoints. Excluding a file must require a documented alternative evidence source, not silently
remove scrutiny. This is the same architectural need as configurable assurance surfaces and host
evidence ingestion noted above.

#### 4. Bound and explain mutation scope before starting a long campaign

The changed mutation gate instrumented seven files with 3,111 mutants and ran for 24 minutes. Its
final score was 35.28%: 735 killed, 33 timed out, 384 survived, 1,025 had no coverage, and 934 ended
as errors. `main.ts` alone contributed 809 no-coverage mutants and 235 errors. During the profile
run, the useful progress lines were captured inside the child command rather than streamed by the
gate wrapper, so the owner-facing console appeared idle for nearly the entire campaign.

Before execution, print target files, executable lines, estimated mutant count, uncovered target
lines, concurrency, timeout, and an estimated range. Stream normalized progress. If a host-only file
has zero dry-run coverage, fail the campaign preflight or classify it as requiring another evidence
route rather than spending time generating hundreds of non-actionable mutants. Provide per-file
resume and survivor-only reruns bound to exact source/test/tool fingerprints.

#### 5. Keep fast and deep lint policy differences visible

The fast lint gate passed while deep lint later found 16 complexity and function-length violations.
The stricter deep limits were useful, but the difference was not visible until after the expensive
profile had started. `status` or `check-risk --plan` should show profile-specific thresholds and
which files currently violate the required profile, allowing a cheap preflight before coverage and
mutation.

#### 6. Make review heuristics semantic enough to avoid obvious false positives

The review packet flagged a new TODO debt marker at a textarea placeholder containing the ordinary
label `To do`. It also flagged deleted test assertions after tests were split and reformatted, even
though the net test diff added hundreds of lines and a new undo regression case. Finally, merely
changing files named `contracts.ts` and `schema.ts` forced an external-contract risk mismatch
without distinguishing internal TypeScript contracts from a public network/file contract.

Recommended fixes:

- tokenize comment debt markers and require word/case/context appropriate to comments, excluding
  string literals such as UI copy;
- compare test identities and assertion ASTs across renames/refactors instead of treating deleted
  diff lines as deleted evidence;
- report whether an assertion was removed without replacement, moved, or strengthened;
- make external-contract inference language- and export-aware, and present path-name matches as a
  human prompt rather than a blocker unless policy explicitly requires otherwise.

#### 7. Surface full failure reasons in the normal CLI summary

The deep run ended as `infrastructure_error`, while its meaningful inventory contained product
quality failures (lint, structure, coverage, mutation, review), a configuration error (missing debt
baseline), and missing/incompatible assurance evidence. The short console summary did not explain
this mixed outcome. Reading individual gate detail JSON was required to understand it.

End every run with a concise categorized table: product failures, configuration errors,
infrastructure failures, missing evidence, inapplicable gates, and exact next commands. Preserve the
immutable detail files, but do not require users to reverse-engineer a headline status from them.

### Suggested new acceptance tests

1. A ratchet-stage project without a reviewed baseline must be diagnosed before any expensive gate,
   and the CLI must still report the separate result of any explicitly requested measured run.
2. `--since-run` must reproduce exactly the product delta after a sealed prior run across changed
   files, coverage, mutation, review, council, and assurance.
3. A UI string containing `To do` must not trigger a TODO/FIXME production-debt rule; an actual
   `// TODO:` comment must trigger it.
4. Splitting one test suite into several `describe` blocks without removing semantic assertions must
   not trigger “test assertions deleted.”
5. A host-only entrypoint with zero headless coverage and declared host evidence must be classified
   as requiring that evidence route, not mutated as thousands of uncovered sites.
6. Profile planning must show that deep complexity limits differ from fast limits before executing
   coverage or mutation.
7. A 20-minute child mutation command must stream progress and expose a resumable campaign ID.
8. A mixed run must summarize every distinct product, configuration, infrastructure, missing, and
   inapplicable outcome without forcing inspection of retrospective JSON.

### Follow-up bottom line

The second campaign again justified using AgentGauntlet: it materially improved architecture and
helped expose a real cross-feature undo bug. Its largest remaining problem is scope and evidence
routing. When a pure TypeScript core, CodeMirror UI, and native Obsidian host are treated as one
uniform headless surface, the tool spends substantial time producing numbers that are technically
correct for its adapter but misleading about the product. A sealed “since last run” scope, early
ratchet preflight, semantic review heuristics, streamed mutation progress, and configurable
per-surface evidence would make the same rigor far more accurate and practical.
