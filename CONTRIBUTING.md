# Contributing

Contributions should preserve AQG’s fail-closed status model and protected trust boundaries.

Before opening a pull request:

```sh
python3 -m compileall -q src tests scripts
PYTHONPATH=src python3 -m pytest -q
python3 scripts/build_release.py
sha256sum -c dist/SHA256SUMS
```

For gate, policy, evidence, installer, or release changes, add conformance coverage for pass, quality failure, configuration failure, and infrastructure failure as applicable. Missing or malformed evidence must never be normalized to pass.

Pull requests should explain:

- observable behavior changed and preserved;
- risk classification;
- new or changed policy/human-review files;
- validation and conformance evidence;
- compatibility and migration impact;
- rollback.

Do not include generated environments, registry credentials, local AQG evidence, browser artifacts, or dependency directories.
