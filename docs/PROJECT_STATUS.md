# AgentGauntlet project status

Status date: 2026-07-28

## The short version

AgentGauntlet is a working public beta, not a finished proof that its own
implementation is defect-free.

You can use it today to install a guarded quality system into Python,
JavaScript, TypeScript, HTML, and CSS repositories; run deterministic checks;
review a change; retain tamper-evident evidence; inspect the result in a CLI,
TUI, or local dashboard; and adopt an existing repository without making all
of its inherited debt block ordinary work.

AgentGauntlet is currently dogfooding itself in **shadow** mode. Its controls
work and its development workflow is usable, but its recovered implementation
still has substantial whole-tree coverage, complexity, and mutation debt. No
reviewed debt baseline has been installed, so AgentGauntlet honestly does not
claim that self-hosting ratchet or strict certification has been earned.

## What the owner should believe

| Question                                                   | Current answer             | Why                                                                                                                                                             |
| ---------------------------------------------------------- | -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Can development continue?                                  | **Yes**                    | Doctor, test discovery, unit contracts, and the shadow workflow are usable. Inherited bootstrap debt is reported rather than hidden.                            |
| Is this branch automatically safe to merge?                | **No**                     | Local checks cannot invent hosted branch-protection authority, and the risk-selected deep evidence is not completely green.                                     |
| Is AgentGauntlet ready for a production release?           | **No claim yet**           | Release evidence and actual human release authority are intentionally separate from development evidence.                                                       |
| Can it install into a new TypeScript/web project?          | **Yes, with beta caution** | A generated strict Vite/TypeScript project passed unit, property, structure, coverage, acceptance, and browser-wiring checks in a connected dogfood run.        |
| Can it adopt an existing repository without freezing work? | **Yes**                    | Shadow audit separates measured quality debt from missing evidence, invalid configuration, infrastructure failure, and unknown product intent.                  |
| Does the no-regression ratchet work?                       | **Implemented and tested** | It compares exact reviewed debt fingerprints and values, but it becomes authoritative only after someone reviews and installs a baseline.                       |
| Can agents replace every human decision?                   | **No**                     | Agents can provide broad technical review. Product intent, policy ownership, and release authority remain explicit boundaries rather than fabricated approvals. |

## What works now

### Installation and project support

- One-command setup and a portable Python 3.11+ executable.
- Python, JavaScript, TypeScript, HTML, and CSS detection and adapters.
- Isolated, pinned checker toolchains.
- Strict greenfield mode and staged brownfield adoption.
- GitHub Actions, CODEOWNERS, Codex, Claude Code, and generic agent
  integrations.
- Deterministic portable builds, checksums, SBOMs, and provenance.

### Quality controls

- Formatting, linting, typing, test-discovery integrity, unit tests, contracts,
  Gherkin acceptance, coverage, structure, CRAP, mutation, security,
  dependency, supply-chain, performance, reproducibility, and release gates.
- Four distinct outcomes: pass, measured quality failure, invalid
  configuration/input, and unusable infrastructure/evidence.
- Complete detailed gate evidence copied into each run directory and finalized
  with a tamper-evident manifest.
- Exact requirement-to-test traceability and domain-valid semantic acceptance
  mutation.
- Stable multi-sample performance evidence instead of a single noisy timing.

### Existing-repository adoption

The lifecycle is:

```text
read-only shadow audit
        ↓
reviewed immutable debt baseline
        ↓
no-regression ratchet + changed-code enforcement
        ↓
debt retirement
        ↓
strict whole-tree enforcement
```

Shadow mode makes only measured inherited quality debt non-blocking. It does
not convert missing reports, checker crashes, invalid configuration, or
unknown product intent into success. Ratchet mode keeps reviewed inherited
debt visible and blocks a new fingerprint, a worsened value, malformed debt,
or changed code that misses current policy.

### Owner control surface

The CLI and dashboard now use one read-only status model. They answer three
different questions:

- **Develop:** may work continue locally?
- **Merge:** is the exact candidate supported by current evidence, and where
  must external authority still decide?
- **Release:** has a release evaluation actually occurred?

The dashboard leads with the decision, then shows the evidence ledger,
inherited debt versus regressions, approvals, and agent-council advice. Missing,
stale, malformed, or tampered evidence remains visible by its real category.

## The advisory agent review council

AgentGauntlet now has an opt-in multi-model technical review workflow:

```sh
python3 quality/qg.py council doctor
python3 quality/qg.py council plan --tier smoke --data-classification public
python3 quality/qg.py council run --tier pr --data-classification public
python3 quality/qg.py council verify
python3 quality/qg.py council report
```

The controller creates one content-addressed candidate bundle—or a manifested
bounded series when the exact diff is too large—from the revision, diff, risk
card, feature requirements, review packet, and quality evidence. A series
repeats the complete shared context, splits only the diff, and requires every
role to review every chunk. Candidate instructions are treated as data, shell
interpolation is forbidden, tools are disabled or restricted, environment
variables are minimized, and timeouts fail closed.

Configured perspectives are:

| Perspective                   | Default model              |
| ----------------------------- | -------------------------- |
| Requirements and behavior     | Grok 4.5                   |
| Test and evidence quality     | Codex GPT-5.6 Sol          |
| Security and trust boundaries | Codex GPT-5.6 Sol          |
| Operations and rollback       | OpenCode DeepSeek V4 Flash |

GLM-4.7-Flash and DeepSeek V4 Flash form the inexpensive smoke tier. The PR
tier retains Synthetic support. High tier uses three existing
subscription/free provider groups—Grok, Codex, and OpenCode—without Synthetic
API spending. Repeated Codex roles visibly count as one provider group, not
independent providers.

