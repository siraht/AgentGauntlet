# Gherkin acceptance specifications

Use Gherkin for important user or business behavior that crosses implementation boundaries.

Keep the supported grammar small:

- `Feature`
- optional `Background`
- `Scenario` and `Scenario Outline`
- `Given`, `When`, `Then`, and `And`
- `Examples` tables

Prefer a small canonical vocabulary. Step handlers must be narrow and ambiguity must fail. Scenarios must use real public application boundaries and isolated state.

Every changed feature should be parsed into canonical JSON IR, checked for accidental duplicate wording, generated into thin test entrypoints, executed normally, and—at High assurance or Critical risk—subjected to acceptance-example mutation.
