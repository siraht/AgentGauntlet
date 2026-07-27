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

| ID    | Decision                                                                                         | Rationale                                                                                                                                                                                                                                                                                                                                         | Revisit when                                                                                                     |
| ----- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| D-001 | Preserve the exact recovered baseline commit and its historical generated conformance file.      | Byte-for-byte recovery provenance is more valuable than rewriting already-public history; the file contains no secret and is deleted at current `HEAD`.                                                                                                                                                                                           | A confirmed secret or legal issue is discovered in the historical object.                                        |
| D-002 | Keep the repository in `adopt` mode during remediation.                                          | Switching to strict whole-tree enforcement before inherited debt meets policy would turn known debt into permanent red CI or encourage threshold weakening.                                                                                                                                                                                       | Full-tree coverage, structure, and mutation evidence meet the selected profile.                                  |
| D-003 | Make changes on `agent/productionize-v2-beta` in small reviewable commits.                       | Policy, dependency, test, refactor, release, and governance changes need separate rollback points and review surfaces.                                                                                                                                                                                                                            | The productionization pull request merges.                                                                       |
| D-004 | Treat this effort as explicit policy maintenance.                                                | The user explicitly requested CI, governance, dependency, and gauntlet improvements that necessarily touch protected control-plane files.                                                                                                                                                                                                         | Policy-plane work is complete.                                                                                   |
| D-005 | Prefer attestable automation over a locally stored private signing key.                          | Repository releases must be verifiable without creating or exposing a long-lived secret in the workspace.                                                                                                                                                                                                                                         | A managed organizational signing identity is provided.                                                           |
| D-006 | Pin third-party GitHub Actions to reviewed immutable commits and let Dependabot propose updates. | Mutable major tags allow unreviewed workflow code to change; commit pins plus automated proposals preserve integrity and maintainability.                                                                                                                                                                                                         | GitHub provides native immutable action references with equivalent automation.                                   |
| D-007 | Override Stryker's transitive `qs` dependency to `6.15.3`.                                       | Upstream pins vulnerable `6.15.1`; the patched release removes the findings without replacing the mutation engine.                                                                                                                                                                                                                                | Stryker removes the dependency or ships a patched version.                                                       |
| D-008 | Generate explicit collection, unit, and coverage commands for every advertised test runner.      | Recognition without an executable evidence contract made Jest, Mocha, AVA, Node, and tox support aspirational rather than immediately usable.                                                                                                                                                                                                     | A runner changes its stable noninteractive command contract.                                                     |
| D-009 | Enforce Python structure at changed-function granularity in adopt mode.                          | Running Xenon against every function in a touched legacy file blocked unrelated edits and did not use AQG's configured line, complexity, or nesting limits.                                                                                                                                                                                       | The repository reaches strict whole-tree enforcement.                                                            |
| D-010 | Require c8 12 for non-Vitest JavaScript coverage.                                                | c8 10.1.3 introduced a high-severity glob/minimatch advisory chain; c8 12 removes it while retaining AQG's machine-readable evidence contract.                                                                                                                                                                                                    | c8 publishes a new reviewed major or a compatible native runner supersedes it.                                   |
| D-011 | Require both cross-platform command contracts and live disposable-project conformance.           | Static detection tests cannot expose runner discovery, module resolution, coverage-report, package-manager, browser-port, or generated-template failures.                                                                                                                                                                                         | The supported language or runner matrix changes.                                                                 |
| D-012 | Decompose validators without changing diagnostic text or order.                                  | Configuration diagnostics are part of the operator and automation contract; reducing complexity must not make failures less stable or actionable.                                                                                                                                                                                                 | A versioned machine-readable diagnostic schema replaces text compatibility.                                      |
| D-013 | Make the CLI dispatcher declarative and JSON failures machine-readable.                          | A 353-line branch chain was difficult to extend safely, and plain-text exceptions made `--json` pipelines unable to distinguish configuration, quality, and infrastructure failures.                                                                                                                                                              | The public CLI contract advances to a new major schema version.                                                  |
| D-014 | Publish a deterministic, project-independent capabilities contract.                              | Agents need to discover commands, arguments, environment controls, output rules, and exit semantics from the binary instead of relying on stale external instructions.                                                                                                                                                                            | The contract schema needs a backwards-incompatible revision.                                                     |
| D-015 | Suggest corrections but never auto-execute guessed commands.                                     | Intent recovery should remove retry friction without turning an ambiguous alias into broader write authority or surprising side effects.                                                                                                                                                                                                          | A versioned alias becomes an explicitly documented public command.                                               |
| D-016 | Keep the agent operating guide embedded and project-independent.                                 | A cold agent must be able to discover safe setup and review workflows before it has a configured repository or external documentation context.                                                                                                                                                                                                    | Project-specific guidance needs a separate generated extension.                                                  |
| D-017 | Make triage a read-only aggregation over existing control models.                                | Daily orientation should collapse multiple calls without creating a second source of truth or allowing the overview command to mutate evidence.                                                                                                                                                                                                   | A measured hot-path bottleneck requires a cached projection.                                                     |
| D-018 | Support help-first ordering without duplicating command documentation.                           | `qg help COMMAND` is a conventional first guess; resolving it through the real parser prevents a parallel help model from drifting.                                                                                                                                                                                                               | Argparse gains a native equivalent with the same JSON contract.                                                  |
| D-019 | Treat natural multi-word guidance as search intent and keep intent probes bounded.               | Agents commonly omit `--search`; accepting the phrase is unambiguous and safe, while audit probes must finish inside the runner's fixed deadline to measure recovery rather than task duration.                                                                                                                                                   | Search syntax or the intent-runner deadline changes.                                                             |
| D-020 | Make empty human and machine invocations self-describing.                                        | Bare `qg` and `qg --json` have no ambiguous product intent and can safely return help or the capabilities contract without repository access or side effects.                                                                                                                                                                                     | The CLI gains a different explicit discovery entry point.                                                        |
| D-021 | Keep embedded guidance independent of repository discovery.                                      | Read-only playbooks ship inside the binary; requiring an initialized project prevented the cold agents who need them most from reading them.                                                                                                                                                                                                      | Guidance gains project-specific extensions.                                                                      |
| D-022 | Dogfood every public control surface in a disposable project.                                    | Unit tests cannot prove the real setup executable, curses terminal, loopback HTTP server, token boundary, review artifacts, and CLI process contracts compose end to end.                                                                                                                                                                         | A new public control surface or security boundary is added.                                                      |
| D-023 | Prioritize inherited-debt tests around governance boundaries.                                    | Hooks, TUI, and dashboard authentication were among the least-covered modules and can silently weaken or misreport the gauntlet if their failure paths are untested.                                                                                                                                                                              | These modules meet strict branch coverage and a lower-risk hotspot dominates.                                    |
| D-024 | Publish deterministic local provenance and keyless hosting attestations as distinct evidence.    | A reproducibility statement remains reviewable offline, while GitHub OIDC and Sigstore authenticate CI-built bytes without a long-lived signing key; neither should be misrepresented as a security verdict.                                                                                                                                      | A managed independent builder or organization signing policy is introduced.                                      |
| D-025 | Make protected Python locks explicit about interpreter-selected transitive dependencies.         | libcst selects `pyyaml-ft` only on Python 3.13+, so a lock resolved on another interpreter can pass locally yet fail hash enforcement on a supported runtime; the marker and hashes now live in the reviewed input and lock.                                                                                                                      | Python packaging gains a resolver-native universal lock format used by pip.                                      |
| D-026 | Resolve Yarn and pnpm matrix runs through the fixture's declared Corepack version.               | A preinstalled Yarn 1 binary can exist while `packageManager` requires Yarn 4; command presence alone does not prove compatibility, and silently choosing the global binary makes conformance host-dependent.                                                                                                                                     | Package-manager shims gain an equally deterministic native replacement.                                          |
| D-027 | Require an independent review without enabling code-owner review in the single-owner repository. | The author cannot approve their own pull request, while requiring `@siraht` specifically as code owner would deadlock every owner-authored change. There are no bypass actors; enable code-owner enforcement when policy ownership can be assigned to a second maintainer or team.                                                                | A second independent policy owner is added.                                                                      |
| D-028 | Compare this repository against `origin/main` after publishing its first remote branch.          | Setup correctly used `HEAD` while the recovered folder had no remote, but retaining it after publication made a clean feature branch appear to have zero changed files and invalidated review scope.                                                                                                                                              | The repository's default branch or remote name changes.                                                          |
| D-029 | Treat only executable pytest suites as Python test roots.                                        | Setup-time heuristics classified `quality` and `src` as test roots, causing mutmut's isolated sandbox to select paths it does not copy and excluding the ten committed CLI ergonomics regressions from ordinary CI.                                                                                                                               | The repository adds or moves a pytest suite.                                                                     |
| D-030 | Classify authorization controls as affected by this change.                                      | The productionization branch changes policy evaluation and public-branch enforcement, so marking authorization false contradicted the changed surface even though the deterministic profile already resolved to high assurance.                                                                                                                   | The policy and repository-governance changes are removed from scope.                                             |
| D-031 | Parse each mutation outcome instead of inferring survivors from display text.                    | Mutmut's default results omit killed mutants and list every other status; counting mutant-looking lines mislabeled never-run, timed-out, and skipped work as survivors and could not enforce the configured score.                                                                                                                                | Mutmut publishes a stable machine-readable result schema.                                                        |
| D-032 | Apply Python debt-marker review only to lexical comments.                                        | Identifiers such as `todo=args.todo` and user-facing strings about TODO feature specifications are valid product code, not unresolved implementation comments; token-aware review preserves the intended warning without noisy false positives.                                                                                                   | A language-neutral parsed-comment interface replaces the current scanner.                                        |
| D-033 | Bootstrap Yarn fixture locks, then prove an immutable hardened reinstall.                        | Yarn 4 enables hardened mode for public pull requests and immutable installs on CI; explicit trusted lock generation followed by hardened `--immutable` installation tests both setup and the committed-project security contract.                                                                                                                | Yarn provides a dedicated ephemeral-fixture mode with equivalent guarantees.                                     |
| D-034 | Count controlled mutant timeouts and crashes as kills.                                           | Source mutation deliberately creates nontermination and invalid execution; when the isolated worker enforces its deadline or observes a crash, the test system has detected the fault. Never-run, interrupted, skipped, and suspicious outcomes remain unusable infrastructure.                                                                   | The mutation engine publishes different statuses for harness and mutant faults.                                  |
| D-035 | Pass an explicit boolean value to mutmut's `results --all` option.                               | Mutmut 3.6 exposes `--all BOOLEAN` rather than a normal flag; omitting the value completed mutation execution but made result normalization fail closed after the run. The protected command contract now uses `--all=true`.                                                                                                                      | Mutmut changes `--all` to an `is_flag` option or publishes JSON results.                                         |
| D-036 | Detect application stacks from production files, not AQG launchers or test harnesses.            | The installed `quality/qg.py` launcher and generated browser smoke test made empty, static-web, and JavaScript-only adopters appear to gain Python or JavaScript after setup, creating false stack drift and an immediate onboarding blocker.                                                                                                     | A versioned project-model schema distinguishes implementation and test languages.                                |
| D-037 | Require the risk-selected AQG profile as its own protected GitHub context.                       | Source tests, conformance, browser checks, and reproducible builds can all pass while the committed High-assurance `deep` profile fails. Branch protection must enforce the policy result rather than infer it from adjacent green checks.                                                                                                        | CI can consume equally trustworthy immutable profile evidence from a separate builder.                           |
| D-038 | Scan untracked content while exempting only statically proven loopback network calls.            | New files were fingerprinted but absent from the textual review diff, while controlled dashboard boundary tests produced the same nondeterminism warning as a live external dependency. Synthetic diffs close the blind spot; literal/dataflow loopback recognition removes only the false positive.                                              | Git supplies a stable cross-platform API for textual untracked-file diffs and parsed test dependency boundaries. |
| D-039 | Apply changed-code metrics only to configured, non-excluded source paths.                        | Synthetic untracked diffs made review complete but exposed an implicit coupling: coverage treated generated AQG launchers, runtimes, and checker configuration as application production. Governed source roots preserve untracked application enforcement without measuring the control plane as adopter code.                                   | A future project schema supports separately governed implementation and generated-code roots.                    |
| D-040 | Provision every dependency of every gate in the authoritative hosted profile.                    | The protected deep profile correctly failed as infrastructure when its Lighthouse gate lacked Playwright Chromium, even though a separate browser conformance job was green. Installing browsers in the policy job makes the required context self-contained instead of borrowing confidence from adjacent CI.                                    | Hosted runners expose a preinstalled, integrity-verifiable browser that AQG can safely adopt.                    |
| D-041 | Fail closed when the configured Git comparison base is unavailable.                              | A shallow pull-request checkout lacked `origin/main`, so fallback to `HEAD~1` made review report zero changed files and mutation return vacuous evidence. CI now resolves the real event base, and runtime diff discovery rejects missing refs while preserving untracked-file support in unborn repositories.                                    | Git provides a first-class event-aware changed-file API with equivalent local reproducibility.                   |
| D-042 | Keep the comparison-base override inside the AQG control process.                                | The outer adapter needs the event base, but passing `AQG_DIFF_BASE` into project tests and mutation sandboxes overrode their own repository models and caused valid disposable-repository tests to fail. Child collection, test, coverage, contract, acceptance, and mutation processes now clear the override.                                   | A typed execution-context API replaces environment-variable propagation.                                         |
| D-043 | Bound each mutant from measured baseline time with protected anti-gaming limits.                 | The complete local campaign finished in 6,574 seconds, but the same source exceeded the 7,200-second gate ceiling on a slower hosted runner. Mutmut's default 15x allowance lets pathological mutants dominate the queue; generated sandboxes now use a protected 5x-plus-1s budget, constrained to 3–10x and 0.5–5s.                             | Mutmut publishes deterministic per-mutant budgets and machine-readable progress suitable for checkpointing.      |
| D-044 | Make release-verification harnesses fail fast and run from the governed project directory.       | A final successful shell command can mask an earlier failed assertion, and the vendored launcher intentionally resolves the governed root from the current directory. Final portable verification therefore uses `set -eu`, explicit assertions, and the disposable project as its working directory.                                             | Release verification is a typed first-class AQG command rather than shell orchestration.                         |
| D-045 | Refuse oversized Python mutation scope before creating a sandbox or invoking mutmut.             | File-level “changed” mutation on this productionization branch selected 4,021 production lines and over ten thousand mutants. Per-mutant deadlines do not make an aggregate campaign portable. A protected 250-line preflight makes the required split explicit and returns durable exit-2 evidence instead of timing out.                        | A mutation engine provides trustworthy incremental selection or resumable, content-addressed campaign shards.    |
| D-046 | Reserve distinct inner mutation, result-export, orchestration, and outer safety budgets.         | Giving an inner command the same deadline as its outer gate creates a race that can discard the adapter report. The 7,200-second gate now allocates 6,300 seconds to mutmut, 300 to results, 300 to orchestration, and 300 to safety, while incomplete work remains exit 3.                                                                       | The runner supports typed nested deadlines with guaranteed evidence-flush time.                                  |
| D-047 | Delegate only isolated implementation slices; retain policy and release authority centrally.     | Grok 4.5 efficiently diagnosed and implemented mutation bounding in an explicit Git worktree, but its first CLI-managed worktree attempt did not create an observable isolation boundary. Codex independently tested and cherry-picked the commits; GitHub mutations, attestations, and final certification remain authoritative-controller work. | The delegated runtime can prove an equivalent durable sandbox and signed evidence boundary.                      |

