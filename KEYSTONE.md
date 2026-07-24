# Product context and feature contracts

This project keeps durable product intent beside the code.

## Feature context

Replace this section during bootstrap with:

- what the product does and who uses it;
- its distinct applications, services, commands, libraries, or runtimes;
- behavior shared across those surfaces;
- the natural top-level feature namespaces;
- links to durable architecture and operational documents.

Do not invent context when existing sources conflict. Surface the conflict for human resolution.

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
