# Architecture

Agent Quality Gauntlet separates authority so an implementation agent cannot silently redefine “correct.”

## Five planes

1. **Intent:** `KEYSTONE.md`, active/TODO feature specifications, Gherkin, public contracts, and QA procedures define observable behavior.
2. **Policy:** `quality/policy.toml`, `quality/project.json`, tool locks, gate adapters, thresholds, exclusions, baselines, hooks, CI, and CODEOWNERS define the rubric.
3. **Implementation:** product source and ordinary executable tests are the agent’s normal work area.
4. **Evidence:** normalized gate reports, review findings, coverage, mutations, SBOMs, artifacts, and run history record what actually ran.
5. **Governance:** clean CI, protected branches, code owners, human approvals, verifier roles, staged release, and rollback prevent self-certification.

Intent and policy are separate because a correct implementation of the wrong behavior is still wrong. Policy and evidence are separate because a configured checker is not proof that it ran successfully.

## Runtime model

The distributable `aqg.pyz` is a dependency-free Python 3.11+ control plane. During setup it copies its package resources into `quality/_aqg/` and creates `quality/qg.py`. Projects therefore pin the runtime they review. The AQG source repository uses `src/aqg/` directly to avoid maintaining a duplicate copy.

Stack tools are isolated:

- JavaScript/web checkers live under `quality/tools/js/` with a protected `package-lock.json`.
- Python checkers execute from `.aqg/venv/` and are installed from `quality/tools/python/requirements.lock.txt`.
- Application dependency installation follows the project’s declared package manager.
- Browser binaries are installed only with `--browsers` or by generated CI when browser acceptance applies.

## Control flow

```text
user request
  -> change-risk card
  -> deterministic minimum risk profile
  -> execution profile
  -> ordered gates
  -> normalized evidence and artifacts
  -> automated review packet
  -> required human/verifier approvals
  -> merge or release decision
```

`fast`, `pr`, `deep`, and `release` are execution profiles. `experiment`, `standard`, `high_assurance`, and `critical` are risk profiles. The risk resolver maps the latter to the former; a user may increase but not reduce the deterministic minimum.

## Gate contract

Each gate:

1. resolves applicability from protected project configuration;
2. removes or isolates stale work paths;
3. executes with a bounded timeout;
4. normalizes tool-specific results;
5. requires expected reports and checks provenance/freshness where applicable;
6. records commands, status, duration, stdout/stderr, metrics, findings, and artifacts;
7. returns 0 pass, 1 quality failure, 2 configuration failure, or 3 infrastructure failure.

Not-applicable is explicit and reasoned. It is not a silent skip.

## Evidence storage

`.aqg/runs/<run-id>/` contains run metadata and gate evidence. `.aqg/work/` contains current tool artifacts. `.aqg/review/` contains human-readable, JSON, HTML, and SARIF review material. The SQLite history and dashboard are derived from the same normalized records.

Evidence is revision-bound. Review approvals also include change and evidence fingerprints, so later source, test, risk, or policy changes invalidate them.

## Review architecture

The review engine examines Git paths and diff content. It classifies:

- policy and governance edits;
- production changes without changed executable evidence;
- assertion weakening, skips, focus markers, suppressions, and snapshot updates;
- public API, schema, migration, auth, billing, privacy, dependency, and deployment changes;
- dangerous primitives, likely secrets, generated code, and boundary drift;
- current evidence and approval completeness.

It produces findings, not implementation approval. High-assurance verification is read-only and independent; Critical work additionally requires human code review.

## Acceptance, mutation, and goldens

Strict Gherkin parsing rejects unsupported syntax. Examples are checked for missing and disconnected fields. Acceptance mutation changes example values and classifies test versus infrastructure outcomes.

Source mutation begins from a passing baseline and uses fresh coverage/scope. Surviving or uncovered mutants are separate from worker errors.

Golden comparison and update are different commands. Updates require `AQG_ALLOW_GOLDEN_UPDATE=1` during an explicit maintenance operation and remain human-review-plane changes.

## Supply chain

The `supply_chain` gate derives deterministic CycloneDX 1.6 component inventories from committed npm, pnpm, Yarn, Bun, Python lock, or exact requirements artifacts. It rejects declared dependencies without a supported reproducible input, validates component shape/order/identity, and inventories protected AQG toolchains when their locks exist.

Vulnerability discovery remains in `security_fast`; inventory and vulnerability detection are intentionally distinct because an SBOM is not a vulnerability verdict.

## Security boundary

Repository instructions and local hooks can be bypassed by a sufficiently privileged local process. The authoritative boundary is hosting-side: required clean CI, immutable or reviewed tool inputs, CODEOWNERS, branch protection, and separate release approval. AQG makes local bypass visible and inconvenient; it does not claim to sandbox a hostile repository owner.
