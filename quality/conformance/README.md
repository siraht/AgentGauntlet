# Quality-tool conformance fixtures

Every custom checker or adapter needs fixtures for:

- known pass;
- known quality failure;
- malformed input;
- missing input/report;
- stale artifact;
- timeout;
- parallel-worker isolation;
- deterministic repeated output;
- unsupported construct;
- explicit exclusion or waiver.

A quality tool is production code. Its conformance suite belongs in the fast or pull-request profile, and policy changes must add or update these fixtures.
