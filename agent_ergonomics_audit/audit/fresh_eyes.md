# Fresh-eyes verification

## Round 1: cold, project-independent use

Commands were executed from `/tmp` with no initialized project:

- bare `qg`: exit 0, human help on stdout, empty stderr;
- `qg --json`: exit 0, valid capabilities contract, empty stderr;
- `qg help onboarding refresh`: exit 0;
- `qg --baes-url`: exit 2 with exact `qg detect --base-url BASE_URL` correction;
- `qg guidance mutation testing`: initially exposed an unnecessary project-root
  dependency, then passed with exit 0 and empty stderr after commit `77d0ca6`.

## Round 2: newly initialized disposable project

A new Git repository was initialized with `qg init --mode greenfield --no-ci`.
`status --json` and `doctor --json` returned valid structured data with exit 0.
`triage --json` returned a valid schema and exact next commands with exit 2,
correctly reflecting three setup blockers rather than claiming guarded readiness.
All four commands kept diagnostics off stderr.

Both rounds were performed after application changes. No further product defect
was found in round 2. These are same-agent fresh-context checks, not independent
human approval.
