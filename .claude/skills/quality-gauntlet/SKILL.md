---
name: quality-gauntlet
description: Run and interpret the repository's deterministic quality gauntlet, create test and QA evidence, and prepare review packets.
---

# Quality Gauntlet

1. Read `QUALITY.md`, `KEYSTONE.md`, applicable `feature-spec/` files, and `quality/change-risk.json`.
2. Run `python3 quality/qg.py status` before editing.
3. Keep product behavior and tests aligned; do not weaken policy or approve expected-output changes.
4. Use `python3 quality/qg.py guidance <topic>` for test-writing instructions.
5. Read the enforcement stage from `status`. In `shadow`, run
   `python3 quality/qg.py audit shadow --profile fast` during work and
   `python3 quality/qg.py check-risk --shadow --keep-going` before completion.
   In `ratchet` or `strict`, use `check fast` and `check-risk --keep-going`.
6. Generate the review packet with `python3 quality/qg.py review --write`.
7. Report every failed, skipped, stale, or inapplicable gate explicitly.
