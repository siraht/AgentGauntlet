# Human review guide

You can operate this system without reviewing implementation code. Review the artifacts that define behavior and risk.

## Before implementation

Approve or correct:

- the plain-language change summary;
- the selected risk profile;
- whether production scope, reversibility, blast radius, or sensitive risk factors force a stricter minimum profile;
- what users should observe;
- important behavior that must not change;
- data, permission, money, privacy, migration, and rollback implications;
- Gherkin examples for valid, invalid, boundary, retry, and recovery cases;
- the QA procedure for High assurance or Critical work.

## Before merge or release

Check the evidence summary:

- Every required gate ran.
- The selected risk profile was not below the deterministic minimum.
- No required gate is skipped.
- Tool crashes and missing reports are called infrastructure errors, not passes.
- Mutation survivors are either fixed or narrowly explained.
- Changed tests were not weakened without an explicit product decision.
- Golden diffs show only intended behavior.
- Waivers have owners and expiration dates.
- The rollback plan is concrete.
- Manual QA was executed when required.

## Questions to ask the agent

- Show me the behavior before and after in plain language.
- Which invalid and boundary cases did the acceptance examples cover?
- What mutation survived, and what real fault could it represent?
- Which test expectations became weaker?
- Which evidence came from a clean run rather than a cache?
- What could cause data loss or unauthorized access?
- How would we know the release is failing?
- Show me the exact rollback procedure.
