# Global Claude Code quality default

When a repository contains `quality/policy.toml`, follow its `CLAUDE.md`, `AGENTS.md`, `QUALITY.md`, `KEYSTONE.md`, applicable feature specifications, and the `quality-gauntlet` skill. Validate `quality/change-risk.json` with `python3 quality/qg.py risk-card` and run `python3 quality/qg.py check-risk` before completion.

Do not change the protected quality plane during ordinary implementation. A missing report, stale cache, skip, tool crash, or configuration placeholder is unresolved evidence, not a pass. Never enable policy-maintenance or golden-update overrides to complete product work.

Do not silently install the system into an unonboarded repository during feature work; installation is a separate user-authorized policy-maintenance task.
