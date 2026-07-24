# Performance and reliability

> Define service-level behavior and resource budgets around representative workloads; use controlled measurements, fault injection, and trend evidence instead of one noisy score.

## Performance contract

Specify workload, data volume, concurrency, hardware/runtime, warm/cold state, percentile latency, throughput, error rate, memory, CPU, network, and payload/bundle budgets. Averages hide tail latency. For web, pair Lighthouse diagnostics with direct resource and Core Web Vitals budgets on canonical pages.

## Test types

- microbenchmark for a pure hotspot, with statistical guardrails;
- component/service load for scaling and saturation;
- browser journey under controlled network/CPU where user perception matters;
- soak for leaks and degradation;
- spike and recovery;
- capacity limit and graceful overload;
- fault injection for dependency latency/error, queue backlog, disk/connection exhaustion, and process restart.

## Determinism and comparison

Use dedicated or controlled runners for merge-blocking thresholds. Warm up, repeat, record environment and variance, and compare distributions or robust statistics. A single shared-CI sample near a threshold is a review prompt, not precise science.

## Reliability assertions

Verify timeout, cancellation, bounded retry with jitter, circuit state, backpressure, idempotency, partial-result semantics, data consistency, and recovery time. Ensure observability shows saturation and failures without high-cardinality or sensitive-data explosions.
