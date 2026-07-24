# Agent Quality Gauntlet

This starter kit implements a **constraint-first quality system for coding agents**. It is intentionally language-agnostic: the repository owns one policy and one evidence format, while project-specific adapters call the native formatter, compiler, test runner, coverage tool, mutation tool, security scanner, and acceptance runner for the detected stack.

The scaffold is deliberately **fail-closed**. `quality/policy.toml` starts with `initialized = false`, and placeholder commands are treated as configuration errors. A coding agent must inspect the target repository, propose the risk profile and behavioral contracts, configure real commands, and prove the gates work before the system can report green.

## Start here

1. Read [`BLUEPRINT.md`](BLUEPRINT.md) for the complete design and adoption plan.
2. Give [`BOOTSTRAP_PROMPT.md`](BOOTSTRAP_PROMPT.md) to Codex or Claude Code from the repository root.
3. Review the proposed product behavior, risk profile, Gherkin examples, and QA procedures. You do not need to review implementation code to do this.
4. Let the agent configure `quality/policy.toml`, language adapters, CI, and conformance fixtures.
5. Run:

```sh
python3 quality/qg.py doctor
python3 quality/qg.py risk-card --card quality/change-risk.json
python3 quality/qg.py check fast
python3 quality/qg.py check-risk --card quality/change-risk.json
```

6. Enable branch protection and code-owner review for the policy and human-review planes before relying on the gauntlet.

## Repository map

```text
AGENTS.md                              Codex and generic-agent working contract
CLAUDE.md                              Thin Claude Code entry point
QUALITY.md                             Normative quality policy
KEYSTONE.md                            Product-context and feature-contract template
feature-spec/                          Durable active and TODO behavior contracts
features/                              Gherkin acceptance specifications
qa/procedures/                         Human-readable manual QA procedures
quality/
  policy.toml                          Risk profiles, gates, protected paths
  qg.py                                Deterministic gate orchestrator and hook guard
  schemas/                             Stable evidence and risk-card schemas
  adapters/                            Adapter contract and examples
  conformance/                         Fixtures that test the quality tools themselves
  tests/                               Self-tests for the orchestrator
.claude/                               Claude Code hooks, skill, and verifier agent
.codex/                                Codex hooks and verifier agent
.agents/skills/                        Codex-compatible reusable skill
ci/                                    CI and CODEOWNERS templates
docs/                                  Owner playbook, source synthesis, rollout, adapters, and threat model
global/                                Optional user-level Codex and Claude defaults
```

For a multi-repository deployment, read `docs/PORTFOLIO_ROLLOUT.md`; it describes a centrally versioned core, ecosystem adapter packs, pinned reusable CI, repository onboarding, and upgrade governance. `docs/OWNER_OPERATING_PLAYBOOK.md` gives the nontechnical day-to-day workflow, and `docs/SOURCE_SYNTHESIS.md` maps every supplied source to the mechanism retained, its failure modes, and the framework adaptation.

## What this kit does and does not do

It gives every project the same control architecture, command surface, evidence model, agent workflow, and human-review boundaries. The bootstrap agent still has to select and configure stack-native tools because cyclomatic complexity, coverage, mutation testing, package auditing, and test discovery are language-specific.

The system is strongest when the policy plane is protected outside the agent’s control. Local hooks reduce accidental or opportunistic edits, but the authoritative enforcement boundary is a clean CI runner plus branch protection or a centrally managed reusable workflow.

The risk card cannot select a profile below the deterministic minimum implied by production scope, reversibility, blast radius, and sensitive risk factors. A human may always select a stricter profile.

The policy model is language-agnostic, but this reference orchestrator requires **Python 3.11+** because it uses the standard-library TOML parser. For repositories that cannot guarantee that runtime, publish the same core as a pinned standalone binary or container; do not maintain divergent rewrites of the policy in each project.

The kit reimplements the control architecture rather than copying the referenced repositories. Before vendoring or redistributing any external checker, verify its current license and pin its version; an adapter may call an installed tool without making that tool part of this kit.
