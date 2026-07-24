# Source-by-source synthesis

This document records what each supplied source contributes, what can go wrong when its idea is copied mechanically, and how the Agent Quality Gauntlet incorporates it.

## Robert C. Martin's constraint strategy

### Useful mechanism

The strategy changes the unit of human trust. The human does not try to infer correctness from every implementation line; the human reviews product-level examples and QA procedures, while the agent's code must satisfy multiple independently implemented constraints. Small deterministic checkers are especially useful because their result does not depend on an agent explaining why its own work is acceptable.

Function size, cyclomatic complexity, coverage, and CRAP are throughput controls as well as maintainability metrics. Agents lose time when they create coupled, branch-heavy code and then repeatedly patch around it. Structural ceilings keep the search space understandable enough for later agent iterations.

The test layers have different trust roles:

- unit tests provide fast local feedback and may be agent-authored;
- executable acceptance examples express behavior a product owner can inspect;
- QA procedures cover workflows and observations that are difficult to encode immediately;
- mutation tests evaluate whether the other tests are sensitive to plausible mistakes;
- periodic manual testing samples the complete experience.

### Mechanical-copy failure

Simply asking one agent to write code, tests, and thresholds leaves one optimizer in control of both the answer and the grading rubric. Running every expensive technique on every change also makes the suite too slow, encouraging bypasses and stale caches.

### Framework adaptation

The gauntlet separates intent, policy, implementation, evidence, and governance. The policy plane is protected from ordinary builder work, and risk profiles determine which constraints run. Reduced code review is an earned operating mode for appropriate Standard work, never a blanket exemption for Critical changes.

## `crap4clj` and `crap4java`

### Useful mechanism

**CRAP** combines cyclomatic complexity with coverage:

```text
CRAP = CC² × (1 - coverage)³ + CC
```

A complex function with weak coverage scores badly, while either simplifying it or testing its branches lowers the risk. Sorting worst first gives an agent a concrete refactoring queue. Both implementations also emphasize regenerating coverage rather than trusting an old report.

### Mechanical-copy failure

A single global score can be gamed by splitting logic into pass-through wrappers, excluding files, or generating superficial coverage. Coverage-to-method mapping may be ambiguous. The Java specification's treatment of missing coverage as `N/A`, combined with treating no numeric scores as a non-violation, can produce a green quality gate when measurement failed.

### Framework adaptation

CRAP is one structural signal, used with function length, cognitive/cyclomatic complexity, duplication, coupling, architecture boundaries, test integrity, and mutation. Missing or ambiguous coverage is a configuration or infrastructure error. Legacy code uses a ratchet: changed code meets current targets and the repository cannot add worse debt.

## `clj-mutate`

### Useful mechanism

Source mutation starts from a passing baseline, changes one supported construct at a time, runs the tests in isolated workers, and classifies mutants as killed or survived. Differential semantic hashes make repeated runs practical by retesting only changed forms. Coverage can restrict mutations to executed code, and a large mutation-site count is itself a module-size warning.

### Mechanical-copy failure

Mutation is expensive and can generate equivalent mutants. Reusing stale coverage misclassifies scope. Shared worker directories make parallel runs flaky. An embedded or externally updated manifest can claim a new baseline without executing mutations. A mutable test-command alias lets a builder redefine what the mutator runs.

### Framework adaptation

Authoritative mutation begins from fresh coverage, uses unique run roots, records tool and input provenance, keeps caches outside source, and invalidates them with a hash of the full behavior-relevant surface. A manifest update without an actual successful run is never evidence. Equivalent-mutant suppression is narrow, reviewed, and reported. Changed-code mutation runs in PRs; broader mutation runs at High assurance, release, or scheduled depth.

## `speclj-structure-check`

### Useful mechanism

The repository demonstrates that test syntax itself needs static validation. A test runner may exit successfully while malformed nesting causes tests to be ignored, so a small parser catches invalid structures before execution.

### Mechanical-copy failure

Checking only one framework's known nesting mistakes misses other forms of silent non-execution: focused-only tests, skips, collection errors, duplicate names, shadowed fixtures, empty discovery, and unexpected test-count drops.

### Framework adaptation

Every ecosystem adapter has a **test-integrity gate**. It validates test structure and discovery, establishes expected counts, rejects accidental focus/skip markers, and treats collection errors or an unexpected zero-test run as failures.

## `Acceptance-Pipeline-Specification`

### Useful mechanism

The pipeline separates a small Gherkin language from project code through a canonical JSON intermediate representation. Generated entry points remain thin and deterministic; a runtime expands scenarios and examples; narrow step handlers connect text to real application behavior. Unsupported steps, missing values, invalid conversions, and failed assertions are explicit failures.

Acceptance mutation changes one example cell in the IR, reuses the same generated entry points, and observes whether the acceptance test fails. Stable mutation identities, deep copies, persistent newline-delimited JSON workers, and separate test/infrastructure outcomes make results reproducible and scalable. Scenario-level hashes allow differential reuse. The advisory DRY checker helps prevent vocabulary drift without automatically rewriting product language.

