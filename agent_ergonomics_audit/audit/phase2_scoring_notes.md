# Phase 2 scoring notes

All 197 inventoried surfaces were scored against rubric digest
`sha256:44e7c00b3dee6be38118f1f40719d814278cb129f9aad34572e0936104b135a4`.
The generated scorecard validates successfully with the skill's scorecard validator.

The median weighted score is 610. The capabilities and global JSON surfaces score
higher because their schemas, determinism, stdout/stderr split, and regression tests
are evidenced directly. The following dimensions remain intentionally conservative:

- intent inference: 250 on ordinary surfaces because misspelled flags and verbs do not
  yet receive a corrected command;
- self-documentation: 600 on ordinary surfaces because there is no embedded
  agent-oriented guide;
- agent ergonomics: 620 on ordinary surfaces because there is no one-call triage view;
- error pedagogy: 550 on ordinary surfaces because argparse failures do not yet include
  a nearest-command suggestion.

Parallel scorer reconciliation was unavailable under this run's orchestration
restriction. Scores therefore use a single conservative rubric application with
file-and-test evidence on every dimension and record zero synthetic spread; no claim
of independent scorer consensus is made.
