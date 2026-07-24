# Gate adapter contract

The orchestrator runs repository-native commands; adapters translate native tool behavior into a stable contract.

## Required behavior

An adapter must:

1. delete or isolate stale artifacts before measuring;
2. run from the repository root;
3. use deterministic ordering;
4. print useful diagnostics;
5. write machine-readable evidence when practical;
6. return:
   - `0` for pass,
   - `1` for a quality finding,
   - `2` for configuration or usage error,
   - `3` for infrastructure failure;
7. identify its tool and version;
8. avoid network access unless the gate explicitly requires it;
9. fail when expected inputs or reports are missing;
10. have conformance fixtures.

An adapter must not create a passing cache/baseline/manifest without executing the check that the cache claims to represent. Cache reuse keys must cover every behavior-relevant input, and required CI must reject stale, partial, or provenance-free evidence.

## Recommended report

Write a JSON report conforming to `quality/schemas/gate-report.schema.json`. Native stdout/stderr is also captured by `qg.py`.

## Adapter selection

Prefer a maintained native tool over reimplementing a parser, compiler, coverage mapper, or mutation engine. Write a small deterministic wrapper when the native output or exit codes do not meet this contract.

Do not call a package or build alias that a normal builder can redefine unless the alias definition and every quality-sensitive configuration file it loads are protected by the policy plane.
