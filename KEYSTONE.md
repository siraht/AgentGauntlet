# Product context and feature contracts

This project keeps durable product intent beside the code.

## Feature context

Agent Quality Gauntlet is a Python 3.11+ control plane used by project owners, developers, Codex, Claude Code, and CI systems to install and run deterministic quality constraints for agentic coding.

Its executable surfaces are:

- the global/source/zipapp `qg` CLI;
- the project-vendored `quality/qg.py` runtime;
- the guided terminal interface;
- the authenticated loopback web dashboard;
- generated CI, hooks, agent skills, verifier definitions, and review artifacts;
- JavaScript, TypeScript, HTML, CSS, and Python adapter packs.

Behavior shared across every surface:

- exit 0 is pass, 1 quality failure, 2 configuration/input failure, and 3 infrastructure failure;
- missing, stale, malformed, or untrustworthy evidence never becomes a pass;
- risk rules may raise but never lower the minimum required profile;
- policy, expected-output, waiver, approval, and governance changes remain separately reviewable;
- target projects receive a pinned vendored runtime and isolated checker definitions.

The top-level feature namespace is `AgentQualityGauntlet`, with subfeatures for Setup, Risk, Execution, Review, Evidence, Dashboard, SupplyChain, and Release.

Durable design and operating documents:

- `ARCHITECTURE.md`
- `IMPLEMENTATION_STATUS.md`
- `docs/CONTROL_SURFACE.md`
- `docs/OWNER_OPERATING_PLAYBOOK.md`
- `BLUEPRINT.md`

## Contract states

Files directly under `feature-spec/` have two states:

- `Product.Feature.md` is active: its requirements describe implemented, supported behavior that must remain true.
- `TODO.Product.Feature.md` is intended: its requirements describe behavior that has not shipped and do not constrain current behavior.

Dot-separated names express parent/child scope. An active child inherits normative requirements from existing active parent prefixes. A child may strengthen a requirement; weakening it requires a narrow, justified exception.

## Before changing current behavior

1. List files in `feature-spec/`.
2. Ignore unrelated TODO files.
3. Identify the most specific active feature affected.
4. Read active parents from least specific to most specific.
5. Read the target and active related specifications.
6. Identify inherited requirements and exceptions.
7. Make implementation and tests conform.
8. Report conflicts rather than editing requirements to match code.

## Before implementing intended behavior

Read the active parent chain, any active specification with the same feature name, applicable TODO parents, the target TODO file, and its related specifications. After implementation and verification, reconcile the TODO with active behavior and remove the TODO state only with human approval.
