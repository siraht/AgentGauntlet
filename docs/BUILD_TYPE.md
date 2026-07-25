# Agent Quality Gauntlet release build type

This document defines the reproducible build contract identified by the SLSA provenance
`buildType` URI in Agent Quality Gauntlet release artifacts.

## Portable v1

The portable-v1 build produces the dependency-free AQG Python zip application, the portable
installer archive, and complete CycloneDX inventories for the runtime and protected checker
toolchains.

### External parameters

- `version`: the PEP 621 project version read from `pyproject.toml`;
- `archive_timestamp`: the normalized ZIP timestamp, currently
  `1980-01-01T00:00:00Z`;
- `compression`: the deterministic archive compression contract, currently `deflate-9`.

### Internal parameters

- `sourceDirty`: whether tracked source files differed from the recorded Git revision while
  the local statement was generated.

### Invocation

From the repository root, run:

```sh
python3 scripts/build_release.py --output dist
```

The command requires Python 3.11 or newer and no third-party runtime dependencies. It derives
the JavaScript and Python checker inventories from the committed protected lockfiles. A missing,
unparseable, or incomplete lock fails the build.

### Outputs and verification

The builder emits:

- `aqg.pyz`;
- `agent-quality-gauntlet-<version>-portable.zip`;
- runtime, JavaScript checker, and Python checker CycloneDX 1.6 JSON documents;
- `provenance.intoto.json`;
- checksum sidecars and `SHA256SUMS`.

Re-running the command from the same source and environment contract must produce identical
bytes. `SHA256SUMS` binds every primary artifact, SBOM, and provenance statement. The CI release
job rebuilds twice, compares the complete output directories, verifies the checksum manifest,
and uses GitHub's short-lived OIDC identity to create externally verifiable attestations.
