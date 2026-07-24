# Agent working agreement

This repository uses the Agent Quality Gauntlet.

Before changing code:

1. Read `QUALITY.md`, `KEYSTONE.md`, and the applicable files in `feature-spec/`.
2. Run `python3 quality/qg.py doctor` and the existing fast profile.
3. Create or update the plain-language change-risk card.
   Store it at `quality/change-risk.json` unless repository policy specifies another path, then run `python3 quality/qg.py risk-card`.
4. Resolve the effective active feature requirements and relevant TODO intent.
5. State the behavior being changed and what must remain unchanged.

During ordinary work:

- Do not edit the protected policy plane listed in `QUALITY.md`.
- Keep implementation slices small and run `python3 quality/qg.py check fast` frequently.
- Write meaningful unit, property, contract, acceptance, and QA evidence required by the risk profile.
- Do not weaken tests, lower thresholds, add skips, approve goldens, or create waivers merely to obtain a green result.
- Treat missing/stale evidence and tool crashes as errors, not passes.
- Use public application boundaries for acceptance handlers.
- Report contradictions instead of silently changing product requirements.

Before completion:

1. Run `python3 quality/qg.py check-risk`; do not manually downgrade the profile selected by the card.
2. Run mutation for changed logic when configured.
3. Invoke the read-only quality verifier for High assurance or Critical work.
4. List changed human-review-plane files.
5. Summarize gates, survivors, waivers, skips, infrastructure errors, manual QA, and rollback status.
6. Do not claim completion while a required result is unknown.

Use the repository skill `quality-gauntlet` for the full workflow.
