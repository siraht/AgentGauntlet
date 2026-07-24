# Python quality

> Test the installed package in an isolated environment, use strict pytest discovery and mypy ratchets, control side effects, and use Hypothesis and mutmut where they add distinct evidence.

## Layout and imports

Prefer a `src/` package layout and pytest `--import-mode=importlib` for new projects so tests do not accidentally import an uninstalled working-tree package. Install the project editable for development and build/install the wheel in release verification. Keep test module names unique or package test directories deliberately.

## Pytest

Use strict configuration and strict markers. Configure explicit `testpaths`. Collection must be nonzero when production code exists. Fixtures should be small, composable, and scoped no broader than required. Avoid autouse fixtures that silently change global behavior. Teardown must run even after failure.

## Types

Aim for mypy strict on new/changed modules. Existing repositories use a ratchet: type-check newly adopted modules strictly and prevent error-count growth. Do not solve errors with global `ignore_missing_imports`, file-wide ignores, or unqualified `# type: ignore`. Use an error code and explanation only for a reproduced typing limitation.

## Boundaries

Use protocols/typed interfaces for clocks, random sources, network, storage, and queues. Patch where the name is looked up, use autospec/spec-set, and prefer stateful fakes for repositories or services. Validate runtime input with explicit parsers/schemas.

## Property and mutation

Use Hypothesis for parsers, normalization, state machines, invariants, and boundary-rich domains. Do not suppress all health checks. Mutmut requires process forking and should run under WSL on Windows. Scope mutation to changed files and covered lines, but treat missing/stale coverage as failure.

## Packaging and security

Release evidence builds a wheel/sdist from a clean tree, installs into a fresh environment, runs tests against the artifact, and compares repeat builds when reproducibility is required. Audit dependencies and run Bandit/static checks as prompts, then review authentication, authorization, deserialization, path handling, subprocess, template, and SQL boundaries semantically.
