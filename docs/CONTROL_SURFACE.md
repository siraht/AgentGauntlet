# Unified control surface

AQG exposes one state model through CLI, TUI, dashboard, reports, CI, and portfolio views.

## Setup flow

```sh
qg wizard /path/to/project
qg setup /path/to/project --owner @team --mode auto
qg setup /path/to/web-project --owner @team --browsers
```

`wizard` interviews the operator. `setup` is non-interactive and performs detection, initialization, optional tool installation, doctor checks, and conformance. `init` writes configuration without requiring tool installation.

```sh
qg init /path/to/project --mode adopt
qg tools install
qg tools install --browsers
qg doctor --strict-tools
qg conformance --tools
```

## Change flow

```sh
python3 quality/qg.py status
python3 quality/qg.py risk-card
python3 quality/qg.py check fast
python3 quality/qg.py check-risk --keep-going
python3 quality/qg.py review --write --sarif
```

Use `fast` while editing. `check-risk` computes the required PR/deep/release profile from the protected risk rules and current change-risk card.

## Authoring flow

```sh
python3 quality/qg.py new spec Product.Feature
python3 quality/qg.py new spec Product.FutureFeature --todo
python3 quality/qg.py new feature Product.Feature
python3 quality/qg.py new qa Product.Feature
python3 quality/qg.py guidance --list
python3 quality/qg.py guidance mutation-testing
python3 quality/qg.py guidance --search authorization
```

Generated material is a starting point. Active behavior, examples, expected output, and QA procedures remain human-review-plane artifacts.

## Evidence and approval flow

```sh
python3 quality/qg.py report
python3 quality/qg.py approval template behavior-review
python3 quality/qg.py approval validate --risk-profile high_assurance
python3 quality/qg.py golden
AQG_ALLOW_GOLDEN_UPDATE=1 python3 quality/qg.py golden --update
```

Approval fingerprints include the current review surface and evidence. Any relevant change makes a prior approval stale.

## Onboarding flow

```sh
python3 quality/qg.py onboarding show
python3 quality/qg.py onboarding next
python3 quality/qg.py onboarding refresh
```

The onboarding state reports blockers, review items, informational enhancements, and the next action. It does not mark missing product contracts or checker locks as complete.

## TUI

```sh
python3 quality/qg.py tui
```

The terminal interface guides users through status, risk, profiles, review, onboarding, evidence, and documentation. It launches the same command handlers as the CLI.

## Dashboard

```sh
python3 quality/qg.py dashboard --open
python3 quality/qg.py dashboard --allow-actions --open
python3 quality/qg.py dashboard --portfolio --open
```

The server binds to `127.0.0.1` by default. Read-only mode exposes current state. `--allow-actions` creates an in-memory token and permits profile execution from the browser. Remote binding is an explicit operator decision and should sit behind a trusted access layer.

The dashboard shows:

- current risk and required execution;
- latest and historical runs;
- gate evidence and artifacts;
- normalized findings and human decisions;
- stack/toolchain readiness;
- onboarding gaps;
- approvals, coverage, mutation, structure, and supply-chain inventory.

## Portfolio

```sh
qg portfolio add /path/to/project --tag production
qg portfolio list
qg portfolio scan
qg dashboard --portfolio --open
```

Portfolio data is local operational inventory. It does not replace each repository’s clean authoritative CI.

## Machine use

Global `--json` may appear before or after the subcommand:

```sh
python3 quality/qg.py status --json
python3 quality/qg.py review --json --no-evidence
```

Exit codes remain stable across human and machine output.

## Control-surface conformance

The source repository continuously dogfoods the public workflow in a disposable
project:

```sh
python3 scripts/dogfood_control_surfaces.py \
  --output build/aqg/control-surface-dogfood.json
```

The harness proves cold-start help and guidance, one-command setup, status,
doctor, fail-closed triage, review packets and SARIF, internal conformance, a
real pseudo-terminal TUI session, dashboard security headers, read-only action
denial, token rejection, authenticated review, and unknown-action handling. CI
retains the normalized JSON result.
