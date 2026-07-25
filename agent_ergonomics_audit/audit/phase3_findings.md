# Phase 3 intent-inference findings

The pre-change runner executed 277 naive and source-aware invocations:

| Classification       | Count |
| -------------------- | ----: |
| `inferred_and_acted` |     1 |
| `useful_hint`        |     0 |
| `useless_error`      |   275 |
| `skipped`            |     1 |
| `silent_fail`        |     0 |

The one inferred invocation proves that AQG already tolerates a global `--json` flag
after a leaf command. The dominant failure is otherwise clear: argparse names the
invalid token but does not suggest the nearest valid flag or verb, nor does it provide
a corrected copy-pasteable command. Conventional guesses such as `qg test`, `qg
verify`, and `qg health` receive the same low-value response as random typos.

This becomes the highest-priority Phase 4 recommendation because it affects almost
every command and costs an agent an avoidable discovery/retry round trip.

After recommendations R-004, R-005, R-008, R-009, and the ambition pass, the
expanded 289-case corpus reports:

| Classification       | Count |
| -------------------- | ----: |
| `inferred_and_acted` |     3 |
| `useful_hint`        |   285 |
| `useless_error`      |     0 |
| `skipped`            |     1 |
| `silent_fail`        |     0 |

All 289 outcomes match their predicted class. The skipped case is the intentionally
unsafe mutating alias `qg create`; AQG does not execute it implicitly.
