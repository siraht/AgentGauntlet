# Constraint-Driven Agent Quality System

## The design in one sentence

Move human judgment out of line-by-line implementation review and into durable product contracts, risk classification, QA procedures, policy-as-code, and review of behavioral evidence; then make a clean, deterministic CI environment—not the coding agent—decide whether a change is acceptable.

The central caveat is that the full test stack should not run at maximum depth on every change. A two-line documentation fix, a routine feature, an authentication change, and a destructive database migration have different failure costs, so this framework selects gates from an explicit risk profile and reserves the deepest mutation, security, performance, and manual procedures for changes that justify them.

---

## 1. What the approach actually changes

A traditional workflow asks a person to infer correctness by reading implementation details. The constraint-first workflow asks a person to define and review **observable behavior**, while deterministic tools constrain the implementation space and produce evidence.

The division of labor is:

| Artifact                                        | Primary author               | Required reviewer                                                    |
| ----------------------------------------------- | ---------------------------- | -------------------------------------------------------------------- |
| Product context and active feature requirements | Human with agent assistance  | Human                                                                |
| Future/TODO feature requirements                | Human with agent assistance  | Human before implementation                                          |
| Gherkin acceptance examples                     | Agent drafts                 | Human review scaled by risk                                          |
| Manual QA procedures                            | Agent drafts                 | Human review scaled by risk                                          |
| Implementation code                             | Agent                        | Automated gauntlet; human code review only where profile requires it |
| Unit/property/contract tests                    | Agent                        | Mutation, coverage, test-integrity gates                             |
| Golden output                                   | Test runner proposes         | Human approves behavioral diffs                                      |
| Gate definitions, hook scripts, CI policy       | Policy-maintenance task only | Human/code owner                                                     |
| Quality reports                                 | Deterministic tools          | CI and verifier agent; human sees summary                            |
| Final exploratory test                          | Human                        | Human                                                                |

This does not remove judgment. It moves judgment to the artifacts with the highest leverage: what the product must do, what failure would cost, which exceptions are allowed, and whether observed behavior changed intentionally.

---

## 2. Five planes of control

### Intent plane

`KEYSTONE.md`, `feature-spec/`, `features/`, and `qa/procedures/` describe product behavior in language a non-programmer can review. Active feature specifications describe behavior that exists and must remain true. `TODO.*.md` files describe intended behavior that has not shipped and do not constrain the current product.

Requirements use observable statements such as:

> An unavailable worker MUST NOT receive a new assignment.

They avoid implementation statements such as:

> `WorkerService.assign()` must call `availabilityRepo`.

The first is durable across refactors and can be tested through public behavior. The second couples the contract to an internal design that may change safely.

### Policy plane

`QUALITY.md`, `quality/policy.toml`, `quality/qg.py`, gate adapters, native quality-tool configuration, baselines, waivers, hook scripts, CI workflows, agent instructions, verifier definitions, and conformance fixtures define how quality is measured. Normal builder agents cannot edit this plane. A separate, explicitly authorized **policy-maintenance task** is required because an agent that can lower a threshold, redefine a package-script alias, change test discovery, or replace a checker command is not constrained.

### Implementation plane

Source code, unit tests, property tests, contract tests, adapters, and step handlers live here. Builder agents may iterate freely, but the policy plane determines what counts as passing.

### Evidence plane

Every gate emits a stable result: command, tool version, scope, input hash where available, duration, status, findings, logs, and artifacts. Evidence distinguishes:

- `pass`: the quality claim was checked and satisfied;
- `fail`: the check ran correctly and found a defect;
- `configuration_error`: the gate was not configured correctly;
- `infrastructure_error`: the check could not establish a result;
- `skip`: allowed only when the policy explicitly permits it and records why.

A missing report, stale coverage file, crashed mutation worker, or absent test runner must never be interpreted as a pass.

### Governance plane

Branch protection, CODEOWNERS, protected environments, and human approvals prevent the same agent from changing the policy and certifying the change. Local hooks improve feedback, but CI from a clean checkout is the authoritative decision point.

---

## 3. Risk profiles

Classify every change before implementation. The classifier considers blast radius, reversibility, data loss, authentication and authorization, privacy, money, external contracts, migrations, concurrency, safety, and operational recovery.

### Experiment

Use for disposable prototypes and low-value internal spikes with no real user data.

Required evidence:

