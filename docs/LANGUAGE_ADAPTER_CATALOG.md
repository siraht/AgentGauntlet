# Language adapter catalog

AQG v2 ships production adapters for JavaScript, TypeScript, HTML, CSS, and Python. Project-local configuration may select native test/build commands while AQG retains control of discovery, freshness, evidence, and exit semantics.

## JavaScript and TypeScript

| Control             | Default or supported mechanism                                                                               |
| ------------------- | ------------------------------------------------------------------------------------------------------------ |
| Formatting          | Prettier                                                                                                     |
| Lint/security rules | ESLint flat config and `eslint-plugin-security`                                                              |
| Types               | TypeScript strict compiler configuration                                                                     |
| Unit tests          | Vitest default; Jest, Mocha, AVA, Node test runner, or protected custom command                              |
| Coverage            | Vitest V8, Jest/Istanbul, c8, or protected custom fresh report                                               |
| Structure           | function lines, nesting, cyclomatic complexity, CRAP, versioned ABC; candidate source-file line/byte budgets |
| Properties          | fast-check guidance                                                                                          |
| Mutation            | Stryker with changed-file scope and JSON evidence                                                            |
| Dependencies        | native package-manager audit                                                                                 |
| Reproducibility     | repeated protected build and output manifests                                                                |

## HTML and CSS

| Control                     | Mechanism                                                      |
| --------------------------- | -------------------------------------------------------------- |
| HTML validity/accessibility | HTML-Validate                                                  |
| CSS structure               | Stylelint plus candidate physical-line and raw-byte budgets    |
| Browser journeys            | Playwright isolated contexts, retries, trace/screenshots/video |
| Runtime accessibility       | axe-core Playwright integration                                |
| Resource size               | candidate exact raw/gzip per-artifact and aggregate budgets    |
| Performance                 | multi-sample Lighthouse budgets                                |
| Manual experience           | generated primary-journey QA procedure                         |

Source-file validation cannot see all runtime DOM behavior; important UI changes require browser and manual evidence.

## Python

| Control          | Mechanism                                                                          |
| ---------------- | ---------------------------------------------------------------------------------- |
| Format/lint      | Ruff                                                                               |
| Types            | mypy                                                                               |
| Unit tests       | pytest default; tox or protected custom runner                                     |
| Collection       | strict pytest collection                                                           |
| Coverage         | coverage.py/pytest-cov JSON with branch data                                       |
| Structure        | Radon/Xenon, AQG function metrics, CRAP, versioned ABC, and candidate file budgets |
| Properties/state | Hypothesis guidance                                                                |
| Mutation         | mutmut in isolated changed-code copies                                             |
| Static security  | Bandit                                                                             |
| Dependencies     | pip-audit                                                                          |
| Dead code        | Vulture in deep profiles                                                           |

## Candidate structural and file-budget behavior

The current rollout adds the following deterministic measurements to the
structure gate. The metric kernels, protected defaults, scaffold, adapters,
retrospective inventory, and focused integration tests are committed. A green
whole-profile run for the final candidate remains a separate release claim.

| Classification | Warning boundary   | Hard boundary      | Raw-byte warning / hard boundary |
| -------------- | ------------------ | ------------------ | -------------------------------- |
| Production     | 300 physical lines | 500 physical lines | 75 KiB / 100 KiB                 |
| CSS-family     | 300 physical lines | 450 physical lines | 75 KiB / 100 KiB                 |
| Tests          | 600 physical lines | 800 physical lines | 75 KiB / 100 KiB                 |

Physical lines use UTF-8 `splitlines()` semantics; nonblank lines are retained
as evidence but are not the policy value. Warning and hard boundaries are
inclusive in the source-budget kernel: a file at the warning value is a
warning, and a file at the hard value is a hard failure. Results retain the
path, classifications, physical and nonblank lines, bytes, SHA-256, applicable
limits, breaches, and deterministic aggregate inventory totals.

The candidate classifies conventional test paths separately. CSS-family files
include `.css`, `.scss`, `.sass`, and `.less`. Paths containing `generated` or
`gen`, `vendor`/`vendors`, or `third_party`/`third-party`, plus `.min.js` and
`.min.css`, receive an explicit excluded classification: their measurements
remain in evidence but their limits are not enforced. Repository-level governed
paths and existing exclusions are applied before this classification step.
This is intentionally a limitation: automatic path classification is not proof
that a file is genuinely generated or third-party, and anti-renaming/evasion
conformance is still outstanding.

