# Owner operating playbook

This is the day-to-day AQG v2 workflow for a product owner who does not normally review implementation code.

## Install once

```sh
./install-aqg.sh /path/to/project --owner @your-org/quality --mode auto
```

Use `--browsers` for a web project when browser checks should be installed now. Setup detects stacks, installs a protected project model, creates isolated toolchain definitions, generates agent/CI integrations, and writes `quality/onboarding.json`.

Then have an agent work through:

```sh
python3 quality/qg.py onboarding show
python3 quality/qg.py doctor --strict-tools
python3 quality/qg.py conformance --tools
```

You personally confirm the product context, current behavior, serious failure modes, rollback, real CODEOWNERS, and which workflows are authoritative.

## Start a change

Ask for these before implementation:

- plain-language summary;
- deterministic risk minimum and selected profile;
- behavior changing and behavior preserved;
- active/TODO feature changes;
- valid, invalid, boundary, permission, retry, and recovery examples where relevant;
- QA, failure detection, and rollback for High-assurance/Critical work.

A useful task preamble:

```text
Use this repository's Agent Quality Gauntlet. Show me the change-risk card,
applicable behavior contracts, proposed acceptance examples, preserved behavior,
and rollback before implementation. Do not weaken the policy or tests. Run
check-risk and report every survivor, skip, waiver, stale approval, and
infrastructure error.
```

## Monitor work

The agent uses:

```sh
python3 quality/qg.py check fast
python3 quality/qg.py status
python3 quality/qg.py review --write
```

You can open:

```sh
python3 quality/qg.py dashboard --open
```

The dashboard is read-only unless explicitly started with `--allow-actions`.

For an additional technical review without making provider calls blindly:

```sh
python3 quality/qg.py council doctor
python3 quality/qg.py council plan --tier pr
python3 quality/qg.py council run --tier pr
```

Read the plan before `run`: it names the exact revision, comparison base,
bundle size, models, roles, and current quality evidence. A council report is
advice, not permission. Ask it to explain consensus, unique findings, dissent,
unknowns, and the smallest safe next action in plain language.

## Review before merge

Read `.aqg/review/review.md` and ask:

1. What changed for a user or external system?
2. What invalid, boundary, permission, retry, and recovery behavior was exercised?
3. Which required profile ran against the final diff?
4. Did any tool crash, time out, find no tests, or miss a report?
5. Which source or acceptance mutants survived?
6. Were tests, expectations, mocks, goldens, thresholds, or suppressions weakened?
7. Which feature specs, Gherkin, QA, schema, migration, auth, dependency, policy, waiver, or approval files changed?
8. What detects failure and what exact rollback is available?
9. Did independent model reviewers agree, dissent, abstain, or fail, and does
   each claim cite the exact candidate evidence?

A green summary is insufficient if any required answer is unknown.

## Decision by risk

- **Experiment:** isolated/disposable work only.
- **Standard:** clean PR profile plus behavior review after the repository has earned trust.
- **High assurance:** deep profile, independent read-only verifier, complete behavior review, mutation triage, manual QA, and rollback evidence.
- **Critical:** release profile, independent human code/specification review, adversarial review as applicable, production-like rehearsal, staged rollout, telemetry, kill switch, and separate release approval.

## Handle failures

- Exit 1: fix the quality defect or make an explicit reviewed product decision.
- Exit 2: repair invalid policy/configuration/input through policy maintenance.
- Exit 3: repair the environment or checker; never call it green.
- Survivor: strengthen the oracle or narrowly justify an equivalent mutant.
- Golden diff: review the raw behavior change; never bulk-approve it.
- Waiver: require exact scope, owner, rationale, compensating control, decision link, and expiration.

## Earn reduced implementation review

Keep normal code review while AQG is new. Consider reducing it only after roughly 20–30 representative Standard changes and a release cycle demonstrate stable clean CI, trustworthy discovery/coverage, low flake, consistently triaged mutants, working approvals, acceptable escaped defects, and successful rollback rehearsal. Critical work retains human code review.
