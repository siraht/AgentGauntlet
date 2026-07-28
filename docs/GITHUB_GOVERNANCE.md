# GitHub governance

The public repository treats GitHub as the authoritative governance plane. Local hooks
remain fast feedback only.

## Default-branch rules

The active desired ruleset is versioned in
`quality/github/main-ruleset.json`. GitHub assigned it ID `19719465`. It protects the
default branch by:

- rejecting deletion and force pushes;
- requiring linear history and pull requests;
- requiring one independent approval, approval of the last reviewable push, dismissal
  of stale approvals, and resolution of review conversations;
- requiring every source, cross-platform contract, live-project, browser, release-build,
  candidate `policy-evidence`, and base-controlled `trusted-policy-evidence` check from
  the GitHub Actions app;
- requiring the pull request to be current with the default branch.

There are no bypass actors. Because this is currently a personal repository with one
maintainer, the owner cannot approve their own pull request. A second trusted maintainer
with write access must review before merge. `CODEOWNERS` still routes policy-plane changes
to the declared owner, but code-owner approval is not enabled until ownership can be
separated from authorship without deadlocking every change.

Apply the versioned declaration with an administration-capable GitHub CLI session:

```sh
gh api \
  --method POST \
  repos/siraht/AgentGauntlet/rulesets \
  --input quality/github/main-ruleset.json
```

For later edits, find the ruleset ID and use `PUT` against that ID with the same input.
Never create a second overlapping ruleset as an update mechanism.

## Repository controls

The repository is configured to delete merged branches, allow auto-merge, disable merge
commits, and permit only squash or rebase merges. Vulnerability alerts, automated security
fixes, secret scanning, and push protection are enabled. Dependabot monitors GitHub
Actions plus both protected checker toolchains.

## Verification

Inspect the effective rules rather than trusting configuration intent:

```sh
gh api repos/siraht/AgentGauntlet/rulesets
gh api repos/siraht/AgentGauntlet/rules/branches/main
gh api repos/siraht/AgentGauntlet
```

The current pull request is deliberately kept unmergeable until all required checks pass
and an independent human approves it. Agent verification is additional evidence, not a
substitute for that approval.

## Immutable grader activation

The ordinary `policy-evidence` job remains useful candidate integration evidence, but it
checks out and invokes candidate files and therefore is not an immutable grading
authority. The separate `trusted-policy-evidence.yml` workflow uses
`pull_request_target`, read-only repository permission, and two credential-free
checkouts:

- `trusted/` is the exact protected base SHA and supplies the AQG runtime, policy,
  project configuration, checker locks, checker configuration, and gate launcher;
- `subject/` is the exact untrusted head SHA and supplies only the code, tests, feature
  intent, risk card, and other candidate subject matter being measured.

Trusted mode ignores the candidate's `quality/qg.py`, policy, project configuration,
checker binaries, and checker configuration. Every gate subprocess is re-routed through
the base launcher, and the uploaded evidence records the base and candidate identities
plus hashes for the complete base runtime. Candidate tests still execute because they
are the object under test, so the workflow exposes no secrets, persists no checkout
credentials, and has no write permission.

Activation is deliberately two-stage to avoid a branch-protection deadlock:

1. Merge the trusted workflow while the existing required checks and independent review
   still govern the change.
2. Observe the workflow running from the default branch, then apply the versioned
   ruleset that requires `trusted-policy-evidence`.
3. Keep candidate `policy-evidence` during the shadow period. It may be removed from the
   required set only after the trusted context is stable and the versioned governance
   declaration is updated through policy maintenance.

GitHub always loads a `pull_request_target` workflow from the protected base. Therefore
the pull request that first introduces this file cannot certify itself with the new
context. The versioned ruleset already describes the intended post-merge state, but the
live ruleset must not require that context until step 2.