- clean build or interpreter load;
- formatter/linter;
- unit tests;
- test-discovery integrity;
- no regression in complexity or CRAP;
- no secrets committed.

Do not use this profile for production behavior merely because the change looks small.

### Standard

Use for routine production features and bug fixes that are reversible and do not touch critical boundaries.

Add:

- static typing or equivalent semantic analysis where available;
- changed-code line and branch coverage;
- dependency-boundary and duplication checks;
- targeted contract/integration tests;
- targeted acceptance scenarios or goldens when behavior crosses components;
- differential source mutation on changed logic;
- dependency and vulnerability checks;
- human review of changed behavioral specifications.

### High assurance

Use for authentication, authorization, privacy, billing, externally consumed APIs, concurrency, important persistence, irreversible user-visible actions, and migrations that can be rehearsed and rolled back.

Add:

- full applicable acceptance suite;
- acceptance-example mutation;
- source mutation across all changed modules;
- explicit threat model and abuse cases;
- migration rehearsal and rollback test;
- performance/resource budgets;
- deterministic golden sessions where broad execution matters;
- independent read-only verifier agent;
- manual QA procedure executed before release.

### Critical

Use where defects could cause severe financial, legal, medical, safety, security, or unrecoverable data consequences.

Add:

- independent human code review;
- independent test/specification review;
- full relevant mutation suite after equivalent-mutant triage;
- adversarial security review;
- production-like release rehearsal;
- canary or staged rollout, telemetry, kill switch, and proven rollback;
- separation of builder, verifier, and release approver.

“No human reads the code” is never a goal by itself. It is an earned operating mode for scopes where the evidence system has demonstrated reliability, and it should not override the Critical profile.

---

## 4. Change-risk card

Before coding, the agent creates a plain-language risk card conforming to `quality/schemas/change-risk.schema.json`. It answers:

- What behavior changes?
- What behavior must remain unchanged?
- What data can be created, read, changed, or deleted?
- Does the change touch identity, permissions, secrets, money, privacy, migrations, concurrency, external APIs, or irreversible actions?
- How will failure be detected?
- How will the change be rolled back?
- Which risk profile applies, and why?
- Which behavioral artifacts require human review?

The card is not bureaucracy. It is the switch that determines which gates run and what the user must inspect.

The selected profile is bounded by deterministic escalation. Production scope requires at least Standard; an unavailable or untested rollback, broad blast radius, authentication, authorization, privacy, money, migrations, concurrency, data-loss exposure, external contracts, or irreversible actions require at least High assurance; safety-sensitive work requires Critical. A human may always select a stricter profile, but the orchestrator rejects a weaker one. This prevents the builder from labeling risky work “Experiment” to reduce its own checks.

---

## 5. The quality gauntlet, in execution order

### Gate 0: clean and reproducible baseline

Before modifying code, the agent proves the existing project can build and run its tests from a clean checkout. The baseline records tool versions and existing failures. Legacy debt is not silently attributed to the new change, but the branch cannot add new violations.

Coverage, mutation, and generated artifacts are deleted or written into a unique run directory before each measurement. Reusing stale evidence can produce confident but false results.

### Gate 1: format, lint, compile, and type analysis

These are fast structural checks and should run after each coherent edit. They catch syntax errors, inconsistent formatting, invalid imports, type mismatches, and obvious misuse before expensive tests run.

Warnings that represent correctness risk should be promoted to errors. Purely stylistic rules belong here rather than in agent prompts or human review comments.

### Gate 2: test-integrity and discovery

A passing test command is meaningless when tests were not discovered, were silently ignored, or were disabled. The integrity gate checks:

- the runner found at least the expected minimum number of tests;
- changed test files are syntactically and structurally valid;
- no focused-only markers such as `.only` remain;
- new skips, ignores, disabled annotations, or quarantine entries require a waiver;
- test count does not unexpectedly fall;
- malformed nesting cannot cause the framework to ignore tests;
- duplicate test names or shadowed fixtures are reported;
- the test runner treats collection errors as failures.

This generalizes the lesson from `speclj-structure-check`: validate the structure of the tests before trusting the test runner’s green result.

### Gate 3: unit and property tests

Unit tests provide fast feedback at narrow boundaries. Property-based and metamorphic tests cover classes of inputs and relationships that example-based tests can miss.

Good properties include:

- serialization followed by deserialization preserves the value;
- sorting twice produces the same result as sorting once;
- adding and then removing the same item restores the original state;
- equivalent input representations produce equivalent outcomes;
- authorization never grants more privilege after removing a role.

