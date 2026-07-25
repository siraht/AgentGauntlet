# Agent execution transcript

Representative cold-agent recovery sequence:

1. Invoke `qg --json` without a project.
2. Read contract version `1.0`, 51 command records, exit meanings, output
   channels, and environment controls from stdout.
3. Search `qg guidance mutation testing --json` from the same directory.
4. Use `qg help check --json` for exact arguments without running a gate.
5. Mistype `qg --baes-url`; receive exit 2 and the exact correction
   `qg detect --base-url BASE_URL` on stderr.
6. Initialize a disposable project, then run `qg triage --json`.
7. Read three setup blockers and exact next commands; preserve exit 2 until
   guarded readiness is actually achieved.

This path requires no repository documentation, prompt-specific command memory,
interactive terminal, or error-message scraping. It never auto-executes an
ambiguous or mutating guess.
