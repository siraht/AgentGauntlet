# Agent Quality Gauntlet

Agent Quality Gauntlet (AQG) is a constraint-first control plane for agentic coding. It installs a protected quality policy, stack-native checks, evidence storage, automated diff review, a guided TUI, and a local web dashboard into JavaScript, TypeScript, HTML, CSS, and Python projects.

The design goal is not “more tests.” It is a set of independent, fail-closed oracles that make it difficult for the same coding agent to change the implementation, weaken the rubric, and certify its own result.

## Quick start

AQG requires Python 3.11 or newer.

From a source checkout:

```sh
./qg setup /path/to/project \
  --owner @your-org/quality \
  --mode auto
```

Add `--browsers` when the project needs Playwright browser checks installed immediately. Without that flag, browser binaries are not downloaded.

From an extracted portable release:

```sh
./install-aqg.sh /path/to/project \
  --owner @your-org/quality \
  --mode auto \
  --browsers
```

To install the global `qg` command instead:

```sh
./install.sh
qg setup /path/to/project --owner @your-org/quality
```

`--mode auto` selects strict full-tree enforcement for a new Git repository without
history. Existing repositories start in non-blocking shadow mode so AQG can measure
inherited debt before any result becomes authoritative. Use `--mode greenfield` or
`--mode adopt` to override that choice.

## Daily control surface

The protected project-local command is authoritative after setup. `./aqg` is the
short form; `python3 quality/qg.py` is the portable fallback:

```sh
./aqg status
./aqg doctor
./aqg check fast

python3 quality/qg.py status
python3 quality/qg.py doctor
python3 quality/qg.py risk-card
python3 quality/qg.py check fast
python3 quality/qg.py check-risk --keep-going
python3 quality/qg.py review --write --sarif
python3 quality/qg.py council plan --tier pr
python3 quality/qg.py tui
python3 quality/qg.py dashboard --open
```

The CLI, TUI, dashboard, Markdown review packet, SARIF, JSON evidence, and SQLite run history use the same project and policy model.

## Retrospective adoption

Existing repositories move through explicit, monotonic stages:

```sh
# 1. Measure everything without blocking ordinary development.
./aqg audit shadow --profile fast

# 2. Propose a debt baseline from a manifested shadow run.
./aqg baseline debt propose --run-id RUN_ID

# 3. A human policy owner reviews the raw findings and confirms the proposal.
./aqg baseline debt review \
  --proposal PROPOSAL_ID \
  --reviewer @your-org/quality \
  --confirm-reviewed

# 4. Propose the protected policy change that activates no-regression ratcheting.
./aqg promote propose --to ratchet
```

Shadow reports classify measured failures, missing evidence, configuration errors,
infrastructure errors, and unknown product intent separately. A reviewed ratchet allows
inherited debt to remain visible while blocking new debt, worsened debt, and changed code
that misses current policy. Strict promotion is available only after a manifested
ratchet-stage deep run proves the governed tree is debt-free and all required controls
are complete.

## What setup installs

AQG detects the repository and writes:

- `quality/policy.toml`: protected gates, profiles, risk escalation, and command guards;
- `quality/project.json`: detected stacks, applicability, paths, thresholds, and enforcement mode;
- `quality/qg.py` and `quality/_aqg/`: a project-vendored runtime;
- isolated JavaScript/web and Python quality-tool definitions;
- a change-risk card, onboarding state, guidance library, and evidence directories;
- Codex and Claude Code working agreements, hooks, skills, and verifier definitions;
- GitHub Actions and CODEOWNERS governance files;
- feature-specification, Gherkin, golden-session, approval, and QA templates.

The source repository itself uses the source runtime; installed target projects receive a vendored runtime so their checks do not depend on a mutable global AQG installation.

## Supported adapters

| Surface                   | Included controls                                                                                                                                                       |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| JavaScript and TypeScript | Prettier, ESLint, `tsc`, Vitest/Jest/Mocha/AVA/Node runner integration, Istanbul/c8 coverage, structural metrics, Stryker, fast-check guidance, dependency audit        |
| HTML and CSS              | HTML-Validate, Stylelint, Playwright, axe-core, Lighthouse budgets, browser artifacts, manual QA templates                                                              |
| Python                    | Ruff, mypy, pytest/tox/custom runners, coverage.py, Radon/Xenon, mutmut, Hypothesis guidance, Bandit, pip-audit, reproducible package checks                            |
| Cross-stack               | strict test discovery, Gherkin lint and acceptance mutation, goldens, secret scanning, diff review, approvals, release readiness, deterministic CycloneDX 1.6 inventory |

