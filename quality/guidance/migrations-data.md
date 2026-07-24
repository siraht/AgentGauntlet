# Migrations and data safety

> Treat schema/data migration as a state transition with compatibility, rehearsal, observability, and recovery evidence; “migration applied successfully” is only the first check.

## Plan

Document source and target schema, invariants, volume, lock/resource impact, application-version compatibility, backfill semantics, null/default handling, retries, idempotency, and rollback or forward-recovery. Classify destructive and irreversible steps explicitly.

## Test matrix

- empty, minimal, typical, maximum-volume, malformed, duplicate, and legacy records;
- old application with new schema and new application with old/intermediate schema where rolling deployment requires it;
- interrupted migration and safe resume;
- duplicate execution/idempotency;
- concurrent reads/writes;
- backfill validation and reconciliation totals;
- rollback/restore, including data written after cutover;
- permissions, audit, and sensitive-data retention.

## Rehearsal

Use production-like volume and distribution in an isolated environment. Record duration, locks, resource peaks, error rate, reconciliation queries, and rollback duration. A dry run that skips writes does not prove write-path behavior.

## Deployment

Prefer expand/migrate/contract for zero-downtime changes. Gate destructive cleanup on telemetry showing old code and data forms are no longer used. Keep a kill switch or traffic-control plan, backups with restore verification, and explicit go/no-go thresholds.