The agent writes these tests, but mutation testing evaluates whether the assertions can detect meaningful faults.

### Gate 4: function size, complexity, architecture, and CRAP

Constrain new and changed code so the agent cannot accumulate tangles that make subsequent work harder.

Measure at least:

- physical or logical function length;
- cyclomatic complexity;
- cognitive complexity where supported;
- **CRAP**: complexity combined with test coverage;
- duplication;
- dependency cycles;
- forbidden layer crossings;
- public API growth;
- module fan-out or coupling hot spots.

The CRAP formula used by the referenced tools is:

```text
CRAP = complexity² × (1 - coverage)³ + complexity
```

A complex method can be acceptable when its behavior is thoroughly exercised, and a simple uncovered method is less risky than a complex uncovered method. CRAP captures that interaction better than either complexity or coverage alone.

Recommended starting targets, to be calibrated by language and repository:

| Profile        |  Changed-function length |   Cyclomatic complexity | Changed-method CRAP |
| -------------- | -----------------------: | ----------------------: | ------------------: |
| Experiment     | target ≤ 50, hard cap 75 |             hard cap 15 |   no new score ≥ 30 |
| Standard       | target ≤ 40, hard cap 50 | target ≤ 8, hard cap 10 |         target ≤ 15 |
| High assurance | target ≤ 30, hard cap 40 |  target ≤ 5, hard cap 8 |                 ≤ 8 |
| Critical       | target ≤ 25, hard cap 30 |  target ≤ 4, hard cap 5 |                 ≤ 5 |

These are starter values, not universal laws. Different analyzers count branches differently, generated code may need exclusions, and legacy projects should use a **ratchet**:

1. New and substantially changed code meets the target.
2. Existing project-level metrics cannot regress.
3. No new hard-cap violation is introduced.
4. Waivers are narrow, have an owner and expiry, and cannot be generated as a routine workaround.
5. Thresholds tighten only after evidence shows the project can sustain them.

Small functions alone do not guarantee good design. An agent can game the metric by creating many wrappers, so architecture, duplication, coupling, and mutation gates remain necessary.

### Gate 5: coverage with freshness and provenance

Measure line/statement and branch coverage for changed code, and track whole-project coverage as a non-regression baseline.

Suggested changed-code starting floors:

| Profile        | Line/statement | Branch |
| -------------- | -------------: | -----: |
| Standard       |            85% |    75% |
| High assurance |            90% |    85% |
| Critical       |            95% |    90% |

Coverage proves execution, not correctness. It is useful because low coverage makes complex code risky and because it scopes mutation work, but it cannot replace assertions, acceptance tests, or mutation testing.

Every report must identify the exact source revision, test command, tool version, and timestamp or input hash. Missing or ambiguous method mapping is `N/A` or an error, never fabricated precision.

### Gate 6: contract and integration tests

Use contract tests at boundaries where one component makes assumptions about another:

- HTTP requests and responses;
- events and queues;
- database schemas;
- command-line interfaces;
- configuration formats;
- file formats;
- third-party adapters.

Validate both producer and consumer expectations. Public schemas should be versioned and diffed so an agent cannot make an accidental breaking change that unit tests inside one repository miss.

### Gate 7: executable acceptance specifications

Use a deliberately small, human-readable Gherkin subset for important end-to-end behavior:

```gherkin
Feature: Password reset

Scenario Outline: A reset link has a bounded lifetime
  Given a reset link issued <age_minutes> minutes ago
  When the user submits the link
  Then the result is <result>

Examples:
  | age_minutes | result  |
  | 5           | allowed |
  | 90          | denied  |
```

The portable pipeline is:

```text
.feature text
  -> deterministic parser
  -> canonical JSON intermediate representation
  -> advisory duplicate/near-duplicate checker
  -> deterministic entrypoint generator
  -> thin generated tests
  -> project runtime and narrow step handlers
  -> real application boundary
  -> project test runner
```

Design rules:

