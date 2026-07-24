# API contracts

> Treat the API specification, runtime validation, compatibility tests, and error semantics as one controlled surface.

## Specification requirements

Document operation identity, authentication/authorization, request and response schemas, validation constraints, status/error codes, idempotency, pagination, concurrency/version preconditions, rate limits, and examples. Examples must include success, invalid input, unauthenticated, unauthorized, not found without information leakage, conflict, rate limit, and dependency failure where applicable.

## Runtime enforcement

Validate untrusted input at the boundary and serialize output through the declared schema. Generated types alone do not validate runtime JavaScript or Python values. Test that unknown fields, duplicate keys, invalid enums, oversized input, wrong content type, and malformed encodings are handled intentionally.

## Compatibility

Diff the machine-readable API contract. Classify each change as non-breaking, conditionally breaking, or breaking. A field made required, enum narrowed, default changed, error status changed, precision reduced, or authentication requirement changed is potentially breaking even when the syntax diff is small.

## Semantic tests

- same idempotency key and same request returns the same effect;
- same key with a conflicting request is rejected;
- pagination has stable ordering and no duplicates or gaps under the documented consistency model;
- authorization is applied before existence-sensitive details are exposed;
- conditional requests and version fields prevent lost updates;
- errors use stable machine-readable codes and safe human text;
- logs and traces correlate requests without exposing credentials or personal data.

## Deployment

For a coordinated breaking change, define dual-read/write or version negotiation, consumer migration evidence, telemetry for old-version use, and removal criteria. Rollback must account for data written in the new format.
