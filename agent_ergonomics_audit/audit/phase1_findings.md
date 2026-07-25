# Phase 1 surface inventory findings

The recursive public-help walk now records 197 command and flag surfaces across 45
public verb paths. The authoritative implementation is
`src/aqg/cli.py`; the generated runtime evidence is in `surface_inventory.jsonl`.

Material findings:

1. The original argparse output had no explicit `commands` section, so generic CLI
   discovery tools saw only global flags.
2. Several long, comma-heavy descriptions were misclassified as verbs by a common
   help walker.
3. Nested verbs had no descriptions or stable command section.
4. Internal adapter and hook entry points appeared as the literal string
   `==SUPPRESS==` instead of being hidden.
5. The CLI had no self-describing machine contract for exit codes, environment
   controls, or JSON failure shape.

The capabilities/help commit corrects those defects. Internal commands remain
executable for the managed runtime but are intentionally absent from public discovery.
