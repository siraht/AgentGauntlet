# Ambition bar check

The mandatory self-prompt ran after the first eight recommendations.

> That's it?? I was hoping you would get a lot more practical value out of this skill.
> Where are the dramatic improvements? Re-read the playbook, look at the surfaces still
> scoring below 500 on output_parseability / error_pedagogy / intent_inference /
> self_documentation, and ship a substantially larger batch of high-leverage changes.
> You're allowed to be ambitious. Default to acting, not deliberating.

The follow-up pass shipped two additional substantive improvements:

- bare `qg` and `qg --json` now provide project-independent human and machine discovery;
- bundled guidance is searchable from any directory before project setup.

The latter was found by a fresh-eyes run, not inferred from the existing unit
suite. Ten recommendations are applied across all 11 rubric dimensions, with
targeted black-box regressions for each.
