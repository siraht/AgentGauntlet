# Golden session testing

> Capture broad deterministic behavior as structured text, normalize only truly unstable fields, and separate comparison from human-approved update.

## Use when

Golden sessions fit CLI workflows, compilers, agent/tool traces, complex transformations, import/export, multi-step state changes, and broad web/API sessions where a readable trace reveals unexpected side effects. Use ordinary assertions when the output is small and obvious.

## Session schema

Capture inputs, configuration affecting behavior, ordered actions/events, outputs, side effects, files read/written, relevant state snapshots, and stable errors. Classify every field:

- stable — compare exactly;
- canonicalizable — sort or normalize deterministically without losing meaning;
- unstable but meaningful — replace with a typed placeholder such as `[REQUEST_ID]`;
- secret/personal — omit or redact before artifact creation.

Normalization occurs before writing the actual artifact, not as a broad wildcard during comparison. Never pattern-match a value you control, because doing so hides regressions.

## Hermetic execution

Inject clocks, random sources, identifiers, network clients, database sequences, and environment. Use the same application code path in live and mocked modes. CI uses mocked/replayed dependencies; an explicit maintenance flow may use live mode to refresh fixtures.

## Update control

Normal `golden` execution compares and fails. `golden --update` requires the protected authorization variable and still creates a review-plane diff. The updating agent cannot approve the result. Review the full diff, source change, normalizer, and fixture provenance.

## Artifact limits

Shard by scenario and phase. Keep files text-based and reviewable; add size/line limits. Capture full state within that budget rather than piping output through narrow `grep`/`jq` projections that only show expected fields.

## Complementary assertions

Add schema validation, event ordering, totals, referential integrity, and critical invariants alongside the raw diff. Mutation or temporary seeded faults should prove that important fields are connected to behavior.
