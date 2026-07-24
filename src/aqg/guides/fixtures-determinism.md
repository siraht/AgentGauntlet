# Fixtures and determinism

> Make every required test reproducible by controlling time, randomness, identity, network, process state, storage, and cleanup; preserve realistic semantics through contract-verified fakes.

## Fixture principles

Use the smallest state that exposes behavior, with explicit names and builders. Keep defaults valid and boring; individual tests override only meaningful fields. Avoid giant shared fixtures whose irrelevant details create brittle diffs.

## Controlled sources

Inject clock/time zone, random generator, ID source, environment/config, filesystem root, network client, database sequence, and scheduler. Use unique per-test namespaces and disposable directories/databases. Record seeds for randomized order and property failures.

## Network and third parties

CI should use contract-verified fakes or recordings. Live tests run separately with controlled credentials and do not gate every commit. Recordings normalize only unstable fields, are redacted, versioned, and revalidated when the contract or dependency changes.

## Flake policy

A first-run failure followed by retry success is flaky, not passed. Quarantine requires an owner, issue, narrow scope, expiry, and compensating coverage; it cannot silently leave required profiles. Diagnose order dependence by shuffled runs and parallel isolation, timing by controlled clocks/web-first waits, and resource collision by unique ports/paths.
