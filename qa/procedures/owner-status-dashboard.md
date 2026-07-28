# QA procedure: owner status dashboard

## Purpose and risk

Verify that a nontechnical owner sees one honest Develop, Merge, and Release
decision, can operate the dashboard with a keyboard and narrow viewport, and
cannot mistake stale or advisory evidence for permission.

## Preconditions

- Environment: local source checkout with installed AQG toolchains.
- Build/version: record the exact Git revision.
- Required permissions: loopback access; no dashboard actions required.
- Evidence: a current manifested run plus at least one deliberately stale run
  or review packet in a disposable checkout.

## Procedure

1. Run `python3 quality/qg.py status --json`.
   - Expected: `owner_status.decisions` contains separate `develop`, `merge`,
     and `release` records with a deterministic next action.
   - Expected: local evidence does not claim hosted merge or release
     authority.
2. Start `python3 quality/qg.py dashboard` and open the printed loopback URL.
   - Expected: the first main content is an owner decision, followed by the
     evidence ledger and attention queue.
   - Expected: the CLI and dashboard decision states agree.
3. Navigate every tab and interactive control using Tab, Shift+Tab, Enter,
   Space, Left Arrow, and Right Arrow only.
   - Expected: focus is visible, tab state is announced, and no function
     requires a pointer.
4. Resize the viewport to 320 CSS pixels and zoom to 200%.
   - Expected: no important decision, action, or evidence count is clipped or
     horizontally unreachable.
5. Change the candidate in a disposable checkout without rerunning evidence.
   - Expected: the prior run, review, and council result become stale; none
     remain a pass or approval.
6. Tamper with a copied run or council evidence file.
   - Expected: manifest verification fails and the dashboard describes the
     evidence as invalid or unverified.

## Cleanup

Stop the dashboard process. Remove only disposable checkout changes and
temporary browser artifacts. Do not modify authoritative evidence.

## Rollback check

Run the same status and dashboard flow against the last known safe revision.
Confirm its evidence is scoped to that revision and cannot be reused for the
new candidate.

## Result

- Executed by:
- Date:
- Build/revision:
- Pass/fail:
- Evidence:
- Follow-up:
