# Verify Agent Quality Gauntlet releases

AQG releases use two complementary integrity layers:

1. `SHA256SUMS` detects a corrupt, incomplete, or mismatched download set.
2. GitHub artifact attestations bind the artifact digests to the repository, workflow, source
   revision, and a short-lived Sigstore certificate issued from GitHub Actions OIDC.

A checksum copied from the same untrusted download location does not authenticate its publisher.
Run both checks for a release artifact you intend to execute.

## Verify the downloaded files

Download the complete release file set into one directory, then run:

```sh
sha256sum -c SHA256SUMS
```

The manifest covers the standalone zip application, portable archive, all three CycloneDX
inventories, and the local in-toto/SLSA reproducibility statement. The two checksum sidecars are
convenience copies for individual downloads; `SHA256SUMS` is the complete manifest.

The release should contain:

- `aqg.pyz`;
- `agent-quality-gauntlet-2.0.0-portable.zip`;
- `aqg-runtime.cdx.json`;
- `aqg-javascript-toolchain.cdx.json`;
- `aqg-python-toolchain.cdx.json`;
- `provenance.intoto.json`;
- checksum sidecars and `SHA256SUMS`.

## Verify GitHub build provenance

Use a current GitHub CLI release with the `attestation` command:

```sh
gh attestation verify aqg.pyz \
  --repo siraht/AgentGauntlet \
  --signer-workflow siraht/AgentGauntlet/.github/workflows/quality-gauntlet.yml \
  --deny-self-hosted-runners

gh attestation verify agent-quality-gauntlet-2.0.0-portable.zip \
  --repo siraht/AgentGauntlet \
  --signer-workflow siraht/AgentGauntlet/.github/workflows/quality-gauntlet.yml \
  --deny-self-hosted-runners
```

For a tagged release, add `--source-ref refs/tags/<tag>` to require that exact release ref. Add
`--source-digest <commit>` when your policy pins the source revision independently.

These checks authenticate where the bytes were built; they do not assert that the bytes are free
of vulnerabilities or that the source was reviewed.

## Verify attached SBOM claims

The zip application has separate runtime, JavaScript-checker, and Python-checker SBOM
attestations. Verify and inspect all CycloneDX predicates with:

```sh
gh attestation verify aqg.pyz \
  --repo siraht/AgentGauntlet \
  --signer-workflow siraht/AgentGauntlet/.github/workflows/quality-gauntlet.yml \
  --predicate-type https://cyclonedx.org/bom \
  --deny-self-hosted-runners \
  --format json \
  --jq '.[].verificationResult.statement.predicate'
```

Each checked-in CycloneDX 1.6 document has a deterministic content-derived UUID, a complete
inventory marker, and the protected lockfile digest used to create it. An SBOM is an inventory;
use vulnerability and license policy tooling as separate controls.

## Understand the local provenance file

`provenance.intoto.json` is a deterministic in-toto Statement using the SLSA provenance v1
predicate. It records:

- every primary output digest;
- the Git revision and repository;
- every packaged source material and digest;
- the documented portable-v1 build contract;
- whether tracked source was dirty during the build.

The file supports reproducibility review and incident analysis. It is not a signature on its own.
Its digest is included in `SHA256SUMS` and in the workflow-generated, cryptographically signed
GitHub provenance attestation.

The exact build contract is defined in [BUILD_TYPE.md](BUILD_TYPE.md).
