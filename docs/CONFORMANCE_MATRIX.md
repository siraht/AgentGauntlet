# Representative project conformance

AQG's internal fault-injection suite proves checker exit semantics. This matrix adds a
different proof: the generated configuration is installed into disposable, realistic
projects and its native collection, unit, structure, coverage, browser, and accessibility
commands must all succeed.

## Contract matrix

Every pull request generates command contracts on Linux, macOS, and Windows with Python
3.11 and 3.13. The contract suite covers npm, pnpm, Yarn, and Bun plus Vitest, Jest, Mocha,
AVA, Node's native test runner, pytest, and tox. It does not install application packages,
so it is fast and deterministic across operating systems.

## Live matrix

The Linux live job uses the hash-locked AQG toolchains and currently exercises:

| Case            | Package runner | Required gates                              |
| --------------- | -------------- | ------------------------------------------- |
| `npm-jest`      | npm / Jest     | collection, unit, structure, fresh coverage |
| `pnpm-mocha`    | pnpm / Mocha   | collection, unit, structure, fresh coverage |
| `yarn-ava`      | Yarn / AVA     | collection, unit, structure, fresh coverage |
| `npm-node`      | npm / Node     | collection, unit, structure, fresh coverage |
| `python-pytest` | pip / pytest   | collection, unit, structure, fresh coverage |
| `python-tox`    | pip / tox      | collection, unit, structure, fresh coverage |

An additional local `bun-node` case proves Bun command generation and execution. The
browser job installs protected Chromium and runs the generated Playwright smoke journey
with axe-core against a static HTML/CSS project on an isolated free port.

Run the default live cases:

```sh
PYTHONPATH=src .aqg/venv/bin/python scripts/project_matrix.py \
  --output .aqg/project-matrix.json
```

Run the optional cases:

```sh
PYTHONPATH=src .aqg/venv/bin/python scripts/project_matrix.py \
  --case bun-node \
  --case browser-static \
  --output .aqg/project-matrix-optional.json
```

The report is normalized JSON. Fixture workspaces and native runner output are temporary;
failed cases can be retained with `--keep-workspace` for diagnosis.
