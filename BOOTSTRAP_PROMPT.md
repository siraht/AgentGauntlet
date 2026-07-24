# Bootstrap Agent Quality Gauntlet v2

You are provisioning the repository’s quality system, not implementing product behavior. This is an explicitly authorized policy-maintenance task.

## Install

From the AQG source checkout or portable release:

```sh
qg setup /path/to/project --owner @OWNER --mode auto
```

Use `./qg` in a source checkout or `./install-aqg.sh` in a portable release when `qg` is not globally installed. Add `--browsers` only when Playwright browser checks should be installed now.

After setup, use the project-local command:

```sh
python3 quality/qg.py onboarding show
python3 quality/qg.py doctor
python3 quality/qg.py conformance
```

## Inventory and reconcile

Read the repository’s README, architecture, build, test, CI, deployment, data, security, and operational material. Confirm:

- product purpose, users, applications/services/libraries, and feature namespaces;
- supported languages, versions, package managers, test runners, builds, and deployment units;
- current formatting, linting, typing, testing, coverage, contracts, browser, security, and performance commands;
- data stores, migrations, external APIs, identity/permissions, billing, privacy, destructive operations, failure detection, and rollback;
- existing CI, protected branches, CODEOWNERS, and release authority.

Do not guess when source and documentation conflict. Record the conflict for human resolution.

## Complete product-specific onboarding

Use `python3 quality/qg.py onboarding next` until all blockers are resolved.

1. Replace placeholder product context in `KEYSTONE.md`.
2. Create the smallest accurate active feature specifications; keep future behavior under `TODO.*`.
3. Add or map executable tests to current behavior.
4. Add Gherkin, contract, golden, browser, and QA evidence only where they improve the independent oracle.
5. Review `quality/project.json` applicability, paths, commands, enforcement mode, and thresholds.
6. Install and commit exact protected checker locks with `python3 quality/qg.py tools install`.
7. Replace CODEOWNERS placeholders and enable clean authoritative CI.

Meaningful policy, feature, Gherkin, QA, golden, schema, migration, dependency, approval, and waiver changes must be surfaced for human review.

## Prove the system

Run:

```sh
python3 quality/qg.py doctor --strict-tools
python3 quality/qg.py conformance --tools
python3 quality/qg.py risk-card
python3 quality/qg.py check fast
python3 quality/qg.py check-risk --keep-going
python3 quality/qg.py review --write --sarif
```

Deliberately prove that installed checkers reject known defects. Missing tools, missing reports, stale evidence, zero unexpected tests, crashes, timeouts, and skipped required controls are not passes.

## Final report

Report:

- detected stacks and project boundaries;
- selected adoption mode and threshold ratchets;
- applicable and explicitly non-applicable gates with reasons;
- exact locked checker inputs and conformance results;
- active/TODO behavior contracts;
- remaining onboarding gaps;
- every failure, survivor, skip, waiver, stale approval, and infrastructure problem;
- manual QA, failure detection, rollback, CI, branch-protection, and code-owner status.

Do not claim guarded autonomy is ready while onboarding blockers or required unknowns remain.
