# Unit tests

> Keep unit tests deterministic and behavior-focused; isolate only unstable or expensive boundaries, and assert meaningful outputs and side effects rather than implementation choreography.

## What belongs here

Use a unit test for pure calculations, validation, parsing, formatting, state reducers, permission decisions, retry-policy decisions, and one component with injected boundary interfaces. Do not force database, browser, network, filesystem, or multi-process behavior into a “unit” label when the real boundary is the behavior under test.

## Required structure

A good test makes four things obvious: starting state, action, externally meaningful result, and forbidden side effects. Use one behavioral reason for failure. Multiple assertions are acceptable when they describe one outcome, such as returned value plus exactly one persisted record and no publication on failure.

```python
# Feature-Spec: Billing.Refunds


def test_duplicate_request_returns_original_refund_without_second_charge(store, gateway):
    existing = store.refund(idempotency_key="r-17", amount=2500)

    result = refund_service(store, gateway).refund(key="r-17", amount=2500)

    assert result == existing
    gateway.charge.assert_not_called()
    assert store.refund_count("r-17") == 1
```

```ts
// Feature-Spec: Billing.Refunds
it("returns the original refund for a duplicate idempotency key", async () => {
  const existing = await store.insertRefund({ key: "r-17", amount: 2500 });

  const result = await service.refund({ key: "r-17", amount: 2500 });

  expect(result).toEqual(existing);
  expect(gateway.charge).not.toHaveBeenCalled();
  expect(await store.countRefunds("r-17")).toBe(1);
});
```

## Mocking rules

- Mock clocks, randomness, network, process environment, and external services at explicit injected boundaries.
- Prefer small fakes with state over long expectation scripts when behavior depends on several calls.
- Use autospec/spec-set or typed interfaces so a mock cannot accept methods the real dependency lacks.
- Patch where a symbol is looked up, not where it was originally defined.
- Never mock the function whose behavior the test claims to prove.
- Maintain contract tests for every important fake or recorded response.

## Assertions agents must avoid

`assert result`, `toBeTruthy()`, only checking a status code, checking only that a mock was called, or snapshotting a large object without semantic assertions are weak unless truthiness/call occurrence/full representation is itself the requirement. Assert exact semantic fields, counts, state transitions, ordering when required, and absence of forbidden effects.

## Table tests and parameterization

Use parameterization when examples share setup, action, and oracle. Split cases when failure diagnosis or setup semantics differ. Include a case identifier and the reason it exists. Do not generate hundreds of nominal examples that crowd out boundary and property tests.
