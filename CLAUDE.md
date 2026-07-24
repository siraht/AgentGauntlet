# Claude Code guidance

Follow `AGENTS.md` and `QUALITY.md`. Read `KEYSTONE.md` plus the applicable active and TODO files under `feature-spec/` before changing behavior.

Use the `quality-gauntlet` skill for implementation work. The protected policy plane may change only in an explicitly authorized policy-maintenance task. For High assurance and Critical changes, delegate final verification to the read-only `quality-verifier` subagent.
