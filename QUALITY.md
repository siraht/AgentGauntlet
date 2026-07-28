# Quality policy

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHOULD**, **SHOULD NOT**, and **MAY** are normative.

## Authority

`quality/policy.toml` is the machine-readable policy. This file explains its intent. A mismatch between the two is a configuration error that MUST be resolved explicitly.

The authoritative result comes from a clean CI run. Agent statements, local output, cached artifacts, and prior reports are not substitutes.

## Protected policy plane

During ordinary feature or bug-fix work, an agent MUST NOT modify:

- `AGENTS.md` or `CLAUDE.md`
- `QUALITY.md`
- `quality/policy.toml`
- `quality/qg.py`
- quality adapters, executable wrappers, baselines, waivers, and orchestrator tests
- `quality/hooks/**`
- `quality/schemas/**`
- `quality/conformance/**`
- the quality-gauntlet skills, verifier-agent definitions, and hook settings for Codex or Claude Code
- CI quality workflows or CODEOWNERS
- stack-native configuration or script aliases that determine how a required gate runs

A change to this plane requires an explicit policy-maintenance task, conformance tests, and human/code-owner approval.

`AQG_POLICY_MAINTENANCE` and `AQG_ALLOW_GOLDEN_UPDATE` MUST be unset during authoritative checks. They are narrow maintenance controls, not a way to obtain passing evidence, and `doctor`/`check` reject them when enabled.

A legitimate local policy-maintenance operation MUST first be declared with an
exact add/modify/delete/rename path:

```sh
python3 quality/qg.py maintenance request \
  --change modify:quality/project.json \
  --reason "Describe the independently reviewed policy change"
```

The request is fingerprinted to the current candidate and controls and carries
no approval authority. With `AQG_POLICY_MAINTENANCE=1`, local hooks MAY permit
only the exact declared operations; shell writes and undeclared protected
paths remain blocked. PR, deep, and release evidence MUST derive the actual
protected diff and require a current independent approval for the same
operation and path. The builder MUST NOT create or approve that independent
record.

## Human-review plane

Changes under these paths are allowed proposals but MUST be surfaced separately for human review:

- `KEYSTONE.md`
- `quality/change-risk.json`
- `feature-spec/**`
- `features/**`
- `qa/procedures/**`
- approved golden/snapshot directories
- database migrations
- public API or schema definitions
- authentication, authorization, cryptography, billing, and privacy policy files

## Required workflow

Before implementation, the agent MUST:

1. establish the baseline;
2. read applicable product contracts;
3. create a change-risk card;
4. run `python3 quality/qg.py risk-card` and select a risk profile at or above its deterministic minimum;
5. identify evidence for every changed requirement;
6. report conflicts instead of guessing.

Before declaring completion, the agent MUST:

1. run `python3 quality/qg.py doctor`;
2. run `python3 quality/qg.py check-risk`;
3. resolve or explicitly report every failure, survivor, skip, waiver, and infrastructure error;
4. invoke an independent read-only verifier for High assurance and Critical work;
5. identify all human-review-plane changes;
6. provide rollback and manual-QA status where required.

## Evidence status

- Exit `0`: pass.
- Exit `1`: quality failure.
- Exit `2`: configuration or usage error.
- Exit `3`: infrastructure error.
- Timeout: infrastructure error.

An infrastructure error MUST fail a required gate. It MUST NOT be counted as a killed mutant, passing test, or accepted skip.

## Test integrity

The project MUST fail when tests cannot be collected, when no tests are found unexpectedly, or when invalid structure causes tests to be ignored. New focused-only, skipped, disabled, ignored, or quarantined tests require an owned, expiring exception.

## Test changes

An agent MAY change tests, but it MUST NOT weaken expected behavior merely to make implementation pass. Deletions, relaxed assertions, broader mocks, new skips, altered goldens, and reduced failure expectations MUST be reported. Relevant mutation testing MUST rerun whenever production logic and tests change together.

## Metrics

New and changed code MUST meet the configured structural and coverage targets. Existing debt follows a no-regression ratchet. Metric exceptions MUST be narrow, justified, owned, and expiring.

Existing repositories MUST begin in `shadow`, create a complete manifested
debt proposal, obtain human review of that inventory, and install the reviewed
baseline through protected policy maintenance before `ratchet` can enforce.
Matching inherited debt remains visible but non-blocking. New, worsened,
malformed, or unclassified debt MUST block. Promotion is monotonic from
`shadow` to `ratchet` to `strict`; a proposal MUST NOT silently alter the stage.

## Behavioral contracts

Active feature specifications describe implemented behavior and MUST remain true. TODO specifications describe intended behavior that has not shipped. When a TODO behavior is implemented and verified, it MUST be reconciled with any active specification before becoming active.

Acceptance tests and QA procedures SHOULD describe observable outcomes rather than internal classes, functions, files, or implementation techniques.

## Mutation

Source mutation and acceptance-example mutation are separate gates. Every mutation run MUST begin from a passing baseline, isolate each mutation, classify infrastructure errors separately, and preserve enough evidence to reproduce survivors.

## Goldens

Normal test execution MUST NOT update expected golden output. Updating a golden requires explicit authorization and human review of the raw behavioral diff.

## Waivers

A waiver MUST include:

- rule or gate;
- exact scope;
- technical rationale;
- owner;
- issue or decision reference;
- creation date;
- expiry date;
- compensating control.

Expired or overly broad waivers MUST fail CI.
