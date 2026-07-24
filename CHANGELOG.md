# Changelog

## 2.0.0 — 2026-07-24

- Recovered and unified the v2 control plane for JavaScript, TypeScript, HTML, CSS, and Python.
- Added auto/adopt/greenfield setup, explicit browser installation, source and portable launchers, deterministic packaging, TUI, dashboard, portfolio registry, and automated review artifacts.
- Completed and registered deterministic CycloneDX 1.6 supply-chain evidence.
- Added executable setup acceptance tests and acceptance-example mutation.
- Added source-repository CI, CODEOWNERS, security policy, contribution guidance, architecture, control-surface documentation, research synthesis, and implementation status.
- Fixed first-commit untracked-file expansion, JavaScript tool exit classification, standalone zipapp resource extraction, checker-created coverage artifacts, shell-based gate execution, and non-Node compatibility-shim selection.
- Replaced vulnerable Lighthouse CI transitive dependencies with direct current Lighthouse execution using explicitly installed Playwright Chromium.

The recovered codebase remains in ratchet mode while its inherited coverage and complexity debt is reduced. See `IMPLEMENTATION_STATUS.md`.
