# Fuzzing and state models

> Use fuzzing for parser and protocol robustness, and model-based testing for sequences; capture minimized reproducers and separate crashes from semantic failures.

## Fuzzing targets

Prioritize untrusted boundaries: parsers, decoders, file formats, URL and header handling, template/render inputs, archive extraction, serialization, command-line parsing, query builders, and protocol adapters. The target must have a deterministic entry point and explicit resource limits.

## Oracles

A fuzz target needs more than “does not crash.” Add assertions for memory/time limits, round-trip properties, canonicalization, rejection of malformed input, no path traversal, no injection, no leaked secret, and equivalence with a reference parser where available. Treat sanitizer findings, hangs, excessive allocation, and unhandled exceptions as failures.

## Corpus management

Seed with valid minimal examples, boundary forms, prior regressions, protocol examples, and mutation survivors. Commit only small high-value reproducers. Never commit raw sensitive production payloads. Hash or synthesize them.

## State models

Represent operations, preconditions, expected transition, and observable state. The model should be simpler than the implementation. Generate sequences, compare after every step, and minimize a failing sequence. Test duplicate and out-of-order events, process restart, stale reads, concurrent updates, and compensation.

## Operational limits

Fast profiles may run regression corpus only. Deep/release profiles run bounded fuzz time with deterministic artifact retention. Long-running continuous fuzzing belongs in a separate scheduled pipeline, but every discovered reproducer must enter the required regression corpus.
