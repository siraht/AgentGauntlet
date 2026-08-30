"""Contracts for the versioned dependency-free Python ABC metric."""

from __future__ import annotations

import math

import pytest

from aqg.abc_metrics import (
    PYTHON_ABC_DEFINITION,
    PythonAbcError,
    analyze_python_abc,
    analyze_python_file,
)


def test_empty_and_function_free_source_have_no_metrics() -> None:
    assert analyze_python_abc("") == ()
    assert analyze_python_abc("answer = 42\n") == ()


def test_assignment_vector_covers_documented_binding_operations() -> None:
    source = """
def bindings(first, /, second=0, *items, named, **options):
    import os, sys
    from pathlib import Path as P
    plain = 1
    annotated: int = 2
    plain += 1
    if (captured := plain):
        pass
    for item in items:
        pass
    values = [value for value in items]
    with open("x") as handle:
        pass
    try:
        pass
    except ValueError as error:
        pass
"""
    metric = analyze_python_abc(source)[0]

    # Five parameters, three imports, five assignment operators, one loop,
    # comprehension binding, one context binding, and one exception binding.
    assert metric.assignments == 17
    assert metric.definition == PYTHON_ABC_DEFINITION


def test_branch_vector_counts_calls_and_explicit_control_transfers() -> None:
    source = """
async def branches(stream):
    value = await stream.read()
    if value:
        yield value
    else:
        raise RuntimeError("empty")
    for item in stream:
        if item:
            continue
        break
    return value
"""
    metric = analyze_python_abc(source)[0]

    # read(), await, yield, RuntimeError(), raise, continue, break, return.
    assert metric.branches == 8


def test_condition_vector_counts_decisions_joins_and_comparisons() -> None:
    source = """
def conditions(values, flag):
    assert values
    if flag and values[0] > 1:
        return 1 if flag else 0
    while 0 < len(values) < 10:
        values = [item for item in values if item != 3]
"""
    metric = analyze_python_abc(source)[0]

    # assert, if, and, >, conditional expression, while, two chained
    # comparisons, comprehension filter, and != inside that filter.
    assert metric.conditions == 10


def test_match_patterns_count_bindings_cases_and_guards() -> None:
    source = """
def parse(value):
    match value:
        case {"items": [first, *rest], **extra} if first > 0:
            return first
        case other:
            return other
"""
    metric = analyze_python_abc(source)[0]

    assert metric.assignments == 5  # parameter, first, rest, extra, other
    assert metric.conditions == 4  # two cases, one guard, one comparison


def test_methods_async_and_nested_functions_have_stable_qualified_names() -> None:
    source = """
class Service:
    def sync(self):
        def inner(value):
            return transform(value)
        return inner(1)

    async def async_method(self, client):
        return await client.fetch()
"""
    metrics = analyze_python_abc(source)

    assert [metric.qualified_name for metric in metrics] == [
        "Service.sync",
        "Service.sync.inner",
        "Service.async_method",
    ]
    assert [metric.line for metric in metrics] == sorted(metric.line for metric in metrics)


def test_nested_function_and_lambda_bodies_are_excluded_from_outer_metric() -> None:
    source = """
def outer(value):
    def inner():
        assigned = expensive(value)
        return assigned
    callback = lambda item: transform(item) if item else fallback()
    return value
"""
    outer, inner = analyze_python_abc(source)

    assert (outer.assignments, outer.branches, outer.conditions) == (2, 1, 0)
    assert (inner.assignments, inner.branches, inner.conditions) == (1, 2, 0)


def test_magnitude_is_euclidean_and_dictionary_is_json_compatible() -> None:
    metric = analyze_python_abc("def sample(arg):\n    value = call(arg)\n    return value\n")[0]

    assert metric.magnitude == math.sqrt(2**2 + 2**2)
    assert metric.as_dict() == {
        "definition": PYTHON_ABC_DEFINITION,
        "name": "sample",
        "qualified_name": "sample",
        "line": 1,
        "end_line": 3,
        "assignments": 2,
        "branches": 2,
        "conditions": 0,
        "magnitude": math.sqrt(8),
    }


def test_results_are_deterministic_across_repeated_analysis() -> None:
    source = "def second(x):\n    return x\n\ndef first(y):\n    return y\n"

    first_run = analyze_python_abc(source)
    second_run = analyze_python_abc(source)

    assert first_run == second_run
    assert [metric.name for metric in first_run] == ["second", "first"]


def test_invalid_source_fails_explicitly_with_location() -> None:
    with pytest.raises(PythonAbcError, match=r"example.py: invalid Python at line 1"):
        analyze_python_abc("def broken(:\n", filename="example.py")


def test_non_text_source_fails_explicitly() -> None:
    with pytest.raises(PythonAbcError, match="source must be text"):
        analyze_python_abc(b"def nope(): pass")  # type: ignore[arg-type]


def test_file_api_reads_utf8_and_reports_unreadable_or_invalid_files(tmp_path) -> None:
    valid = tmp_path / "valid.py"
    valid.write_text("def café(value):\n    return value\n", encoding="utf-8")
    assert analyze_python_file(valid)[0].name == "café"

    with pytest.raises(PythonAbcError, match="unable to read Python source"):
        analyze_python_file(tmp_path / "missing.py")

    invalid_utf8 = tmp_path / "invalid.py"
    invalid_utf8.write_bytes(b"\xff")
    with pytest.raises(PythonAbcError, match="unable to read Python source"):
        analyze_python_file(invalid_utf8)