- Parse only the syntax the project supports and reject malformed or unknown non-comment lines with line numbers. A compatibility mode may capture explicitly allowed prose descriptions, but required CI must not silently ignore unsupported tags, rules, DocStrings, tables, or localized keywords that a human could mistake for executable behavior.
- Preserve deterministic ordering and canonical JSON so diffs are stable.
- Generate thin entrypoints and metadata; never generate business semantics into the tests.
- Keep step handlers narrow. Multiple matching handlers are an error rather than an arbitrary choice.
- Create a fresh scenario world/state for each execution.
- Run Background steps and scenario steps in source order.
- Connect handlers to public application behavior, not to an imitation that merely confirms the test’s own setup.
- Treat duplicate and near-duplicate wording as advisory; similar text may still represent different semantics.
- Reference the most specific active feature specification from the acceptance test.

The human reviews whether the examples express the desired behavior. The agent handles parser/runtime plumbing.

### Gate 8: golden or snapshot sessions

Use goldens when a compact artifact can capture broad, structured behavior that would be tedious to assert field by field: compiler output, CLI sessions, protocol traces, agent/tool traces, render trees, migration plans, or complex transformations.

A trustworthy golden system:

- serializes a defined event schema rather than dumping arbitrary console output;
- includes broad context but keeps each artifact bounded and reviewable;
- normalizes only fields proven to be unstable, such as timestamps, random IDs, ports, and temporary paths;
- mocks clocks, randomness, and slow or nondeterministic external dependencies where practical;
- keeps a small set of canonical scenarios fast enough for every commit;
- combines broad diffing with targeted invariants for safety-critical facts;
- separates “run and compare” from “update expected output”;
- never auto-approves changed goldens;
- shows raw diffs to the human and requires explicit approval for updates.

Over-normalization can hide regressions, while surgically extracting a few fields defeats the broad-observation purpose. Keep stable fields visible and normalize at the serialization boundary.

### Gate 9: source mutation testing

Conventional mutation testing changes one production-code operation at a time—such as reversing a conditional, changing a boundary, replacing a return value, or deleting a side effect—and reruns the relevant tests.

Classification:

- tests fail: mutant is **killed**;
- tests pass: mutant **survives**, revealing a test gap or equivalent behavior;
- runner crashes, times out, or cannot execute: **infrastructure error**, not a survivor and not a pass.

Workflow:

1. Prove the unmodified baseline passes.
2. Discover mutation sites deterministically.
3. Exclude generated code and explicitly justified no-mutate regions.
4. Mutate one site at a time in an isolated worker copy.
5. Run the smallest sound test scope.
6. Restore or discard the worker copy.
7. Review survivors; add meaningful tests or document a narrow equivalent mutant.
8. Rerun until the profile’s requirement is met.
9. Store a content-hashed manifest so unchanged, previously clean scopes can be reused safely.
10. Run differential mutation on pull requests and full mutation on a schedule or release boundary.

Mutation is expensive, so persistent workers, coverage-guided selection, unique work directories, and content-hash reuse matter. Reuse is valid only when the source, tests, runtime, configuration, and relevant generated entrypoints match the manifest.

Suggested starting mutation expectations:

| Profile        | Pull request                                                                   | Scheduled/release          |
| -------------- | ------------------------------------------------------------------------------ | -------------------------- |
| Standard       | changed logic, target ≥ 70% killed after triage                                | broader suite periodically |
| High assurance | all changed modules, target ≥ 85%                                              | full applicable modules    |
| Critical       | all affected critical paths, target ≥ 90% and no unexplained critical survivor | full relevant suite        |

Mutation score alone is not the goal. One surviving authorization or data-loss mutant matters more than many trivial killed mutants.

### Gate 10: acceptance-example mutation

Acceptance mutation is separate from source mutation. It changes one value in the Gherkin Examples-derived JSON IR while reusing the same generated entrypoint.

```text
base JSON IR
  -> mutate exactly one example cell
  -> persistent project runner evaluates mutated IR
  -> acceptance test fails: killed
  -> acceptance test passes: survived
  -> runner unavailable/crashed: infrastructure error
```

This answers a specific question: are the example values actually connected to the application and assertions, or are they decorative text?

Requirements:

- mutate exactly one example cell per job;
- never mutate source step text or production code in this mode;
- use deterministic mutation IDs and value transformations;
- separate **domain-valid semantic mutants** from invalid-input robustness mutants; a typo that dies during parsing or enum conversion does not prove the application or final assertion used the value;
- report the kill stage—parse, conversion, setup, application behavior, or assertion—and count only the configured evidence class toward the connection-quality target;
- report original value, mutated value, JSON path, scenario, and status;
- keep runner protocol machine-readable and keep diagnostic logs off its protocol channel;
- reuse manifests only for scenarios with zero survivors and zero errors;
- invalidate required-run reuse when any behavior-relevant input changes: feature IR, generated entrypoints, runtime, step handlers, application artifact or relevant source closure, test configuration, dependency lock, tool version, or material environment configuration;
- store cache manifests in the evidence/cache plane rather than inserting mutation stamps into human-authored feature files.

