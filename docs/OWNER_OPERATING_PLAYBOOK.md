# Owner operating playbook

This is the day-to-day procedure for a project owner who does not review implementation code.

## One-time setup for a repository

1. Copy this kit into the repository root.
2. Start Codex or Claude Code from that root and provide `BOOTSTRAP_PROMPT.md` as the task.
3. The agent inventories the stack and proposes product namespaces, risk boundaries, native quality tools, thresholds, protected files, and expected runtimes before it changes product contracts.
4. Review the proposal in plain language. Correct what the product does, what it must never do, which failures are serious, and what rollback is possible.
5. Let the agent provision adapters and deliberately break fixtures to prove each gate catches its intended fault.
6. Require `doctor`, `check fast`, and the example risk-card tests to pass after maintenance overrides are unset.
7. Install the CI and CODEOWNERS templates, then enable branch protection so required checks and policy-owner review cannot be bypassed by the builder.

Do not accept a setup report that says a gate is “planned,” “skipped for now,” or green with missing output. The initial scaffold is intentionally red until each active gate is real.

## Starting a normal change

Give the agent the outcome you need, then require these artifacts before implementation:

- a one-paragraph change summary;
- the change-risk card and its computed minimum profile;
- changed and preserved behavior;
- proposed active/TODO feature-spec changes;
- Gherkin examples for success, failure, boundary, retry, and recovery where relevant;
- a QA and rollback plan for High assurance or Critical work.

A useful task preamble is:

```text
Use the repository's Agent Quality Gauntlet. Before implementation, show me the
plain-language risk card, applicable feature requirements, proposed acceptance
examples, behavior that must remain unchanged, and rollback. Do not modify the
protected policy plane. Run the profile resolved by check-risk and report every
survivor, skip, waiver, infrastructure error, and human-review-plane change.
```

## What to approve before coding

You are approving intent, not implementation technique. Check that:

- the examples describe what a user or external system can observe;
- permissions, data deletion, privacy, money, migrations, concurrency, and irreversible actions are classified honestly;
- invalid and boundary cases are concrete rather than “handle errors correctly”;
- the rollback restores a safe state and accounts for data changes;
- the selected profile is no weaker than the computed minimum;
- a TODO document is not being treated as permission to implement unrelated work.

For routine Standard changes, this review can be a focused spot check. For High assurance and Critical changes, inspect every behavioral example and QA step.

## What the agent may change

During normal work, the builder may change source code and ordinary implementation tests. It may propose changes to feature specifications, Gherkin, QA procedures, migrations, API schemas, and goldens, but those changes are listed separately for your review.

The builder may not change gate commands, thresholds, exclusions, baselines, waivers, quality scripts, agent hooks, CI quality workflows, or aliases that determine what a gate runs. Those require a separate policy-maintenance task and owner approval.

## Reading the completion report

A valid report answers these questions directly:

1. Which risk profile was selected, what minimum did the resolver calculate, and why?
2. Which required gates ran from a clean environment?
3. Did any tool crash, time out, use stale data, find no tests, or fail to produce a report?
4. Did any source or acceptance mutation survive, and what behavior could that missing assertion allow?
5. Were tests deleted, skipped, relaxed, broadly mocked, or rewritten with weaker expectations?
6. Did a golden, feature specification, Gherkin file, QA procedure, migration, or public schema change?
7. What manual QA was run, what was observed, and who performed it?
8. How will production failure be detected, and what exact rollback is available?

A green summary is insufficient when one of these answers is unknown.

## Merge decision by profile

**Experiment:** Merge only into disposable or isolated environments. Never use the label to avoid production checks.

**Standard:** A clean PR profile plus your review of behavioral changes is normally sufficient after the repository has earned trust. Keep implementation code review while the gauntlet is new or unstable.

**High assurance:** Require the independent verifier, complete human review of behavior and QA artifacts, manual QA, mutation triage, and operational rollback evidence.

**Critical:** Require independent human code and specification review, adversarial review where applicable, production-like rehearsal, staged rollout, telemetry, a kill switch, and a release approver separate from the builder.

## Handling a failure

- **Quality failure:** The checker ran and found a real violation. The agent fixes the code or strengthens evidence; it does not lower the bar.
- **Configuration error:** The policy, input, or gate is invalid. Stop and repair the quality system through a policy-maintenance task.
- **Infrastructure error:** The checker could not establish a result. Rerun only after fixing the environment; never count it as a pass or a killed mutant.
- **Mutation survivor:** Ask what plausible defect survived, then require a stronger assertion or a narrowly justified equivalent-mutant classification.
- **Golden diff:** Decide whether the behavior change is intended from the raw diff. Do not let the builder bulk-approve it.
- **Waiver request:** Require exact scope, owner, rationale, compensating control, issue reference, and expiration. Broad or permanent waivers should be rejected.

## Earning reduced code review

Do not stop reading agent-authored implementation immediately after installation. First collect evidence across representative changes: stable clean CI, no silent skips, low flake, trustworthy coverage provenance, consistently triaged mutants, successful rollback rehearsal, and an acceptable escaped-defect record. The blueprint recommends a pilot across roughly 20–30 successful changes and at least one representative release cycle before reducing implementation review for Standard work.

Critical work and any area where the controls have not proved reliable retain human code review.

## Portfolio routine

For multiple projects, keep the core and adapter packs in a central versioned repository. Track each project's pinned version, onboarding phase, risk classification, last deep/release run, open waivers, mutation survivors, flaky tests, and rollback rehearsal. Roll out core upgrades through conformance repositories and canary projects rather than asking one agent to rewrite every repository at once.