Tool versions are resolved into protected project-local lockfiles. Missing tools, reports, locks, or discoverable tests never become a pass.

## Profiles and status codes

Profiles are cumulative:

| Profile   | Intended use                                                               |
| --------- | -------------------------------------------------------------------------- |
| `fast`    | tight implementation loop                                                  |
| `pr`      | routine production pull requests                                           |
| `deep`    | High-assurance changes, mutation, SBOM, security, and broader behavior     |
| `release` | Critical/release checks, reproducibility, approvals, and release readiness |

Every gate uses four outcomes:

| Exit | Meaning                                                       |
| ---: | ------------------------------------------------------------- |
|  `0` | measurement ran and passed                                    |
|  `1` | measurement ran and found a quality defect                    |
|  `2` | policy, configuration, or input is invalid                    |
|  `3` | checker, environment, timeout, or trustworthy evidence failed |

## Automated review

`qg review` classifies the actual Git diff. It detects policy-plane changes, weakened tests, new skips/focus markers, broad suppressions, golden and schema changes, migrations, authorization and dependency changes, likely secrets, dangerous execution primitives, under-classified risk, missing current evidence, and stale human approvals.

It writes:

- `.aqg/review/review.md`;
- `.aqg/review/review.json`;
- `.aqg/review/review.sarif`;
- a normalized finding set used by the dashboard and release gate.

AQG routes decisions; it does not let a builder auto-approve policies, goldens, waivers, or release evidence.

For additional independent technical perspectives, `qg council` creates an
exact-candidate bundle and orchestrates isolated Grok/OpenCode reviewers. Its
validated ballots, dissent, quorum, tool provenance, and conclusion are
immutable and always advisory. See
[docs/AGENT_REVIEW_COUNCIL.md](docs/AGENT_REVIEW_COUNCIL.md).

## Build a portable release

```sh
python3 scripts/build_release.py
sha256sum -c dist/SHA256SUMS
python3 dist/aqg.pyz --version
```

The builder fixes archive timestamps, path order, file modes, and compression settings. It produces:

- `dist/aqg.pyz`;
- `dist/agent-quality-gauntlet-2.0.0-portable.zip`;
- deterministic runtime, JavaScript-checker, and Python-checker CycloneDX 1.6 inventories;
- an in-toto/SLSA reproducibility statement with source-material digests;
- checksum sidecars and `dist/SHA256SUMS`.

The release workflow independently rebuilds the complete output set, verifies every checksum, and
uses GitHub Actions OIDC to create keyless Sigstore provenance and SBOM attestations. Follow
[docs/RELEASE_VERIFICATION.md](docs/RELEASE_VERIFICATION.md) before executing a published
artifact.

## Repository map

```text
src/aqg/                         v2 control-plane implementation
src/aqg/templates/               installed stack and governance templates
src/aqg/guides/                  embedded agent test/QA playbooks
src/aqg/static/                  local dashboard application
tests/                           source-level test suite
scripts/build_release.py         deterministic portable builder
ARCHITECTURE.md                  planes, trust boundaries, and data flow
IMPLEMENTATION_STATUS.md         recovered/validated/missing status
docs/CONTROL_SURFACE.md          CLI, TUI, and dashboard workflows
docs/PROJECT_STATUS.md           plain-language current capabilities and limits
docs/AGENT_REVIEW_COUNCIL.md     multi-model advisory review workflow
docs/RELEASE_VERIFICATION.md     checksum, provenance, and SBOM verification
docs/RESEARCH_REPORT_2026.md     research-to-control synthesis
BLUEPRINT.md                     full design and adoption model
docs/SOURCE_SYNTHESIS.md         source-by-source mechanism analysis
```

## Trust boundaries

Local hooks are fast feedback, not the final security boundary. Authoritative enforcement requires clean CI, protected branches, required checks, CODEOWNERS, and separate release authority. Reduced human code review is earned gradually for routine work; Critical changes retain independent human code and behavior review.

See [ARCHITECTURE.md](ARCHITECTURE.md), [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md), and [docs/OWNER_OPERATING_PLAYBOOK.md](docs/OWNER_OPERATING_PLAYBOOK.md) before organization-wide rollout.

## License

Apache-2.0. External tools are invoked through adapters and keep their own licenses; verify current provenance and licensing before organization-wide approval.
