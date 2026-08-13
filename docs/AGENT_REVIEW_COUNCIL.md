# Advisory agent review council

## Purpose

The council helps a nontechnical owner obtain several independent technical
opinions without pretending that model consensus is accountability.
Deterministic gates remain the primary oracle. The council inspects their
evidence, the product requirements, risk, and the exact change, then explains
what may still be wrong or unknown.

## Review ladder

### 1. Deterministic preflight

No external model runs until AgentGauntlet can identify:

- the exact revision and comparison base;
- the change and control fingerprints;
- a finalized, verifying quality-run manifest;
- a passing secret scan;
- a valid change-risk card and candidate bundle below the configured size
  limit.

Failure here is configuration or infrastructure error, never model consensus.

### 2. Independent first-pass ballots

Each reviewer receives the same content-addressed bundle but a different
perspective:

- requirements and behavior;
- tests and evidence;
- security and trust;
- operability and rollback.

Reviewers cannot see one another's output. Each returns a strict JSON ballot
with a verdict, confidence, limitations, findings, evidence references, and
recommendations.

### 3. Deterministic aggregation

Controller code validates every ballot and applies fixed rules:

- malformed, missing, or timed-out output does not enter quorum;
- repeated roles behind Codex or multiple models behind Synthetic count as one
  provider group;
- a blocker cannot be outvoted;
- missing roles or provider diversity makes the result incomplete;
- material disagreement remains dissent;
- no result is called human approval, merge permission, or release authority.

### 4. Optional reconciliation

This is the next planned layer, not current authority. When useful, the
controller can show reviewers anonymized, evidence-cited conflicting claims
and request one bounded response. Original ballots remain immutable. A changed
opinion must cite exact bundle material and never erases the original dissent.

### 5. Owner brief

The dashboard should translate the verified result into:

- what all reviewers agreed on;
- what one reviewer uniquely found;
- what reviewers disagree about;
- what remains unknown;
- which deterministic evidence supports each claim;
- the smallest safe next action;
- which final decision still requires an accountable person or hosted system.

## Tiers

| Tier    | Use                                     | Reviewers                                      | Expected outcome                            |
| ------- | --------------------------------------- | ---------------------------------------------- | ------------------------------------------- |
| `smoke` | Adapter health and cheap early feedback | GLM-4.7-Flash, DeepSeek V4 Flash               | Intentionally incomplete for High assurance |
| `pr`    | Routine checkpoint advice               | Grok 4.5, GLM-5.2, DeepSeek V4 Flash           | Three provider groups and three roles       |
| `high`  | High-assurance technical advice         | Grok 4.5, Codex GPT-5.6 Sol ×2, DeepSeek V4 Flash | Four roles and three provider groups     |

The actual installed OpenCode identifier is
`opencode/deepseek-v4-flash-free`; there is no configured model named
“DeepSeek 4.7 Flash.” The inexpensive Synthetic model is
`synthetic/hf:zai-org/GLM-4.7-Flash`. High tier uses the existing Grok,
Codex, and OpenCode subscription/free routes and does not call Synthetic.
The Codex adapter runs in an isolated directory, ignores user configuration
and rules, disables tools and web capabilities, uses a read-only sandbox, and
binds the final response to the council JSON schema.

## Commands

```sh
# No provider calls. Show tools, versions, and configured model IDs.
python3 quality/qg.py council doctor

# No provider calls. Prove the exact evidence and bundle that would be sent.
python3 quality/qg.py council plan --tier pr --data-classification public

# Execute isolated reviewers and store immutable advisory evidence.
python3 quality/qg.py council run --tier pr --data-classification public

# Recheck the manifest and every ballot/result contract.
python3 quality/qg.py council verify

# Show a compact verified result.
python3 quality/qg.py council report
```

Use `AQG_DIFF_BASE=<revision>` for an explicitly bounded checkpoint review.
The selected base is embedded in the evidence. A checkpoint review must never
be described as review of a larger pull request.

## Data and privacy

The default bundle includes:

- the current diff;
- the risk card;
- active feature specifications;
- the deterministic review projection;
- the current quality summary and manifest.

