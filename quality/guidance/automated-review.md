# Automated review

> AQG’s reviewer classifies deterministic risk signals and assembles evidence; it does not replace product, security, accessibility, or release judgment.

## Blockers

The reviewer blocks policy-plane changes, production changes without changed executable evidence, deleted test expectations, new focus/skip/coverage/mutation/type/lint suppressions, invalid or under-classified risk cards, missing current profile evidence, and missing/stale required approvals.

## Human-review prompts

It highlights feature/Gherkin/QA changes, expected-output/golden changes, dependency and lock changes, migrations/schemas/contracts, public-interface changes, and traceability gaps. These are not automatically wrong; they are surfaces where a human must decide whether the behavior is intentional and safe.

## Diff heuristics are prompts

Filename and text patterns can over- or under-classify. Resolve each finding by changing the risk card/evidence or writing a concrete human decision, never by deleting the detector or renaming files. Security-sensitive behavior hidden in a generic filename still needs proper classification.

## Review packet order

1. risk resolution and required profile;
2. current revision/change/control fingerprints;
3. gate matrix with raw evidence links;
4. blockers and suppressions;
5. product/spec/acceptance/golden diff;
6. contracts/dependencies/migrations;
7. mutation survivors and coverage gaps;
8. QA, rollback, and approvals;
9. changed files.

## Automated reviewer extensions

Project-specific rules should be deterministic, small, versioned, tested with positive/negative fixtures, and report applicability. Useful extensions include API schema diffing, SQL migration linting, forbidden dependency directions, tenant-scope checks, log redaction, bundle budgets, and required telemetry. Do not insert an LLM result as a merge-blocking oracle unless its prompt/model/input are pinned, output schema is validated, false-positive handling is defined, and deterministic controls remain authoritative.
