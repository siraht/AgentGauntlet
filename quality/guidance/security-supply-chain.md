# Security and software supply chain

> Use layered secure-development controls from design through release: threat model, input/boundary tests, secret/dependency/static analysis, locked tools, isolated builds, provenance, and human review of high-impact paths.

## Design and implementation

Map trust boundaries, assets, identities, authorization decisions, sensitive data, external dependencies, and destructive actions. Validate at each untrusted boundary, use least privilege, safe defaults, parameterized APIs, output encoding, explicit cryptographic libraries, secure session/cookie handling, and redacted observability.

## Verification layers

- secret scan of full repository history where platform support exists plus changed/worktree scan locally;
- dependency audit against a committed lock and review of direct/transitive changes;
- static analysis for injection, deserialization, path, subprocess, template, and auth patterns;
- contract/negative tests for malformed and hostile input;
- authorization matrix and cross-tenant tests;
- dynamic application/security tests for exposed services where justified;
- fuzzing for parsers/protocols;
- manual threat-focused review for high assurance.

A scanner warning is evidence to triage, not proof of exploitability. A clean scanner is not proof of security.

## Toolchain integrity

AQG tools run in isolated project-local environments from exact JS locks and hash-checked Python requirements. Protected CI installs the committed lock and runs conformance fixtures. Policy/tool changes require CODEOWNERS review. Build output should carry provenance/attestation and be promoted rather than rebuilt between environments.

## Standards mapping

Use NIST SSDF 1.1 as the current final process baseline; treat NIST SSDF 1.2 as draft until final. Use OWASP ASVS 5.0 requirements for web application verification. Use SLSA 1.2 Source/Build tracks for source governance and provenance. Project regulation and threat model may impose stricter requirements.