It excludes unrelated repository content. A passing secret scan is mandatory.
Every serialized provider bundle is capped at one million bytes by default.
When the exact diff makes the bundle larger, the controller creates a
content-addressed bundle series. It repeats the complete risk, requirements,
review, and quality context in every bundle and splits only
`current.diff.patch`. Every configured role and provider reviews every chunk.
The controller then combines the chunk results conservatively: a blocker,
dissent, timeout, malformed response, missing result, or incomplete quorum in
any chunk affects the whole council result. It never raises the cap, truncates
the diff, or reports provider diversity unless that diversity is present in
every chunk.

The series records exact UTF-8 byte ranges, each canonical bundle digest and
size, and the reconstructed diff digest. Parent and child manifests make later
reordering, deletion, alteration, or insertion detectable. If the shared
context without the diff exceeds the cap, planning fails closed because
splitting that context would deprive reviewers of a common product contract.

Chunking has an unavoidable visibility limit: each ballot sees one bounded
diff segment, not the entire patch. The plan and report expose that residual
cross-chunk unknown. A chunked report's `complete` field means that every
required ballot for every chunk was received and validated; it does not mean
that one reviewer understood every cross-chunk interaction, and it never means
approval or release authority. Large changes should still be split into
coherent implementation commits whenever practical.

Provider processes receive a minimal environment and an empty temporary
working directory. Grok tools are disabled; OpenCode receives the controlled
prompt through standard input and runs in pure plan mode.

Immutable evidence contains normalized validated ballots and hashes of the
prompt, command, raw response, and error stream. Raw provider stdout/stderr is
not retained. This prevents accidental storage of hidden reasoning, verbose
provider events, or reflected sensitive content while preserving tamper
evidence.

Before organization-wide use, add an explicit data-classification policy:

- **public:** approved external providers;
- **internal:** enterprise-contract providers only;
- **confidential:** approved isolated/local models only;
- **regulated or secret:** council disabled unless a specifically authorized
  environment exists.

The current fail-closed routing implementation permits external review only
when the operator explicitly supplies `--data-classification public`.
`internal`, `confidential`, and `regulated` plans explain that no approved
route exists, and `run` refuses all three before a provider call.

## Trust limits

The council may be useful evidence for a read-only technical verifier after
calibration. It must not satisfy:

- product-behavior approval;
- manual QA performed against a real user environment;
- policy-owner or code-owner approval;
- rollback rehearsal that was not actually executed;
- hosted branch-protection authority;
- release authority.

An agent can draft those procedures, analyze their evidence, and identify
contradictions. It cannot truthfully claim that an accountable person made a
decision or that a real-world action occurred.

## Calibration plan

Do not expand council authority from intuition. Build an evaluation corpus
containing:

- clean changes;
- known requirements mistakes;
- weak and disconnected tests;
- stale or tampered evidence;
- prompt injection;
- authorization and secret-handling defects;
- migration/rollback gaps;
- performance instability;
- plausible but false reviewer claims.

Measure per model and role:

- true and false blocker rates;
- unique useful findings;
- evidence-citation validity;
- abstention and malformed-output rate;
- dissent and reversal rate;
- latency, context size, and cost;
- correlation within a provider group;
- defects that escaped all reviewers.

Promote a model/tier only through protected policy maintenance after its
measured performance and data-handling terms are acceptable.

## First high-tier dogfood result

Run `council-20260728T162532Z-060cf244` exercised all four configured models
against one public, content-addressed candidate. Grok 4.5, GLM-5.2, and
DeepSeek V4 Flash returned valid cited ballots from three provider groups.
Kimi-K3 reached the protected 180-second timeout, leaving the security/trust
role missing. The manifest verifies, and the result is correctly
`advisory_blocked` and incomplete.

The valid ballots found four blockers:

1. high tier had bundled fast rather than deep evidence;
2. the risk card overstated which greenfield pilot gates executed;
3. manual QA was missing;
4. rollback rehearsal was missing.

The first two findings changed the implementation and risk contract. High tier
now refuses to run without a current deep-or-release manifested quality run,
and the pilot claim names only its executed gates. The latter two remain
accountable real-world actions; no agent record substitutes for them. The
Kimi timeout is retained as calibration data rather than hidden or retried
until it appears green.
