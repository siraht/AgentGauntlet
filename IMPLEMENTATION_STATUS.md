# Implementation status

Status date: 2026-07-24  
Version: 2.0.0  
Recovery source SHA-256: `8b472df584dee17bc3b72e22bff2d764983cfe47d4617ee4a4dfd8cbc37a757e`

## Recovery audit

The recovered archive contained the complete v2 Python source modules, dashboard assets, stack templates, agent guidance, and a partial CycloneDX implementation. It also contained a stale v1-facing README and unconfigured v1 root scaffold.

The following items named in the referenced conversation were absent or incomplete and have been reconstructed:

- `ARCHITECTURE.md`;
- `IMPLEMENTATION_STATUS.md`;
- `docs/CONTROL_SURFACE.md`;
- `docs/RESEARCH_REPORT_2026.md`;
- `install-aqg.sh`;
- deterministic zipapp/portable release build tooling;
- a repository `.gitignore`;
- SBOM gate registration, validation, evidence, and tests;
- `--mode auto` and explicit `--browsers` CLI behavior;
- zipapp-safe extraction of embedded runtime/templates/guides;
- a v2 README and source-repository CI.

## Implemented

- JavaScript, TypeScript, HTML, CSS, and Python detection.
- Auto, adopt, and greenfield enforcement modes.
- Four execution profiles and four deterministic risk profiles.
- Protected policy and human-review paths.
- Format, lint, type, test-integrity, unit, structure, coverage, contract, acceptance, golden, source mutation, acceptance mutation, review, secret, security, supply-chain, performance, reproducible-build, and release-readiness adapters.
- Strict Gherkin linting and acceptance example mutation.
- Review packet generation in Markdown, JSON, HTML, and SARIF.
- Fingerprinted human approval records.
- Local TUI, authenticated loopback dashboard, and portfolio registry.
- Project-vendored runtime, agent integrations, GitHub Actions, and CODEOWNERS generation.
- Deterministic CycloneDX 1.6 inventories from supported committed locks.
- Deterministic portable release builder.
- 27 Python source/acceptance tests, one JavaScript dashboard contract test, and internal
  and installed-tool conformance fixtures.

## Locally validated

- Python compilation.
- Source test suite.
- Internal AQG conformance.
- Source launcher and CLI help/version.
- Disposable-project initialization.
- Standalone zipapp initialization with a vendored runtime.
- Deterministic repeated portable builds and checksum verification.
- Package metadata and wheel/sdist builds when the standard build frontend is available.
- Live npm/PyPI tool resolution with exact protected locks.
- All ten installed-checker fault-injection fixtures.
- Playwright Chromium installation on the current Linux image.
- Lighthouse execution against the bundled dashboard (performance `1.00`, accessibility `0.95`).
- High-severity npm and Python dependency audits.

## Still environment-dependent

These cannot be certified by source tests alone:

- all supported native project runners and package-manager variants in representative real repositories;
- Playwright browser/E2E behavior on every supported CI image;
- Stryker and mutmut performance, isolation, and survivor triage at large-project scale;
- Lighthouse behavior for framework-specific start/build flows;
- GitHub branch protection, required reviews, and organization rulesets;
- license/provenance approval for every external checker.

AQG includes conformance commands for installed tools, but an organization should approve a toolchain only after running those fixtures in a clean, connected environment.

## Known design limits

- AQG supports five source surfaces today; other ecosystems require new adapters.
- Static dangerous-pattern and secret scans are triage controls, not complete security analysis.
- CycloneDX inventory does not itself discover vulnerabilities; `security_fast` performs audits.
- Local hooks are advisory. Hosting-side governance is required.
- Existing repositories need calibrated ratchets and project-specific behavior contracts; setup cannot infer product intent safely.
- Reduced human implementation review must be earned from operational evidence and is never the default for Critical work.

## Recovered-code debt

The recovered implementation does not yet earn its own High-assurance “reduced code review” mode. A full comparison with the recovered baseline reports roughly 34% aggregate Python coverage, changed-line coverage below the 90% target, and multiple functions over the default complexity/CRAP caps. The largest hotspots are CLI dispatch, policy/project validation, toolchain installation, automated review, and dashboard rendering.

AQG is therefore published in `adopt`/ratchet mode. New changes must not add debt, while the existing hotspots need focused characterization tests and incremental extraction before switching this repository to full strict enforcement. This limitation affects confidence in AQG’s implementation, not the availability of the CLI, installer, evidence model, dashboard, or supported adapters.
