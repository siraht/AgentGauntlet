# Threat modeling

> Produce a small actionable threat model tied to trust boundaries and verification, then keep it current when identity, data flow, deployment, dependency, or privilege changes.

## Model

Record assets, actors, entry points, trust boundaries, data stores, external services, privilege levels, and data classifications. Draw or list the data flow from input to durable side effect. State assumptions such as authenticated transport, tenant isolation, managed key storage, or trusted build runner.

## Enumerate threats

For each boundary consider spoofing/identity, tampering/integrity, repudiation/audit, information disclosure/privacy, denial of service/resource exhaustion, and elevation of privilege. Add business-abuse cases such as duplicate payment, inventory race, mass enumeration, workflow bypass, and notification spam.

## Convert to controls and tests

Each material threat gets preventive control, detection signal, test/QA evidence, owner, and residual risk. Examples: authorization decision test matrix; rate-limit property; path traversal fuzz corpus; secret-redaction golden; stale-version concurrency test; audit-event contract; deployment kill switch.

## Change triggers

Review the model when adding routes, roles, authentication factors, sensitive fields, migrations, queues, third-party services, file handling, cryptography, CI permissions, dependencies with install scripts, or new deployment topology. A risk-card factor should point to the relevant threat-model section.
