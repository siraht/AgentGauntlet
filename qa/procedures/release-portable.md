# QA procedure: portable AQG release

## Identity

- Rule: `QA-AQG-PORTABLE-001`
- Feature: `AgentQualityGauntlet`
- Risk: High assurance
- Owner: AQG release owner

## Applicability

Run for every public AQG source or portable release.

## Preconditions

- Clean checkout at the candidate revision.
- Python 3.11+.
- No `AQG_POLICY_MAINTENANCE` or `AQG_ALLOW_GOLDEN_UPDATE` override.
- A disposable target directory.

## Procedure

1. Run the source tests and internal conformance.
2. Build the portable distribution twice into separate directories.
3. Compare both `aqg.pyz` files and both portable ZIP files byte-for-byte.
4. Verify every checksum with `sha256sum -c`.
5. Run `aqg.pyz --version` and `aqg.pyz --help`.
6. From the extracted portable ZIP, run `install-aqg.sh` against the disposable target with `--no-install --no-ci`.
7. Confirm the target contains `quality/qg.py`, `quality/_aqg/`, `quality/policy.toml`, `quality/project.json`, `quality/change-risk.json`, and embedded guidance.
8. Run the target’s `python3 quality/qg.py doctor`.
9. Inspect the source archive/portable ZIP for credentials, local evidence, caches, browser output, dependency directories, and the recovered input archive.

## Pass conditions

- Every automated test and internal conformance case passes.
- Repeated artifacts are byte-identical.
- Checksums verify.
- The standalone zipapp initializes a working vendored runtime.
- Doctor reports no configuration error; project-specific onboarding warnings are explicit.
- No local, secret, cache, or dependency material appears in the release.

## Failure and recovery

Any mismatch, checksum failure, missing runtime resource, configuration error, or unwanted packaged file fails this procedure. Do not publish. Correct the source/build process, delete the candidate artifacts, rebuild from a clean checkout, and repeat every step.
