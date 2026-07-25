# Regression alerts

Pass 2 introduced no weighted-score regression, no per-dimension drop greater
than 25 points, and no hard stop. All 197 surfaces shared with pass 1 improved;
12 valid surfaces were added. Eight false verb records emitted by the external
inventory parser were excluded only after their recorded `--help` probes proved
they were invalid commands with exit 2.