## Progress

| Phase                          | Status   | Evidence                                                                                                                                                                                                                                                                                                               |
| ------------------------------ | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Baseline and risk contract     | Complete | Goal created; baseline status and public remote verified; productionization branch created.                                                                                                                                                                                                                            |
| CI and dependencies            | Complete | Node 24 actions pinned; workflow-pin tests pass; npm audit is clean; checker conformance passes 18/18.                                                                                                                                                                                                                 |
| Cross-stack conformance        | Complete | Six default live projects, Bun, and Playwright/axe pass; all cross-platform contracts and live/browser jobs pass in [run 30148035852](https://github.com/siraht/AgentGauntlet/actions/runs/30148035852).                                                                                                               |
| Coverage and complexity debt   | Active   | 104 tests plus 78 subtests pass; whole-tree coverage is 56.97% / 44.15% with 51 complexity blockers; the latest complete local mutation campaign scored 54.70% with zero incomplete mutants; exact-current deep run `20260727-041042-593d89a5` refused its 4,021-line mutation scope in 178 ms with structured exit 2. |
| End-to-end dogfood             | Complete | Disposable setup, CLI, review, conformance, PTY TUI, and read-only/authenticated dashboard harness passes locally and runs on Python 3.13 CI.                                                                                                                                                                          |
| Release and provenance         | Active   | Final artifacts reproduce byte-for-byte and verify; extracted install/doctor/archive hygiene pass; public-main rollback and candidate restoration match exact vendored bytes; keyless CI attestation remains.                                                                                                          |
| GitHub governance              | Complete | Active ruleset `19719465` has no bypass actors and requires review plus all 13 GitHub Actions contexts, including fail-closed `policy-evidence`; merge, Dependabot, secret-scanning, push-protection, and alert controls are configured.                                                                               |
| Final independent verification | Active   | Read-only verification found false post-setup stack drift and a missing authoritative policy context. Both product/governance defects are remediated; the exact revised candidate requires a final verifier pass.                                                                                                      |

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
- Cataloging every nested flag lets a missing-command error suggest a complete valid
  invocation instead of merely reporting that `COMMAND` is absent. Natural multi-word
  documentation queries can also be recovered safely because they are read-only.
- Cold-start recovery should act only when intent is exact: an empty invocation can show
  help and `--json` alone can return capabilities, while ambiguous or mutating guesses
  must continue to stop with a correction.
- Embedded guidance must remain available before setup. A read-only documentation
  command that unnecessarily discovers project state defeats its own cold-start role.
- A useful dashboard test must cross the actual HTTP boundary. Direct server-object
  tests do not prove response headers, token rejection, action routing, or process
  startup and shutdown behavior; the same applies to curses without a real PTY.
- Coverage remediation is most valuable when it changes confidence at a control
  boundary. Eight focused tests raised hooks from 11% to 89%, TUI from 10% to 56%,
  dashboard from 24% to 48%, and whole-library coverage from 49% to 53%.
- A standards-valid document may still fail at a consumer boundary. GitHub's current
  attestation action detects CycloneDX by requiring a serial number, so AQG now emits a
  content-derived RFC 4122 UUID that preserves reproducibility and signer compatibility.
- Local provenance and authenticated provenance answer different questions. The local
  statement makes the build inputs inspectable; the hosting attestation authenticates the
  builder identity and binds its output digests using a short-lived certificate.
- Cross-version CLI tests should assert semantic layout, not an argparse column boundary.
  Python 3.11 wrapped a long command description that 3.13 kept inline; normalized
  whitespace preserves the actual help contract without pinning terminal formatting.
- Hash enforcement correctly fails when an environment-selected transitive dependency is
  absent. Validate protected locks on both the oldest and newest supported interpreters,
  even when the top-level requirements are identical.
- A binary on `PATH` is not evidence that it satisfies a project's declared tool contract.
  Package-manager conformance must select the version named by `packageManager`, including
  when the CI image already exposes an incompatible global Yarn.
- A cold CI cache must be part of the package-manager proof. Hydrate the declared manager
  explicitly with Corepack before invoking its shim, and preserve both stdout and stderr
  on failure; a warm local cache can otherwise hide the download path entirely.
- A setup-time `HEAD` comparison is valid only before a durable mainline exists. Reconcile
  the protected base ref immediately after first publication or the review engine will
  faithfully analyze an empty three-dot diff.
- Test-root detection is a proposal, not permanent truth. Confirm the collected suites
  after setup: broad source/config directories can look test-like, then fail only inside
  a mutation tool's narrower sandbox while real regression directories remain unexecuted.
- Mutation summaries are not a result schema. Normalize explicit per-mutant statuses so
  killed, survived, uncovered, interrupted, and unusable work retain different meanings.
- Diff heuristics should be conservative about severity and precise about syntax. Token
  boundaries prevent ordinary option names and explanatory strings from masquerading as
  unresolved production comments.
- Public-pull-request hardening is a distinct execution environment. Disposable package
  fixtures must explicitly disable both hardened and CI-default immutable behavior only
  while generating their exact lock, then rerun the same install immutably instead of
  disabling the hardened contract wholesale.
- A mutant timeout is not the same as a checker timeout. Preserve the boundary: an
  isolated mutant that exceeds its enforced deadline is detected, while an incomplete
  overall run remains unusable evidence.
- Exercise result-export commands as well as mutation execution during checker
  conformance. A value-taking Click option can look like a normal flag in code review and
  fail only after an otherwise successful long run.
- Rehearse release recovery against exact bytes, not only version strings. Installing the
  public-main runtime and comparing its vendored source before restoring and comparing the
  candidate proves both rollback and forward recovery even when both builds share a
  semantic version.
- Generated tooling is not application code. Run stack detection again after installation
  and verify that launchers, vendored runtimes, and generated test harnesses cannot change
  the protected project model or manufacture an onboarding blocker.
- Required contexts must include the policy decision itself. A collection of green unit,
  matrix, browser, and build jobs is useful evidence, but it is not equivalent to the
  risk-selected profile when that profile has stricter gates and human controls.
- A file-name inventory is not a content review. Include deterministic synthetic diffs for
  untracked files, then keep approval exclusions at the fingerprint layer so writing an
  approval record does not invalidate itself.
- Network-test heuristics should recognize only statically provable loopback bindings.
  Suppressing all HTTP in a server-test module would hide accidental external calls; literal
  host and request-variable propagation keeps the exception narrow and testable.
- Review scope and metric scope are related but not identical. Review must see every
  untracked file, while changed-code coverage and structure must enforce only configured,
  non-excluded application roots; sharing an unfiltered diff silently conflates the two.
- A required profile job must provision its own complete execution surface. A green
  browser fixture in another job cannot turn a missing browser in the authoritative
  Lighthouse gate into usable evidence.
- A missing comparison ref is not an empty diff. Changed-code gates must reject it as a
  configuration error, and hosted workflows must resolve the event's real base before
  hashing, reviewing, measuring coverage, or selecting mutation scope.
- Control-plane context must stop at the application-process boundary. A comparison ref
  selected for the outer AQG run must not override the repository model of tests,
  acceptance handlers, or mutation sandboxes launched by an adapter.
- Aggregate mutation timeouts must be portable to the slowest authoritative runner.
  Baseline-relative per-mutant budgets keep generated nontermination from exhausting the
  whole campaign, while protected lower bounds prevent timeout settings from inflating
  the mutation score.
- Verification harness control flow is part of the evidence. Fail on the first assertion,
  set the governed working directory explicitly, and never let a trailing informational
  command replace an earlier nonzero status.
- A per-mutant timeout does not bound aggregate campaign wall-clock time. Measure the
  actual production-line scope before creating a sandbox, require large changes to split,
  and never score mutants that were not executed.
- Nested timeout budgets need explicit slack. Reserving result-export, orchestration, and
  safety windows prevents the outer gate from racing the adapter's fail-closed report.
- Delegated-agent isolation must be verified from the filesystem, not inferred from a CLI
  flag. An explicit Git worktree provided the reviewable boundary that the first delegated
  launch failed to materialize.

## Evidence conventions

- Record commands and immutable GitHub run or release URLs, not screenshots.
- Record a failed, skipped, stale, or inapplicable control as such; never summarize it as
  green.
- Human approvals must be completed by an actual human after final fingerprints exist.
- Temporary fixture repositories and runtime evidence live under ignored paths.
