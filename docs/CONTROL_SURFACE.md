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
python3 quality/qg.py check inner
python3 quality/qg.py check fast
python3 quality/qg.py check-risk --keep-going
python3 quality/qg.py review --write --sarif
python3 quality/qg.py council plan --tier pr
```

Use `inner` while editing and `fast` at coherent local checkpoints.
`check-risk` computes the required PR/deep/release profile from the protected
risk rules and current change-risk card.

## Retrospective adoption flow

Existing repositories begin with observation, not instant whole-tree
certification:

```sh
python3 quality/qg.py audit shadow --profile fast
python3 quality/qg.py baseline debt propose
python3 quality/qg.py promote status
```

The shadow command returns success only when all non-quality evidence is
usable. Its summary retains the observed result and detailed taxonomy. A debt
proposal is immutable, reviewable input; it is not an accepted baseline.

After a human reviews the complete inventory, create exact maintenance scope:

```sh
python3 quality/qg.py maintenance request \
  --change add:quality/baselines/debt.json \
  --reason "Install the reviewed retrospective debt authority"
AQG_POLICY_MAINTENANCE=1 python3 quality/qg.py baseline debt review \
  --proposal PROPOSAL_ID --reviewer HUMAN_ID --confirm-reviewed
python3 quality/qg.py promote propose --to ratchet
```

The baseline and stage change still require independent code-owner approval.
Ratchet mode reports matching inherited debt without blocking unrelated
conforming changes and rejects new, worsened, malformed, or unclassified debt.
Strict promotion additionally requires a current debt-free enforcing deep run
over the exact controls and change surface.

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

Each completed profile or standalone gate stores detailed evidence beneath its
run directory and finalizes `manifest.json`. A missing or non-verifying
manifest makes historical evidence unusable. The mutable `.aqg/work` directory
is execution scratch space, never historical authority.

## Protected policy maintenance

Ordinary builders cannot edit protected paths. A legitimate maintenance flow
declares exact operations first:

```sh
python3 quality/qg.py maintenance request \
  --change modify:quality/project.json \
  --reason "Promote reviewed self-hosting from shadow to ratchet"
```

Local hooks accept only declared path/operation pairs while the maintenance
override is active. Shell-based or broader writes remain blocked. PR, deep,
and release profiles derive the real protected diff and require an exact,
current, independent approval. Authoritative commands refuse to run while the
override is active.

## Trusted authoritative verification

Candidate CI is useful feedback but cannot be the sole grader of changes to
its own policy or checker. The hosted trusted workflow runs the protected-base
launcher, policy, project definition, tool definitions, and gate commands
against a separate candidate checkout with read-only credentials. Activate it
in two stages: first land and observe the workflow on the default branch under
the old ruleset, then add its context to required checks.

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

- separate Develop, Merge, and Release decisions from one owner-status model;
- exact-candidate advisory council quorum, dissent, and completeness;
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
