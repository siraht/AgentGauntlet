# Bootstrap the Agent Quality Gauntlet in this repository

You are performing **quality-system provisioning**, not product implementation. Do not change user-visible behavior during this task.

This is an explicitly authorized policy-maintenance task. Run the provisioning session with `AQG_POLICY_MAINTENANCE=1` so the existing local hooks permit deliberate policy-plane edits. Do not leave that environment variable enabled for ordinary implementation work.

Unset `AQG_POLICY_MAINTENANCE` and `AQG_ALLOW_GOLDEN_UPDATE` before final `doctor`, `check`, or `check-risk` runs. The orchestrator intentionally rejects authoritative evidence collected while either override is enabled.

The repository contains an Agent Quality Gauntlet scaffold. Read, in order:

1. `BLUEPRINT.md`
2. `QUALITY.md`
3. `AGENTS.md`
4. `KEYSTONE.md`
5. `quality/policy.toml`
6. `quality/adapters/README.md`
7. existing README, architecture, requirements, CI, build, dependency, test, deployment, and operational documents.

Then do the following.

## 1. Inventory the real repository

Identify:

- languages, versions, package/build systems, applications, services, libraries, CLIs, and deployment units;
- test frameworks and how tests are discovered;
- current format, lint, type, build, coverage, integration, E2E, security, and performance commands;
- data stores, migrations, queues, external APIs, authentication/authorization, secrets, billing, privacy, and irreversible operations;
- existing CI, branch protections, CODEOWNERS, release process, and rollback mechanism;
- generated code and files that require special handling.

Do not guess when documents and source disagree. Report the conflict.

## 2. Establish a clean baseline

From a clean checkout or worktree:

- install dependencies using the project’s locked/reproducible mechanism;
- run the existing build and tests;
- record tool versions, failures, skips, test counts, flakiness, coverage, and existing structural hot spots;
- detect stale coverage/generated artifacts;
- identify test-framework constructs that can silently disable or ignore tests.

Do not perform a broad cleanup. Create a no-regression baseline and a changed-code ratchet.

## 3. Propose the control model for approval

Before writing product contracts, show the user:

- product surfaces and proposed top-level feature namespaces;
- which existing behavior should receive durable active specifications first;
- which roadmap behavior is TODO rather than active;
- proposed risk boundaries;
- the exact native tools and commands for each gate;
- proposed thresholds and legacy ratchet;
- which files will require human or code-owner review;
- deterministic minimum-risk escalation rules;
- expected fast, PR, deep, and release runtimes.

Explain all terms in plain language. Obtain user approval for product intent and risk classification before creating active/TODO feature files.

## 4. Configure deterministic adapters

Replace every `__CONFIGURE__` command in `quality/policy.toml` with a real command or remove the gate from every active profile with an explicit rationale.

Create `quality/change-risk.json` from `quality/change-risk.example.json`, replace every placeholder, and prove that `python3 quality/qg.py risk-card` rejects under-classified production, authorization, irreversible, and safety examples.

Prefer small wrappers under `quality/bin/` that:

- run from the repository root;
- delete or isolate stale artifacts;
- use unique work directories;
- fail on missing inputs/reports;
- return 0 pass, 1 quality failure, 2 configuration error, 3 infrastructure error;
- print tool versions and useful diagnostics;
- produce stable JSON where practical;
- have conformance fixtures.

At minimum provision:

- format check;
- lint/static analysis;
- compile/type check where applicable;
- test-structure and discovery integrity;
- unit/property tests;
- function size, cyclomatic complexity, CRAP, duplication, and architecture boundaries;
- fresh changed-code line and branch coverage;
- contracts/integration;
- targeted acceptance;
- differential source mutation;
- secret and dependency scanning.

Add golden, acceptance mutation, deep security, performance, reproducible build, migration, and release gates where the risk map requires them.

Add every file that can weaken those commands—native linter/test/coverage/mutation configuration, package-script aliases, wrapper scripts, CI workflows, baseline files, and waiver stores—to `policy.protected_paths` or an equivalent mandatory code-owner rule. Do not point a gate at a mutable script alias that a normal builder can silently redefine.

## 5. Provision product intent

After user approval:

- replace the Feature context in `KEYSTONE.md`;
- create the smallest useful active and TODO files in `feature-spec/`;
- annotate or map tests to the most specific active feature;
- add initial Gherkin scenarios for high-value behavior;
- create project-specific parser/IR/generator/runtime/handler/runner components when a portable acceptance pipeline is warranted;
- configure strict parser behavior so unsupported non-comment syntax fails instead of being silently ignored;
- add QA procedures for High assurance behavior.

Do not document every implementation detail. Define observable behavior.

## 6. Protect the system

- Keep the existing Codex and Claude Code hooks and verify them with sample JSON.
- Install/adapt CODEOWNERS and CI templates.
- Make policy-plane paths require explicit review.
- Keep normal agent permissions to workspace scope with restricted network.
- Configure the read-only verifier agents.
- Ensure normal golden comparison cannot update expected output.
- Ensure a policy-maintenance environment override is not set in ordinary sessions.

## 7. Prove the checkers

Add conformance fixtures for pass, quality fail, malformed input, missing report, stale artifact, timeout, and parallel isolation. Run the orchestrator’s own tests.

Test the system by deliberately introducing and then reverting representative faults:

- syntax/lint/type error;
- malformed or undiscovered test;
- function over complexity/size limit;
- uncovered complex branch;
- weak assertion that permits a mutant;
- acceptance example disconnected from behavior;
- unsupported Gherkin syntax that would otherwise be ignored;
- an acceptance mutant killed only by parsing/conversion rather than by application behavior or assertion;
- forbidden policy-plane edit;
- missing coverage or mutation report.

A gate is not provisioned until the deliberate fault is caught.

## 8. Finish and report

Set `initialized = true` only after:

```sh
python3 -m unittest discover -s quality/tests
python3 quality/qg.py doctor
python3 quality/qg.py risk-card --card quality/change-risk.json
python3 quality/qg.py check fast
python3 quality/qg.py check-risk --card quality/change-risk.json
```

all behave according to policy.

Provide a plain-language setup report containing:

- detected stack and boundaries;
- installed gates and exact commands;
- baseline debt and ratchet;
- thresholds;
- expected runtimes;
- active/TODO feature contracts;
- mutation and acceptance strategy;
- protected and human-review paths;
- CI/branch-protection steps still requiring the user;
- every remaining skip, waiver, survivor, flaky test, infrastructure limitation, and manual action.

Do not claim the system is complete while any configured gate is a placeholder, silently skipped, stale, or unable to distinguish infrastructure failure from quality failure.
