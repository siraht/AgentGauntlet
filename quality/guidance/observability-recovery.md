# Observability and recovery

> A feature is operable only when failures are detectable, diagnosable, containable, and recoverable without relying on source inspection.

## Signals

Define success/error counters, latency and resource measures, queue/backlog state, business invariants, structured safe logs, traces/correlation IDs, and audit events. Each signal needs owner, threshold, aggregation window, and expected response. Avoid secrets, credentials, personal data, and unbounded high-cardinality labels.

## Tests

Inject each important failure and assert both behavior and signal: user receives safe actionable error, durable state remains valid, expected metric/event/log is emitted once, correlation is possible, and forbidden data is absent. Test degraded dependencies, timeout, cancellation, duplicate event, restart, stale cache, and alert-clear recovery.

## Runbooks

A runbook states detection, impact assessment, immediate containment, rollback/kill switch, data reconciliation, recovery validation, and escalation. Rehearse the runbook for high-assurance changes and record observed timing. A written rollback command that has never been exercised is a hypothesis.