The referenced portable mutator deliberately uses generic value changes, which is useful as a baseline but can over-credit kills caused by invalid values. High-assurance adapters should generate valid alternatives at domain boundaries—another recognized role, a neighboring limit, a different valid state, or an alternate identifier—so a kill demonstrates behavioral coupling rather than input rejection.

### Gate 11: security and supply chain

Run profile-appropriate checks for:

- committed secrets;
- vulnerable direct and transitive dependencies;
- unsafe language constructs and injection paths;
- license policy;
- container and infrastructure configuration;
- software bill of materials;
- authentication and authorization invariants;
- dependency pinning and lock-file integrity;
- untrusted input reaching shell, SQL, templates, deserializers, file paths, or network destinations.

Security tools produce leads rather than proof. High-assurance changes add a human-readable threat model and abuse-case acceptance tests.

### Gate 12: performance and resource budgets

For performance-sensitive behavior, define budgets for latency, throughput, memory, CPU, database calls, network calls, artifact size, and algorithmic scaling. Compare against a stable baseline under controlled conditions.

A noisy benchmark should report uncertainty or an infrastructure error. It should not fail or pass on an unexamined single sample.

### Gate 13: manual QA and release controls

Manual QA is a backstop for user experience, environment interaction, and failures that the model of the system did not anticipate.

A QA procedure contains:

- purpose and risk addressed;
- exact preconditions and test data;
- numbered actions;
- expected result after each meaningful action;
- negative and recovery cases;
- cleanup;
- evidence to capture;
- rollback procedure.

High-assurance and Critical releases add canarying or staged rollout, telemetry, alert thresholds, a kill switch, and a rehearsed rollback.

---

## 6. Quality tools must pass their own gauntlet

Small deterministic tools are useful only when their outputs are trustworthy. Each custom adapter or checker needs:

- unit tests;
- conformance fixtures with known pass, fail, malformed, and infrastructure-error cases;
- deterministic output ordering;
- explicit exit-code contract;
- version output;
- input and configuration hashing;
- safe cleanup that cannot escape the repository;
- unique work directories for parallel workers;
- stale-artifact detection;
- timeouts;
- machine-readable output;
- clear separation between quality failures and tool failures;
- golden fixtures for parsers and report formats;
- mutation or fault-injection tests for the checker where practical.

Never let a quality tool quietly fall back to old coverage data, share worker paths, swallow parse failures, or report “no findings” when it never completed.

---

## 7. Agent roles and separation of duties

### Builder agent

May edit implementation, unit/property/contract tests, project-specific acceptance handlers, and proposed behavioral artifacts. It must run the configured gates and may not change the policy plane during a normal task.

### Verifier agent

Runs in read-only mode from a clean checkout or separate worktree. It maps the changed behavior to active feature contracts, reruns the required profile, investigates survivors and skipped checks, and reports evidence. It does not repair the code it is judging in the same pass.

### Policy maintainer

Activated only by an explicit request to change gates, thresholds, hooks, CI, waivers, or protected paths. The task must explain why the old policy is wrong, add conformance tests, and obtain human approval.

### Human product/release owner

Reviews the risk card, observable requirements, Gherkin examples, QA procedures, golden diffs, waivers, migration/rollback plan, and final manual behavior where required. The human does not need to understand every implementation detail to make these decisions.

Two agents are not fully independent if they share the same prompt, context, and ability to edit policy. The deterministic CI runner and human-owned contracts provide the real independence.

---

## 8. Per-change workflow

