# Golden session tests

`scenarios.json` defines complete command sessions. Each scenario records normalized stdout, stderr, exit status, and selected filesystem effects in a committed artifact under `expected/`.

Normal verification is read-only:

```sh
python3 quality/qg.py golden run
```

Updating expected behavior is deliberately separate and policy protected:

```sh
AQG_ALLOW_GOLDEN_UPDATE=1 python3 quality/qg.py golden update
python3 quality/qg.py review --write
```

Use normalization only for values that truly vary between equivalent executions, such as timestamps, generated IDs, absolute temporary paths, and durations. Stable values, ordering, counts, messages, and public payloads must remain literal so unintended changes appear in the diff.