### Mechanical-copy failure

The specified parser permits unknown free-form lines to be ignored, which can turn a misspelled requirement into no requirement. The documented implementation hash covers generated entry points but excludes handlers, runtime, adapters, and application code, so cached acceptance-mutation results can outlive relevant behavior changes. Generic string dithering may create an invalid value that dies during parsing; that proves input validation, not that the example value reaches the intended business assertion. Embedding mutation stamps in human-authored feature files mixes evidence cache with product intent.

### Framework adaptation

CI uses strict parsing: unsupported non-comment syntax fails. Cache keys cover the parser, IR schema, generator, generated entry points, runtime, handlers, runner adapter, relevant application modules, feature content, and mutator version. Acceptance mutations are divided into valid semantic mutants and invalid-input mutants, and reports record where each mutant died: parse, conversion, application behavior, or assertion. Cache and evidence live outside the feature specification.

## Golden-testing guidelines

### Useful mechanism

Golden sessions capture broad, structured execution rather than a few hand-picked assertions. Event schemas classify every field as stable or unstable, nondeterminism is injected or mocked, and expected artifacts are checked into version control. A normal comparison command and a separately authorized update command prevent silent approval. Raw diffs are combined with targeted invariants for critical semantics.

### Mechanical-copy failure

Snapshots become noise when timestamps, generated IDs, ordering, or network behavior are uncontrolled. Broad regex placeholders hide real changes. Monolithic traces are hard to review. Narrow `grep` or `jq` extractions defeat the ability to catch unanticipated changes. An agent that automatically updates expected output can make any implementation pass.

### Framework adaptation

Goldens are used only where broad traces add signal. Serialization normalizes explicitly classified unstable fields, artifacts are bounded and sharded, CI runs hermetically, and ordinary tests cannot update expected output. A changed golden is a behavioral-specification proposal requiring human review of the raw diff.

## FitNesse

### Useful mechanism

FitNesse's core idea is collaborative executable specification: people can express inputs and expected outputs in readable tables, and fixtures connect those tables to the system. This makes acceptance evidence inspectable without requiring the product owner to understand implementation code.

### Mechanical-copy failure

Readable tables are not automatically good specifications. Fixtures can bypass the real system, examples can omit boundaries and failure cases, and a large wiki can drift away from the product.

### Framework adaptation

Use the table/executable-specification idea where it is the clearest representation, but keep fixtures thin and attached to public boundaries. Product contracts remain versioned beside code, acceptance mutation checks example connectivity, and human review focuses on valid, invalid, boundary, retry, and recovery cases.

## Keystone feature specifications

### Useful mechanism

Keystone keeps durable product intent beside code. Active files describe implemented behavior that must remain true; `TODO.*.md` files describe intended behavior that has not shipped. Dot-separated namespaces and inherited requirements let broad guarantees apply to specific features without duplicating them. Requirements describe observable behavior rather than source structure.

### Mechanical-copy failure

An agent can incorrectly declare aspirational behavior active, over-document internal details, create contradictory parent and child requirements, or treat TODO files as authorization to implement unrequested work.

### Framework adaptation

The bootstrap task proposes namespaces and active/TODO classification for human confirmation before writing. Active specifications are part of the human-review plane, conflicts are explicit, and tests may reference the most specific applicable feature name. Keystone defines intent; the risk card and user request control what work is authorized.

## Codex and Claude Code mechanisms

### Useful mechanism

Both environments support repository instructions, reusable skills, deterministic lifecycle hooks, and specialized verifier agents. These are appropriate for fast feedback, protected-path checks, and a consistent workflow across sessions.

### Mechanical-copy failure

Prompt files remain instructions, not a security boundary. Local hooks can be bypassed by broad shell access, changed configuration, a different client, or an explicitly authorized maintenance session. A verifier that writes to the same worktree can accidentally alter the evidence it is evaluating.

### Framework adaptation

`AGENTS.md` and `CLAUDE.md` are thin entry points into the same repository policy. Pre-tool hooks block obvious policy-plane and destructive writes; Stop hooks can run the fast profile after it becomes stable. High-assurance verification uses a tool-restricted agent in an isolated worktree. Clean CI, branch protection, CODEOWNERS, and centrally pinned workflows remain authoritative.

## Combined conclusion

The reusable idea is not a particular Clojure, Java, Gherkin, or snapshot tool. It is a control architecture:

1. humans define observable intent and risk;
2. agents implement within a protected policy;
3. several independent test or analysis mechanisms constrain different failure modes;
4. every mechanism fails closed and proves its own integrity;
5. evidence is fresh, isolated, reproducible, and independently enforced;
6. expensive controls scale with failure cost;
7. operational detection and rollback limit what testing cannot eliminate.
