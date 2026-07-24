# Mutation testing

> Mutation testing measures whether tests detect plausible faults; scope it with fresh coverage, classify survivors, and never treat cached or manifest-only updates as evidence.

## Preconditions

The unmodified baseline must pass. Coverage and source maps must be fresh and attributable to the same source/test revision. Each worker uses an isolated directory or process. Timeouts, crashes, missing reports, stale coverage, and protocol failures are infrastructure failures, not killed mutants.

## Scope

PR/deep runs should mutate changed production functions plus directly affected high-risk modules. Release runs should mutate the full relevant security/data/contract surface. Do not mutate generated code, vendored code, type declarations, trivial constants without semantic value, or unreachable/dead code merely to inflate counts.

## Result handling

- **Killed:** a relevant test failed because behavior changed.
- **Survived:** tests passed; add or strengthen a semantic oracle.
- **No coverage:** treated as undetected and a coverage/oracle defect.
- **Compile/runtime invalid:** excluded from mutation score but reported.
- **Timeout:** investigate; count as detected only when the mutation caused a bounded, observable behavior and the tool’s semantics are explicit.
- **Equivalent:** suppress only with a concrete proof and narrow reviewed rule.

Review survivors one by one. Group by missing boundary, weak assertion, missing side-effect check, unreachable behavior, equivalent mutant, or test isolation issue. A percentage target does not authorize unexplained survivors in authentication, authorization, money, privacy, persistence, safety, or external contracts.

## Caching

Cache only when source, tests, specifications, configuration, dependencies, generated entry points, handlers, runtime, runner adapter, and mutation implementation fingerprints match. Stryker incremental mode does not see every environmental or non-test-file change, so AQG’s authoritative runs disable incremental reuse unless the full fingerprint model is satisfied.

## Test the mutation tool

Tool conformance must seed a known mutant that a strong test kills and a weak test lets survive. Verify report parsing, exit codes, missing-report behavior, worker isolation, and restoration after interruption.