1. **Read durable context.** Load `AGENTS.md`, `QUALITY.md`, `KEYSTONE.md`, the applicable active feature chain, relevant TODO documents, related specifications, architecture boundaries, and existing QA material.
2. **Establish the baseline.** Run `doctor` and the existing fast profile before editing. Record pre-existing failures.
3. **Classify risk.** Produce the change-risk card and select Experiment, Standard, High assurance, or Critical.
4. **Resolve intent.** State the behavior to add/change and the behavior that must remain unchanged. Surface contradictions rather than guessing.
5. **Draft behavioral artifacts.** Create or update the smallest feature specification, Gherkin scenarios, and QA procedure needed. High-assurance work pauses for human approval at this point.
6. **Plan evidence.** Map each requirement to unit, property, contract, acceptance, golden, security, performance, or manual evidence.
7. **Implement in small slices.** Keep functions, modules, and diffs small enough that the fast profile remains quick and failures remain local.
8. **Run the fast profile repeatedly.** Never accumulate many unrelated failing gates.
9. **Run the pull-request profile.** Refresh coverage, enforce changed-code metrics, run contracts/acceptance, and perform differential mutation.
10. **Investigate rather than bypass.** Fix survivors, flakiness, ambiguous handlers, missing discovery, and infrastructure errors. Do not weaken tests or thresholds to make the report green.
11. **Run independent verification.** The read-only verifier works from a clean checkout or worktree and produces an evidence summary.
12. **Human review.** Review changed behavior artifacts, risk/rollback, goldens, waivers, and manual QA according to the profile.
13. **Clean CI decides.** Required checks run with pinned dependencies and no stale artifacts.
14. **Release and observe.** Apply canary, telemetry, alert, rollback, and post-release checks required by the profile.
15. **Reconcile contracts.** When a TODO feature ships, merge it into the active specification and remove the TODO state only after verification.

---

## 9. Test-change policy

Agents must be allowed to improve tests, but changing tests and implementation together creates a conflict of interest. Enforce these rules:

- Deleted tests, reduced assertions, broader mocks, new skips, changed expected errors, lower timeouts, and relaxed golden normalizers are separately reported.
- Any changed production logic with changed tests reruns mutation for the affected scope.
- A test deletion requires evidence that the behavior is obsolete, duplicated, or replaced.
- A skip requires owner, reason, issue, and expiry.
- Golden update commands require explicit human authorization; normal test commands are read-only.
- Acceptance and QA changes are human-review-plane changes.
- Policy, hook, CI, and waiver changes are policy-maintenance changes.
- “The old test failed” is not evidence that the old expectation was wrong.

Layering many tests makes casual weakening harder, but mechanical change auditing and mutation testing are the dependable controls.

---

## 10. CI topology

### Fast profile

Target: feedback in roughly one or two minutes for a typical project.

Run format check, lint, compile/type check, test-integrity, focused unit/property tests, and changed-code structural metrics.

### Pull-request profile

Target: complete before review without blocking iteration for an excessive period.

Add full unit suite, changed coverage, contracts, targeted acceptance/goldens, differential mutation, dependency/security checks, and review-plane diff reporting.

### Deep profile

Run nightly or on demand.

Add broad source mutation, acceptance mutation, randomized test order, flake detection, full integration/E2E, heavier security scans, and performance regression tests.

### Release profile

Run before production deployment.

Add clean reproducible build, SBOM/signing where applicable, migration rehearsal, production-like smoke tests, manual QA sign-off, canary plan, rollback proof, and release evidence bundle.

CI requirements:

- clean checkout;
- pinned or locked dependencies;
- no untrusted cache for evidence that affects pass/fail;
- unique run/work directories;
- artifacts uploaded even on failure;
- infrastructure errors fail required checks;
- policy-plane changes require code-owner approval;
- required checks cannot be skipped by changing the pull request;
- reports are retained long enough to investigate regressions.

For stronger protection across many repositories, host the authoritative workflow and policy verification in a separate central repository and call it as a pinned reusable workflow. A repository-local agent should not control the final enforcement code.

Trace every policy command to the executable and configuration files it actually uses. Calling `npm test`, a Make target, or another alias is safe only when the alias definition and every quality-sensitive configuration file it loads are also policy-protected or require code-owner approval; otherwise the agent can leave `quality/policy.toml` unchanged while silently redefining what “test” means.

---

## 11. Codex integration

Use:

- root `AGENTS.md` for the stable working contract;
- nested `AGENTS.override.md` only for genuine module-specific rules;
- `.agents/skills/quality-gauntlet/SKILL.md` for the reusable workflow;
- `.codex/hooks.json` for deterministic pre-tool and stop hooks;
- `.codex/agents/quality-verifier.toml` for a read-only verifier;
- workspace-write sandbox with on-request approvals for normal local work;
- no network during verification unless a specific gate requires a scoped destination;
- command rules or managed policy for especially dangerous commands;
- CI as the authoritative gate.

Keep instructions concise and point to durable files rather than duplicating the entire policy in `AGENTS.md`.