ABC is per function and uses a Euclidean magnitude
`sqrt(assignments² + branches² + conditions²)`. The base/PR candidate limit is
20, deep is 15, and release is 10. Source line/byte boundaries currently remain
the same across profiles. Python and JavaScript definitions are versioned
separately because they count language constructs differently; neither value
should be compared across languages as if it were one universal metric.

- `aqg-python-abc-v1` includes parameter and other bindings as assignments;
  calls and explicit control transfers as branches; and Python decision,
  comparison, and boolean sites as conditions.
- `aqg-javascript-abc-v1` counts initialized declarations, assignments,
  updates, and default patterns; calls, construction, dynamic import, and
  yields; and JavaScript control-flow/logical sites. It supports JS, JSX, TS,
  and TSX through ESLint and `typescript-eslint`.
- Both definitions exclude nested function bodies from the enclosing function
  and preserve the exact `<A,B,C>` vector and definition identifier.

In existing-repository/adopt mode, the candidate enforces changed functions.
For Python complexity, function lines, nesting, ABC, and source-file hard
failures it compares the Git base so inherited over-limit values remain visible
without blocking unless they worsen. Focused temporary-repository contracts
prove inherited, regressed, new, and missing-base cases without leaving fault
files behind.

## Candidate built-resource budgets

The separate `resource_budget` gate is planned for PR, deep, and release
profiles, not the fast editing profile. It measures `.js`, `.mjs`, `.cjs`, and
`.css` files under explicit, non-overlapping roots.

| Budget                   | Raw-byte cap | Deterministic gzip cap |
| ------------------------ | ------------ | ---------------------- |
| One JavaScript artifact  | 1,048,576    | 256,000                |
| All JavaScript artifacts | 1,677,722    | 409,600                |
| One CSS artifact         | 307,200      | 76,800                 |
| All CSS artifacts        | 409,600      | 102,400                |

Headroom warnings start at 80%. The artifact cap itself is allowed but warned;
an observed value greater than the cap is a quality failure. Aggregate budgets
remain enforceable even when a bundle is split into smaller files. Evidence
retains stable paths, kinds, raw and gzip bytes, content SHA-256, modification
time, effective limits, compression parameters/runtime, findings, totals, and
a fingerprint of the complete measurement.

`build` mode runs the protected build command and requires every measured
artifact to be at least as new as the build start. `source_static` mode measures
already-versioned static resources without asserting build freshness. Missing
or empty roots, no applicable artifacts, unsafe/overlapping paths, symlinks,
unreadable or concurrently changing files, stale build output, and invalid
limits fail closed. Gzip uses level 9 and timestamp zero; the zlib compile and
runtime versions are recorded because compressed size can be toolchain
sensitive.

These byte budgets complement rather than replace Lighthouse. They measure all
applicable files under configured roots, not route-specific initial-load or
tree-shaking semantics. Framework setup chooses a conventional output root;
projects with unusual bundler layouts need explicit protected configuration.

## Cross-stack adapters

- test-integrity scanning;
- changed-code review and risk reconciliation;
- strict Gherkin and acceptance example mutation;
- contract-test routing;
- golden sessions;
- secret scanning;
- deterministic CycloneDX 1.6 inventory;
- performance, reproducible build, approvals, and release readiness.

## Configuration contract

`quality/project.json` determines applicability and paths. `quality/policy.toml` points every gate to the vendored AQG adapter. Native custom commands must be protected, must execute from the repository root, and must produce fresh evidence in the expected path.

Unsupported ecosystems require an adapter that preserves:

- applicability with an explicit reason;
- isolated stale-artifact cleanup;
- bounded timeouts;
- stable 0/1/2/3 outcomes;
- machine-readable evidence;
- known-good and known-bad conformance fixtures;
- protected commands, configs, locks, exclusions, and baselines.

The broader candidate-tool table from the original design remains in `BLUEPRINT.md`; it is not a claim that those ecosystems are implemented in v2.
