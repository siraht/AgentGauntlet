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
- requiring every source, cross-platform contract, live-project, browser, and release
  check from the GitHub Actions app;
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
