---
name: quality-gauntlet
description: Use for any implementation, bug fix, refactor, test change, migration, or release work in a repository that contains quality/policy.toml. Do not use it to modify the quality policy unless the user explicitly requests policy maintenance.
---

# Quality Gauntlet workflow

1. Read `AGENTS.md`, `QUALITY.md`, `KEYSTONE.md`, and applicable `feature-spec/` files.
2. Run `python3 quality/qg.py doctor` and the existing fast profile before editing.
3. Create or update `quality/change-risk.json`, then run `python3 quality/qg.py risk-card`; select a profile at or above its deterministic minimum.
4. State observable behavior changes and preserved behavior.
5. Draft required feature, Gherkin, golden, contract, and QA evidence. Obtain human approval before High assurance implementation.
6. Implement in small slices and run `python3 quality/qg.py check fast` frequently.
7. Run `python3 quality/qg.py check-risk` to execute the profile required by the risk card.
8. Treat survivors, skips, stale/missing reports, and tool crashes as unresolved.
9. Do not alter the protected policy plane during normal work.
10. For High assurance or Critical work, delegate final verification to the read-only quality verifier.
11. Report changed human-review-plane files and provide a plain-language evidence summary.
