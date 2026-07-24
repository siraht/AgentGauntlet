# Legacy repository adoption

> Install AQG as a ratchet: measure honestly, block new debt, and retire reviewed baselines without requiring an unsafe big-bang cleanup.

## Baseline first

Run from a clean revision, inventory existing tests and collection, coverage, complexity/CRAP, suppressions, dependency findings, flaky tests, and mutation feasibility. Separate pre-existing debt from tool/configuration failures. Missing evidence is not debt and cannot be baselined as pass.

## Changed-code policy

In adopt mode, formatting, lint, structural limits, changed-line coverage, and mutation focus on changed production scope while type checks may need the full dependency graph. New and materially changed functions meet current thresholds; existing untouched debt cannot increase.

## Baselines and waivers

A baseline is machine-readable, location-specific, reviewed, and protected. It records exact findings, source fingerprint, owner, reason, expiry/retirement target, and compensating evidence. It never suppresses future findings at new locations. A waiver is narrower and temporary.

## Characterize before refactor

For risky legacy behavior, add golden/characterization and contract tests, then mutation-test the changed area. Refactor in small behavior-preserving steps. Update product specifications only when actual supported behavior is intentionally changed, not to excuse a defect.

## Progress metrics

Track remaining baseline count, changed-code threshold compliance, high-CRAP functions, mutation survivors, flaky/quarantined tests, and escaped defects. Do not optimize a single aggregate score at the cost of scope or honesty.
