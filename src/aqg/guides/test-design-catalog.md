# Test design catalog

> Derive tests systematically from the behavior model instead of asking an agent to “add edge cases.”

## 1. Invariants

Write statements that must remain true across all valid operations. Examples: balances never become negative without an explicit overdraft state; one tenant cannot observe another tenant’s object; a successful retry creates at most one durable operation; serialized and parsed values preserve meaning. Turn each invariant into property tests and targeted examples around state transitions.

## 2. Equivalence partitions

Divide the input domain into groups expected to behave the same: valid/invalid identifiers, supported/unsupported formats, active/suspended/deleted accounts, authorized/unauthorized roles, empty/single/many collections. Test one representative from each partition, then use properties or fuzzing to explore within important partitions.

## 3. Boundary-value analysis

For every numeric, temporal, size, pagination, rate, text-length, and collection limit, test `min-1`, `min`, `min+1`, a nominal value, `max-1`, `max`, and `max+1` when meaningful. Include daylight-saving transitions, leap days, time-zone conversion, integer precision, Unicode normalization, empty strings, whitespace-only strings, and maximum encoded payload size.

## 4. Decision tables

When behavior depends on several booleans or categories, create a table before tests. Columns are conditions; rows are distinct outcomes. Collapse impossible or equivalent combinations explicitly. Authorization, discounts, feature flags, retry policy, and state-dependent actions often need this technique.

## 5. State-transition tests

Model allowed states, actions, next states, and forbidden transitions. Test every transition at least once, every terminal state, repeated actions, interrupted transitions, stale versions, and concurrent transition attempts. A state machine or model-based property test is preferable when sequences are combinatorial.

## 6. Pairwise and combinatorial interaction

For configuration matrices, browsers, roles, feature flags, storage backends, and locales, use pairwise generation for routine compatibility, then add explicit higher-order combinations for known risk clusters. Do not claim full combinatorial coverage from a handful of hand-selected examples.

## 7. Metamorphic properties

When exact expected output is difficult, assert relationships: sorting twice equals sorting once; encode/decode round-trips; adding a neutral item does not change the result; reordering independent input does not change an aggregate; a stricter permission set cannot grant more access; scaling all weights by a constant preserves normalized proportions.

## 8. Error guessing from history

Inspect prior incidents, support tickets, bug fixes, mutation survivors, flaky tests, and code hotspots. Convert recurring defects into permanent regression tests and, where generalizable, properties or checker rules. Historical evidence is a design input, not a substitute for systematic techniques.

## 9. Fault injection

Inject timeout, refused connection, malformed response, partial write, disk-full/permission failure, stale cache, duplicate delivery, out-of-order event, process interruption, and dependency degradation at controlled seams. Verify both the user-visible result and durable side effects.

## 10. Negative capability

Assert that forbidden behavior does not occur: no extra database write, no event publication on rejection, no secret in logs, no cross-tenant query, no destructive action during dry run, no stale golden approval, and no fallback from denied to allowed.

Each test should name the design technique in a comment or test description when the rationale is not obvious. This makes future pruning and review much safer.
