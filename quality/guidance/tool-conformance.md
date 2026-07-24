# Tool conformance

> A checker is trustworthy only after positive and negative fixtures prove its scope, exit semantics, report production, cleanup, and failure behavior.

## Contract

For each tool record version/digest, command, working directory, inputs, exclusions, expected reports, timeout, exit-code mapping, and applicability. AQG normalizes: 0 pass, 1 quality defect, 2 configuration/input error, 3 infrastructure/missing trustworthy evidence.

## Required fixtures

- known-good fixture passes;
- one seeded defect of each relied-upon rule fails;
- excluded file is ignored and included file is measured;
- zero tests/zero source/missing report fails closed when applicable;
- stale report is deleted or rejected;
- timeout/crash maps to infrastructure failure;
- concurrent workers do not share mutable directories;
- interrupted mutation restores source;
- path spaces/Unicode and monorepo modules resolve correctly;
- machine-readable report parser handles current schema.

## Upgrades

Upgrade tools only in policy maintenance. Regenerate exact locks, run full conformance, compare rule/default/report changes, and document threshold impact. Do not automatically float major versions in CI.
