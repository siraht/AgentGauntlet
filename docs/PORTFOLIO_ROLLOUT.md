# Rollout across all projects

A reusable quality system should have one centrally governed core and thin project adapters. Copying unrelated configurations into every repository and letting each one drift recreates the problem the system is meant to solve.

## Target operating model

Create a private or public central repository for the Agent Quality Gauntlet core. Version the orchestrator, schemas, bootstrap prompt, conformance fixtures, agent skills, verifier definitions, and reusable CI workflow there. Each product repository keeps only:

- a pinned core version or vendored core with a recorded digest;
- `quality/policy.toml` containing project risk and gate selection;
- small stack-native adapters under `quality/bin/`;
- product intent under `KEYSTONE.md`, `feature-spec/`, `features/`, and `qa/`;
- the current change-risk card and project-owned evidence;
- branch-protection and code-owner bindings.

The authoritative CI workflow should come from the central repository at a pinned immutable revision. A local workflow may install dependencies and call adapters, but it should not be able to replace the central policy verifier without code-owner approval.

## Core runtime distribution

The included reference core uses Python 3.11+, which is acceptable only when that runtime is part of the supported CI image. For heterogeneous fleets, package the core as a signed standalone executable or immutable container and pin its version and digest in every repository. The repository adapters may vary by language, but the policy parser, risk resolver, evidence schema, and exit semantics must remain one centrally tested implementation.

## Onboard one repository at a time

1. **Inventory and baseline.** Run the bootstrap prompt without changing product behavior. Record existing failures, skips, coverage, complexity, flake, security findings, and build reproducibility.
2. **Install the fast core.** Configure format, lint, compile/type, test discovery, unit tests, structure/CRAP, fresh changed coverage, secrets, hooks, and clean CI.
3. **Add intent.** Specify only the highest-value active behavior first, then add Gherkin and QA procedures at risky boundaries.
4. **Add test-quality gates.** Start differential source mutation on changed logic, then acceptance mutation where Examples tables carry important behavior.
5. **Add deep controls by risk.** Goldens, security analysis, migration rehearsal, performance, fuzzing, canarying, and rollback are selected by the repository's actual failure costs.
6. **Earn reduced implementation review.** Reduce code review only after the repository has stable, independently enforced evidence and acceptable escaped-defect history. Keep human code review for Critical scopes.

## Adapter packs

Maintain versioned adapter packs per ecosystem rather than rediscovering tools for every repository: Python, TypeScript, Go, Java/Kotlin, .NET, Rust, C/C++, Ruby, PHP, and Clojure. Each pack should provide deterministic wrappers, conformance fixtures, current tool-version compatibility, report normalization, and documented exclusions. Repositories may override a pack only through policy maintenance.

## Portfolio registry

Track every repository in a small registry with:

- owner and business criticality;
- core and adapter-pack versions;
- onboarding phase;
- default and maximum risk profile;
- required CI checks and branch protections;
- last clean deep/release run;
- open waivers, mutation survivors, flaky tests, and infrastructure failures;
- rollback rehearsal date;
- upgrade status.

This registry is operational inventory, not a quality score. It shows where evidence is missing and where enforcement has drifted.

## Upgrade process

Release the core with semantic versions and migration notes. Test a new release against conformance repositories for every adapter pack, canary it on low-risk projects, then roll it out in batches. Never let an agent bulk-update policy and approve the resulting changes in the same workflow.

## Metrics that matter

Measure whether the gauntlet itself is reliable: gate runtime, flake rate, infrastructure-error rate, stale-artifact incidents, mutation survivors by severity, waiver age, manual-QA discoveries later converted to automation, escaped production defects, rollback success, and time agents spend untangling structural debt. Avoid ranking teams by raw coverage or mutation percentage because that encourages metric gaming.

## Global agent defaults

The templates under `global/` can be merged into `~/.codex/AGENTS.md` and `~/.claude/CLAUDE.md`. They make onboarded repositories discoverable without duplicating the full policy globally. Keep the repository policy authoritative because project risk and commands differ.