Every valid ballot cites exact bundled material. Quorum, blocker veto,
completeness, and dissent are deterministic. Prompt and response digests,
validated ballots, model/provider identity, tool versions, timings, and the
conclusion are immutable. Raw provider streams are discarded because they can
contain hidden reasoning, provider metadata, or reflected sensitive text.

Chunked review now states its limit plainly: each ballot sees one diff segment,
so cross-chunk relationships remain a residual unknown. `complete` means all
required chunk ballots arrived and validated, not that one model comprehended
the whole patch. Live dogfood reviewed a two-chunk, 93,820-byte candidate
through six isolated calls across Grok, GLM, and DeepSeek; nested evidence run
`council-20260728T222334Z-40d69d5f` verifies without manifest errors.

The result is always labeled **agent advisory — not an approval or release
authority**. A council cannot turn a failing deterministic gate green, fill in
unknown product intent, impersonate a code owner, or release software.

## Comparison with the original v2 plan

The recovered v2 plan described a strong control plane: setup, language
adapters, profiles, automated review, evidence, TUI/dashboard, agent guidance,
and supply-chain controls. Most of that exists and has been exercised.

The productionization work added or materially strengthened the pieces that
the original plan either left incomplete or trusted too easily:

| Original v2 promise                  | Current implementation                                                                                                                                   |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ratchet mode for legacy repositories | Real shadow evidence, reviewed baseline lifecycle, exact value/fingerprint comparisons, and monotonic promotion stages.                                  |
| Immutable evidence                   | Detailed adapter evidence is inside each run and manifest verification detects additions, deletions, modifications, unsafe paths, and identity mismatch. |
| Authoritative CI                     | A protected-base workflow grades candidate source with controls from the trusted base rather than executing a candidate-controlled grader.               |
| High-assurance review                | Behavior review, manual QA, rollback rehearsal, and independent verification are real fingerprinted requirements.                                        |
| Easy dashboard                       | One owner-status model now drives plain Develop/Merge/Release decisions and the evidence ledger.                                                         |
| Automated review                     | Deterministic diff review is supplemented by an immutable, diverse, advisory model council.                                                              |
| Acceptance mutation                  | Mutants use declared domain-valid mappings and prove entry through the application boundary.                                                             |
| Performance                          | Warmup plus retained samples, median aggregation, and stability limits replace one-shot results.                                                         |
| Test collection                      | Every configured test root, including `quality/tests`, is authoritative.                                                                                 |

## What is not yet earned

- The recovered codebase is not whole-tree clean at current Standard
  thresholds. Existing coverage, structure, and mutation debt remains real.
- AgentGauntlet has not installed a reviewed self-hosting debt baseline because
  the owner explicitly deferred that review. It therefore remains in shadow.
- Stop-hook enforcement is disabled. It should remain disabled until the fast
  profile is green, stable, and reasonably quick across repeated runs.
- The advisory council has no policy authority and has not been calibrated
  against enough real reviewed changes to justify expanding its authority.
- Critical changes still need actual accountable human review and release
  authority.
- Two representative brownfield pilots are intentionally deferred.

## How confidence was built

AgentGauntlet has been tested at several levels:

- source unit and contract tests, including the normally omitted
  `quality/tests` root;
- deliberate faults for stale/tampered evidence, missing tests, malformed
  output, invalid policy maintenance, changed-code regressions, and mutation
  gaps;
- live JavaScript/Python/package-manager/browser fixtures;
- an end-to-end strict TypeScript/web pilot;
- local dashboard and TUI control-surface dogfood;
- deterministic repeated release builds and hosted CI;
- bounded changed-code structure, coverage, and mutation proofs;
- real provider-tool discovery and fail-closed advisory-council evidence.

This is strong evidence that the mechanisms execute as designed. It is not a
mathematical proof that every adapter is correct in every future repository.

## Practical use today

For a new project:

```sh
./install-aqg.sh /path/to/project --owner @your-org/quality --mode greenfield
cd /path/to/project
./aqg doctor
./aqg check fast
```

For an existing project:

```sh
./install-aqg.sh /path/to/project --owner @your-org/quality --mode adopt
cd /path/to/project
./aqg audit shadow --profile fast
./aqg status
```

For ordinary development:

```sh
./aqg check inner
./aqg audit shadow --profile fast
./aqg check-risk --shadow --keep-going
./aqg review --write --sarif
./aqg status
```

The two shadow commands are correct for this repository today. After a reviewed
baseline and promotion to `ratchet`, use `check fast` and
`check-risk --keep-going` instead.

Use deep checks at PR or meaningful checkpoint boundaries. Use release and
human-assurance controls only for an actual release or risk profile that
requires them.

## Best next improvements

1. Calibrate the advisory council on a corpus of known-good and deliberately
   defective changes; measure unique finding yield, false positives,
   contradiction rate, latency, and cost by role/model.
2. Add approved enterprise/local provider routes for `internal`,
   `confidential`, and `regulated` bundles. Current routing already classifies
   and rejects those scopes before any provider call.
3. Add bounded reconciliation: reviewers see anonymized conflicting claims,
   not identities, and must cite evidence for any changed position.
4. Generate a plain-language owner brief that explains each council finding,
   confidence, evidence, and recommended decision without technical shorthand.
5. Continue extracting recovered complexity hotspots behind characterization
   tests and bounded mutation campaigns.
6. Reduce the inner-loop p95 without removing controls; keep the complete fast
   suite at coherent checkpoints rather than every edit.
7. Pilot two real brownfield repositories later, as intentionally deferred,
   before recommending portfolio-wide ratchet defaults.
