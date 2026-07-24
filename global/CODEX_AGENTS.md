# Global Codex quality default

For any repository containing `quality/policy.toml`, read the repository's `AGENTS.md`, `QUALITY.md`, `KEYSTONE.md`, applicable `feature-spec/` files, and the `quality-gauntlet` skill before implementation. Create or update the repository change-risk card, run `python3 quality/qg.py risk-card`, and use `python3 quality/qg.py check-risk` before claiming completion.

Do not modify a repository's protected quality plane during ordinary implementation. Policy installation or maintenance must be an explicit user task with separate review. Treat missing, stale, skipped, crashed, or unconfigured checks as unresolved rather than passing.

When a repository does not contain the gauntlet, do not silently install it during feature work. Tell the user the repository is not onboarded and use its existing instructions and CI.
