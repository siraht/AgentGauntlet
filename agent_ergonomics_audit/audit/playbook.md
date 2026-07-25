# Agent ergonomics apply playbook

The ranked work follows the observed corpus, not aesthetics:

1. Finish nearest-token and conventional-verb error teaching (`R-004`, `R-005`).
2. Add the one-call read-only triage response (`R-007`).
3. Embed an agent guide (`R-006`).
4. Accept the conventional `help COMMAND` ordering (`R-008`).
5. Re-run the complete intent corpus, public control-surface tests, determinism checks,
   and the repository gauntlet.

Already applied foundations (`R-001` through `R-003`) establish a stable JSON failure
envelope, machine-readable capabilities, deterministic help, recursive discoverability,
and regression tests. The remaining work must preserve all command semantics and exit
codes. In particular, a guessed alias may produce a precise suggestion but must not
silently execute a mutating command.

## Success measures

- zero silent failures;
- every close typo receives a deterministic valid correction;
- conventional top-level guesses receive exact safe command suggestions;
- `triage --json` replaces at least four orientation round trips;
- `robot-docs guide` is sufficient for a cold agent to run setup and review safely;
- capabilities, triage, and error output are byte-stable for a fixed repository state;
- no changed function exceeds Standard structural limits.
