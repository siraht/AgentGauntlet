# Acceptance tests and Gherkin

> Write a small, strict vocabulary of observable behavior, connect every example value to the real application, and use acceptance mutation to prove the examples matter.

## Scenario rules

A scenario describes one user or external-system outcome. Use domain language, not selectors, class names, database tables, or internal method calls. Keep `Given` to relevant state, `When` to one meaningful action, and `Then` to observable outcome and forbidden side effects.

Use Scenario Outlines when each Examples row represents a materially distinct partition or boundary. Every column must be consumed by a step handler. Add a short comment or scenario name explaining why each row exists.

Required categories for important behavior:

- normal success;
- boundary and exact-limit cases;
- invalid input and safe error;
- unauthenticated/unauthorized/ownership boundary;
- retry/duplicate/idempotency;
- dependency failure and recovery;
- persistence or external side effect;
- rollback/compensation when stateful.

## Step vocabulary

Prefer stable phrases such as “the customer has an active subscription” and “the request is rejected with code `<code>`.” One phrase should have one semantic meaning. Narrow regex/expression handlers may capture placeholder names, but ambiguous matches and unsupported steps must fail.

Generated entry points must be deterministic and thin. They load canonical IR, create fresh scenario state, prepend background, execute in order, and delegate to project handlers. Handlers must call the real application boundary, not duplicate business logic in the test adapter.

## Review

Humans review scenarios because they are executable product claims. Review for missing failures, weak `Then` steps, implementation language, excessive background, coupled scenarios, and examples that differ without changing expected behavior.

## Acceptance mutation

Mutate one valid example cell at a time. Record where the mutant died: parse/conversion, setup, application behavior, or assertion. A kill during invalid conversion proves input rejection, not business connectivity. High-value domain-valid mutants should reach the application and be killed by a semantic assertion.
