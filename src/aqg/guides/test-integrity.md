# Test integrity

> Before trusting test results, prove that intended tests were collected, executed, isolated, and not weakened by skips, focus markers, suppressions, or malformed structure.

## Collection checks

Record collected test count and file/module distribution. Fail when production source exists but zero tests are collected, an expected directory is absent, duplicate module names shadow tests, a plugin changes discovery unexpectedly, or a test file cannot import. Review count decreases against the previous current run.

## Forbidden markers

Required profiles reject focused tests (`only`), skips/todos/xfail without a protected baseline, coverage ignores, mutation disables, type/lint suppressions, and broad accessibility exclusions. A narrow temporary waiver needs owner, reason, exact location, compensating evidence, and expiry.

## Structure and execution

Use framework strict modes. Validate nested test structures when a framework can silently ignore them. Run order-randomization where supported and repeat selected tests to detect hidden shared state. A retry may collect diagnostic evidence but does not turn a flaky first failure into a pass.

## Assertion integrity

Flag deleted assertions, broad truthiness checks, empty exception catches, snapshot-only tests for critical invariants, mocks without semantic assertions, and tests that duplicate production algorithms. Mutation testing is the strongest automated check for oracle weakness.

## Isolation

Each test owns its records, files, ports, clock, random seed, process state, and browser context. Cleanup runs on failure. Tests do not depend on execution order or mutate global production configuration. Parallel execution should not create collisions.

## Evidence

The test-integrity report must include discovered files, collected count, skip/focus/suppression findings, baseline differences, and exact command. Missing or unparseable collection evidence is configuration/infrastructure failure.
