# Acceptance mutation adapter contract

The normal acceptance command proves that the base Gherkin behavior passes. The acceptance mutation command proves that every Examples value is connected to observable behavior or an assertion.

Configure `quality/project.json`:

```json
{
  "acceptance_mutation": {
    "command": ["python3", "tests/acceptance/runner.py", "{feature_json}"],
    "timeout_seconds": 60
  }
}
```

AQG executes the command once against the base JSON IR and once for every single-cell example mutation. It also exports the path as `AQG_FEATURE_JSON`. The command must execute the **same generated acceptance entry points** against that JSON; it must not regenerate assertions from the mutated values. Exit `0` means the supplied specification passes. A nonzero test failure kills the mutation. A process failure or timeout is an infrastructure error, not a kill.

Handlers must route steps into the real application boundary, reject unsupported or ambiguous text, parse values strictly, create fresh state per scenario execution, and preserve shared state only within one scenario. Domain-valid mutations are preferred; add project-specific semantic mutators where generic string dithering is rejected before reaching business behavior.
