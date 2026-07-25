# Agent ergonomics audit handoff

The full CLI audit is complete for the current v2 beta control surface.

- 209 valid command and flag surfaces inventoried and scored.
- 10 of 10 recommendations implemented.
- 10 focused black-box regression tests pass.
- 289 intent probes match their expected outcomes: 285 useful corrections,
  three safe read-only inferences, and one intentionally skipped mutating alias.
- Median weighted score improved from 610 to 843 with no regression.
- Two fresh-eyes rounds completed; the first found and drove the rootless
  guidance fix.
- Strict artifact validation passes.

Future passes should regenerate inventory from `qg capabilities --json` rather
than parse wrapped help prose, then repeat the intent corpus and score diff.
