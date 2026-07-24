# Research synthesis for constrained agentic coding

This report records the design conclusions embodied in AQG v2. Detailed source-by-source analysis is in `SOURCE_SYNTHESIS.md`; embedded, technique-specific instructions are under `src/aqg/guides/`.

## Central conclusion

Agentic coding quality improves when the agent’s search space is bounded by several independent oracles and when the agent cannot freely change those oracles. Tests alone are insufficient because the same agent can write weak tests, disable discovery, update snapshots, or lower thresholds. The control system therefore needs intent, policy, implementation, evidence, and governance boundaries.

## Controls retained from the supplied materials

Robert C. Martin’s constraint strategy contributes layered tests, structural limits, coverage, mutation, QA, and selective human review of behavior rather than every implementation line.

The CRAP tools contribute the combined signal:

```text
CRAP = cyclomatic_complexity² × (1 - coverage)³ + cyclomatic_complexity
```

This catches code that is simultaneously branch-heavy and weakly exercised. AQG combines it with function length, nesting, changed coverage, mutation, and architecture checks so agents cannot game one metric by creating wrapper chains.

`clj-mutate` contributes isolated mutants, passing baselines, survivor evidence, and differential execution. AQG separates survivor, no-coverage, timeout, crash, and configuration outcomes.

`speclj-structure-check` demonstrates that a successful test command does not prove tests were discovered. AQG explicitly scans focus/skip markers and invokes framework collection.

The portable acceptance-pipeline work contributes strict Gherkin, canonical examples, thin handlers, and acceptance mutation. AQG rejects unsupported syntax and disconnected example fields.

Golden-testing guidance contributes structured broad traces, explicit normalization, separate compare/update operations, and raw human-reviewed diffs.

FitNesse contributes collaborative executable examples but also illustrates why readable tables still need thin fixtures attached to real public boundaries.

Keystone feature specifications contribute active versus TODO behavior, dot-namespaced inheritance, and durable observable requirements.

## Additional standards and tool basis

AQG’s embedded research basis references:

- NIST Secure Software Development Framework;
- OWASP Application Security Verification Standard;
- SLSA source/build provenance concepts;
- WCAG 2.2 and ACT rule structure;
- official Playwright, Vitest, Stryker, mutmut, pytest, Hypothesis, mypy, TypeScript, ESLint, and Stylelint guidance.

Standards provide control vocabularies, not automatic proof. Projects still need domain rules, incident history, regulatory obligations, and operational recovery.

## Best-practice synthesis

### Test design

Agents receive selection guidance rather than a generic instruction to “write tests.” Tests should cover equivalence partitions, boundaries, state transitions, invariants, retries, idempotency, authorization, recovery, and external contracts. Expected values should come from independent rules or examples rather than duplicating the implementation algorithm.

### Test integrity

Collection errors, unexpected zero tests, new skips, focus markers, duplicate structures, and fresh-report failures are first-class defects. Coverage scopes mutation; it does not demonstrate assertion sensitivity.

### Structural quality

Function size and complexity limits improve both maintainability and agent throughput. Legacy repositories use changed-code ratchets. Metrics are protected policy, not a per-feature negotiation.

### Mutation

Changed-code mutation is useful in pull requests; broader mutation belongs in High-assurance, release, or scheduled runs. Critical survivors require explanation even when the aggregate score passes.

### Acceptance and QA

Gherkin and manual procedures describe observable behavior. Scenarios cover success, invalid input, boundaries, permission denial, retry, failure recovery, and forbidden side effects. A blocked manual case is not a pass.

### Browser and accessibility

Use accessible locators, deterministic test data, isolated contexts, retained failure artifacts, and explicit retry classification. Automated accessibility checks catch only machine-decidable rules; manual keyboard, focus, name/role/value, contrast/context, and assistive-technology review remains necessary by risk.

### Security and supply chain

Secrets, static security patterns, dependency vulnerability audits, exact tool locks, deterministic SBOMs, reproducible builds, minimal CI permissions, and protected workflows serve different purposes. Inventory is not vulnerability detection, and a clean vulnerability audit is not proof of safe application behavior.

### Review automation

Automated review should route human attention to behavioral contracts, policy changes, test weakening, goldens, schemas, migrations, auth, dependencies, survivors, waivers, approvals, rollback, and release evidence. It should not pretend to make subjective product or safety decisions.

## Anti-gaming rules

- Builder agents cannot lower thresholds or rewrite protected commands during feature work.
- Normal execution cannot update goldens.
- Missing reports and crashed workers fail closed.
- Mutation caches are evidence only when behavior-relevant hashes match.
- New untracked files are included in changed-code scope.
- Human approvals become stale after relevant changes.
- High-assurance verification is read-only and independent.
- Critical work retains human code review and separate release approval.

## Operational recommendation

Adopt AQG centrally with thin project installations. Start in ratchet mode for existing repositories, prove every checker with known-good and known-bad fixtures, keep clean CI authoritative, and gather evidence over 20–30 representative Standard changes plus a release cycle before reducing implementation review. Use canaries, telemetry, kill switches, and rehearsed rollback to limit failures that no pre-release test model predicted.

## Supplied primary sources

- https://github.com/unclebob/crap4clj
- https://github.com/unclebob/crap4java
- https://github.com/unclebob/clj-mutate-
- https://github.com/unclebob/speclj-structure-check
- https://github.com/unclebob/Acceptance-Pipeline-Specification
- https://github.com/jlevy/tbd/blob/main/packages/tbd/docs/guidelines/golden-testing-guidelines.md
- https://fitnesse.org/FitNesse/UserGuide/OneMinuteDescription.html
- https://github.com/MichaelWDanko/keystone-feature-spec
