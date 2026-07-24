# Property-based testing

> Use generated data to prove invariants and state relationships across a domain; keep strategies valid, shrinkable, deterministic under replay, and free of blanket health-check suppression.

## Choose a property

A property is a relationship that should hold for many inputs, not a reimplementation of the production algorithm. Good families include:

- round trip: `decode(encode(x)) == x` for supported values;
- idempotence: `normalize(normalize(x)) == normalize(x)`;
- monotonicity: increasing an entitlement cannot reduce allowed actions unless specified;
- conservation: totals before and after a transfer are equal;
- permutation invariance: order of independent inputs does not change the aggregate;
- model equivalence: the implementation result matches a small obviously correct model;
- state-machine invariants after arbitrary valid action sequences;
- metamorphic relations when exact outputs are expensive to calculate.

## Strategy design

Generate values from the real semantic domain. Prefer constructors that only create valid entities, then define a separate invalid-input strategy. Avoid `assume` or filters that discard most examples; they waste exploration and often trigger health checks for good reason. Bias toward boundaries and special values while retaining broad variation.

Persist the failing seed/example that found a defect as a named regression test, while retaining the property so adjacent defects remain discoverable. Do not hardcode a random seed globally to make a broken property appear stable; Hypothesis and fast-check already record reproducible failure information.

## Stateful tests

Model state with a small reference implementation and commands with preconditions. Compare observable outputs after each command and assert invariants after every transition. Include retries, duplicates, cancellations, stale versions, and concurrent interleavings where applicable.

## CI profile

Use a bounded but meaningful example count in fast/PR profiles and a larger count or deadline-free run in deep/release profiles. Store failure artifacts. A timeout is infrastructure failure unless the test deliberately proves a performance bound.

## Review checklist

- Does the property state a business or mathematical invariant rather than mirror implementation code?
- Can the generator reach boundaries, empty values, Unicode, maximum sizes, and unusual state sequences?
- Are invalid values separated from valid-domain generation?
- Are health checks or shrink phases being suppressed? Any suppression requires narrow justification.
- Would a deliberately wrong implementation fail? Confirm with mutation or a temporary seeded fault.
