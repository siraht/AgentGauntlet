# Language adapter catalog

AQG v2 ships production adapters for JavaScript, TypeScript, HTML, CSS, and Python. Project-local configuration may select native test/build commands while AQG retains control of discovery, freshness, evidence, and exit semantics.

## JavaScript and TypeScript

| Control             | Default or supported mechanism                                                  |
| ------------------- | ------------------------------------------------------------------------------- |
| Formatting          | Prettier                                                                        |
| Lint/security rules | ESLint flat config and `eslint-plugin-security`                                 |
| Types               | TypeScript strict compiler configuration                                        |
| Unit tests          | Vitest default; Jest, Mocha, AVA, Node test runner, or protected custom command |
| Coverage            | Vitest V8, Jest/Istanbul, c8, or protected custom fresh report                  |
| Structure           | per-function logical lines, nesting, cyclomatic complexity, CRAP                |
| Properties          | fast-check guidance                                                             |
| Mutation            | Stryker with changed-file scope and JSON evidence                               |
| Dependencies        | native package-manager audit                                                    |
| Reproducibility     | repeated protected build and output manifests                                   |

## HTML and CSS

| Control                     | Mechanism                                                      |
| --------------------------- | -------------------------------------------------------------- |
| HTML validity/accessibility | HTML-Validate                                                  |
| CSS structure               | Stylelint standard rules                                       |
| Browser journeys            | Playwright isolated contexts, retries, trace/screenshots/video |
| Runtime accessibility       | axe-core Playwright integration                                |
| Performance                 | Lighthouse budgets                                             |
| Manual experience           | generated primary-journey QA procedure                         |

Source-file validation cannot see all runtime DOM behavior; important UI changes require browser and manual evidence.

## Python

| Control          | Mechanism                                      |
| ---------------- | ---------------------------------------------- |
| Format/lint      | Ruff                                           |
| Types            | mypy                                           |
| Unit tests       | pytest default; tox or protected custom runner |
| Collection       | strict pytest collection                       |
| Coverage         | coverage.py/pytest-cov JSON with branch data   |
| Structure        | Radon/Xenon plus AQG function metrics and CRAP |
| Properties/state | Hypothesis guidance                            |
| Mutation         | mutmut in isolated changed-code copies         |
| Static security  | Bandit                                         |
| Dependencies     | pip-audit                                      |
| Dead code        | Vulture in deep profiles                       |

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
