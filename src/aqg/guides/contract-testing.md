# Contract testing

> Verify the shape and semantics of every boundary independently of both the caller and provider implementation; keep examples versioned and make compatibility direction explicit.

## Boundary inventory

Create contracts for HTTP/GraphQL/RPC APIs, events and queues, database schemas consumed by another component, files and exports, CLI stdout/exit codes, environment/configuration, third-party clients, and recorded mock fixtures. A contract should state required/optional fields, types, constraints, error model, ordering, idempotency, authentication, pagination, versioning, and compatibility.

## Consumer and provider evidence

A consumer test proves what the caller relies on. A provider verification proves the real provider satisfies that expectation. Neither is complete alone. Run provider verification against the exact schema/example version used by the consumer and fail on an unverified pending contract.

## Compatibility rules

State whether the change must be backward compatible, forward compatible, or coordinated. Test additive optional fields, unknown enum values, missing optional fields, changed default behavior, numeric precision, null versus absent, duplicate events, and replay. Reject “schema valid” as sufficient when semantic constraints matter.

## Fakes and recordings

A fake or cassette is trusted only when verified against the real contract. Normalize unstable headers and IDs narrowly. Expire or revalidate recordings on contract version, dependency version, or authentication-flow changes.

## Failure behavior

Test timeout, malformed response, partial response, retryable/non-retryable status, rate limit, authentication expiry, and schema-incompatible payload. Verify no forbidden side effect occurs after a rejected contract.

## Review evidence

The review packet should identify changed contract files, compatibility direction, affected consumers/providers, verification run, rollout order, and rollback strategy. Lockfile or generated client changes do not substitute for this analysis.