Use `python3 quality/qg.py risk-card` to validate classification and `python3 quality/qg.py check-risk` to invoke the required cumulative execution profile. The agent should not be trusted to remember which profile applies.

---

## 12. Claude Code integration

Use:

- root `CLAUDE.md` as a thin pointer to `QUALITY.md`, `KEYSTONE.md`, and the skill;
- `.claude/settings.json` for permissions and deterministic hooks;
- `.claude/skills/quality-gauntlet/SKILL.md` for the reusable workflow;
- `.claude/agents/quality-verifier.md` for a read-only verifier;
- `PreToolUse` hooks to block policy-plane writes and destructive commands;
- `Stop` hooks, once fast checks are stable, to prevent a task from ending with a failing fast profile;
- repository permissions or managed settings for restrictions that users must not bypass;
- CI as the authoritative gate.

Prompt instructions are advisory. Hooks and permissions provide deterministic local control, and clean CI provides independent enforcement.

Use the same `risk-card` and `check-risk` commands as Codex. The verifier subagent has no direct edit tools and runs in an isolated worktree because test execution often needs to create caches and evidence even when tracked source is treated as read-only.

---

## 13. Adoption plan

### Phase 0: inventory and baseline

The bootstrap agent identifies languages, build systems, test frameworks, deployment surfaces, data stores, public contracts, existing CI, and current failures. It does not change product behavior.

Deliverables:

- repository map;
- risk-boundary map;
- proposed feature namespaces;
- tool/adaptor choices;
- baseline measurements;
- list of flaky, undiscovered, skipped, or failing tests;
- rollout plan that avoids a giant cleanup.

Exit: existing behavior can be reproduced from a clean environment, or every baseline failure is explicitly documented.

### Phase 1: fast deterministic core

Configure formatting, linting, compile/type checking, test discovery, unit tests, function size, complexity, CRAP, changed coverage, secret scanning, and the `qg` command.

Exit: `doctor` and `check fast` work locally and in clean CI; stale artifacts and tool failures fail closed.

### Phase 2: intent and behavioral contracts

Create `KEYSTONE.md`, active/TODO feature specs, the first high-value Gherkin features, and QA procedures. Start with business-critical behavior, not exhaustive documentation.

Exit: each selected active feature has an observable contract and at least one linked verification path.

### Phase 3: test-quality verification

Add differential source mutation for changed logic, equivalent-mutant triage, test-change auditing, and acceptance-example mutation for example-heavy scenarios.

Exit: mutation results are reproducible, infrastructure errors are separate, and manifests are invalidated by relevant changes.

### Phase 4: broad behavior and operational risk

Add goldens, contract tests, architecture rules, dependency/security gates, migration rehearsal, performance budgets, canarying, and rollback controls where the system needs them.

Exit: the High assurance profile can produce a complete evidence bundle.

### Phase 5: earned reduced code review

Pilot reduced code review only on Standard-profile scopes.

Recommended evidence before expanding:

- at least one representative release cycle and roughly 20–30 successful changes through the gauntlet;
- no unexplained bypasses or silent skips;
- stable test-discovery and coverage provenance;
- low, measured flake rate and no hidden retry dependence;
- mutation survivors consistently triaged;
- manual QA findings fed back into automated contracts;
- policy-plane changes protected and audited;
- rollback exercised;
- post-release defect rate acceptable for the domain.

Keep human code review for Critical scopes and any area where the evidence system has not earned trust.

---

## 14. Common failure modes and controls

