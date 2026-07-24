# Agent Quality Gauntlet guidance index

> Operational playbooks for agents and human reviewers. These are working instructions, not background reading.

## Start here

1. `agent-workflow` — the required sequence for every change.
2. `test-strategy` — choose the smallest independent set of oracles that can prove the behavior.
3. `test-design-catalog` — derive cases from invariants, boundaries, state transitions, failures, permissions, and concurrency.
4. `qa-procedures` — write reproducible manual and semi-automated procedures.
5. `automated-review` — understand what AQG flags and what still requires judgment.

## Test layers

- `unit-tests`
- `property-based-testing`
- `fuzzing-state-models`
- `contract-testing`
- `api-contracts`
- `acceptance-gherkin`
- `web-ui-playwright`
- `golden-session-testing`
- `mutation-testing`
- `test-integrity`

## Stack playbooks

- `javascript-typescript`
- `python`
- `html-css-quality`
- `accessibility`

## Risk and operations

- `security-supply-chain`
- `threat-modeling`
- `authentication-authorization`
- `migrations-data`
- `performance-reliability`
- `observability-recovery`
- `release-readiness`
- `fixtures-determinism`
- `legacy-adoption`
- `tool-conformance`

## Evidence and sources

- `research-basis` records the primary standards and official tool guidance used to derive these rules.

Agents MUST read the applicable guide before creating a new test category, waiver, expected-output artifact, mutation configuration, QA procedure, or release approval. A guide does not authorize changing protected policy files.