| Failure mode                             | Why it happens                              | Control                                                                                |
| ---------------------------------------- | ------------------------------------------- | -------------------------------------------------------------------------------------- |
| Agent changes the tests to match a bug   | Code and tests share an author              | Mutation, test-change audit, human-owned acceptance/QA, verifier agent                 |
| Agent lowers thresholds                  | Policy is inside its writable scope         | Protected policy plane, hooks, CODEOWNERS, central CI                                  |
| Green tests discover nothing             | Framework silently ignores malformed tests  | Test-structure checker, minimum-count and no-new-skip gates                            |
| High coverage with weak assertions       | Coverage measures execution                 | Source mutation, properties, acceptance mutation                                       |
| Stale coverage changes CRAP              | Old artifacts are reused                    | Delete/fingerprint artifacts; fail on ambiguous mapping                                |
| Mutation workers collide                 | Parallel runs share paths or ports          | Unique run roots, isolated workers, deterministic IDs                                  |
| Mutation becomes too slow                | Full suite runs for every mutant            | Coverage-guided scope, persistent workers, differential manifests, scheduled full runs |
| Equivalent mutants waste effort          | Mutation does not alter observable behavior | Narrow suppression with rationale; score after triage                                  |
| Gherkin becomes verbose and inconsistent | Agents invent new phrasing per scenario     | Small grammar, canonical vocabulary, advisory DRY checker                              |
| Step handlers test a fake                | Acceptance plumbing bypasses the real app   | Thin entrypoints, public-boundary handlers, acceptance mutation                        |
| Goldens hide regressions                 | Broad normalizers or blind updates          | Schema, field classification, bounded artifacts, human raw-diff review                 |
| Flaky tests are retried until green      | Retry masks nondeterminism                  | Hermetic clocks/RNG/network, seed logging, flake budget, no silent retry               |
| Tiny functions create wrapper soup       | Agent games size metrics                    | Coupling, duplication, architecture, mutation, module-level review                     |
| Tool crash is reported as test failure   | Status model is too coarse                  | Separate pass/fail/config/infra statuses and exit codes                                |
| Full stack slows every change            | Risk is not classified                      | Experiment/Standard/High/Critical profiles                                             |
| Acceptance spec is subtly wrong          | Human delegates product intent too far      | Human review of observable examples and manual QA                                      |
| Manual QA finds recurring bugs           | Findings stay informal                      | Convert each meaningful finding into a durable automated contract                      |

---

## 15. What a non-programmer reviews

For each change, focus on five questions:

1. **Behavior:** Do the feature requirements and Gherkin examples say what users should actually experience, including errors and edge cases?
2. **Risk:** Does the change-risk card correctly identify data loss, permissions, privacy, money, external contracts, migration, and rollback concerns?
3. **QA:** Could another person follow the procedure and know exactly what success and failure look like?
4. **Behavioral diffs:** Do golden or acceptance-result changes represent an intended product change rather than incidental noise?
5. **Release safety:** Is there a believable way to detect failure and return to the previous state?

The automated report should translate engineering evidence into plain language: which gates ran, which were skipped and why, whether any survivor or waiver remains, and what still requires a human decision.

---

## 16. Minimal vocabulary

- **Unit test:** checks a small unit of behavior quickly.
- **Property test:** checks a rule across many generated inputs.
- **Contract test:** checks assumptions between components.
- **Acceptance test:** checks user/business behavior end to end.
- **Gherkin:** Given/When/Then text used to express acceptance examples.
- **JSON IR:** a canonical machine-readable form produced from the Gherkin text.
- **Coverage:** how much code was executed by tests.
- **Cyclomatic complexity:** the number of independent decision paths in a function.
- **CRAP:** a risk score combining complexity and lack of coverage.
- **Mutation testing:** deliberately changes code or example data to see whether tests notice.
- **Golden test:** compares a structured observed result with an approved expected artifact.
- **Flaky test:** sometimes passes and sometimes fails without a relevant code change.
- **Ratchet:** existing debt may remain temporarily, but no change may make it worse.
- **Waiver:** a narrow, owned, expiring exception—not a permanent bypass.
- **Infrastructure error:** the checker could not establish a result.
- **Canary:** releases to a small controlled population before broad rollout.
- **Rollback:** restores the previous safe version or data state.

---

## 17. Source lineage

This framework synthesizes the mechanisms in:

- Robert C. Martin’s July 2026 X thread and replies supplied with the request.
- `unclebob/crap4clj`
- `unclebob/crap4java`
- `unclebob/clj-mutate`
- `unclebob/speclj-structure-check`
- `unclebob/Acceptance-Pipeline-Specification`
- `jlevy/tbd` golden-testing guidelines
- FitNesse’s executable-acceptance specification model
- `MichaelWDanko/keystone-feature-spec`
- Current Codex and Claude Code project-instruction, hook, skill, permission, and subagent mechanisms.

The repositories are inputs, not drop-in universal dependencies. The framework preserves their useful contracts—determinism, canonical IR, freshness, isolation, mutation, structural validation, durable intent, and human review of behavior—while delegating language-specific measurement to adapters.

The implementation in this starter kit is original glue and policy code. External tools should be invoked through adapters or vendored only after checking their current licenses, provenance, and update policy; the framework does not assume that every referenced repository can be copied or redistributed.
