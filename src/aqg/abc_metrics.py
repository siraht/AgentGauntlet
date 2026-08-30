"""Deterministic Assignments-Branches-Conditions metrics for Python.

``aqg-python-abc-v1`` measures named ``def`` and ``async def`` bodies.  It is
an AQG-specific, versioned definition because published ABC implementations do
not agree on Python semantics:

* Assignments are parameter bindings, assignment operators, named-expression
  operators, import aliases, and loop/context/exception/pattern bindings.
* Branches are calls and explicit control transfers: return, raise, await,
  yield, yield-from, break, and continue.
* Conditions are decision sites (if, conditional expressions, while, assert,
  comprehension filters, exception handlers, and match cases) plus comparison
  operators and boolean joins.

Decorators and default values are outside the measured function body.  Nested
named function and lambda bodies are excluded from their enclosing function;
nested named functions receive their own metric.  Results are returned in
source order.  Invalid source and unreadable files raise ``PythonAbcError`` and
can therefore never be interpreted as an empty, passing measurement.
"""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from pathlib import Path

PYTHON_ABC_DEFINITION = "aqg-python-abc-v1"


class PythonAbcError(ValueError):
    """The requested Python source could not be measured reliably."""


@dataclass(frozen=True, slots=True)
class PythonAbcMetric:
    """The immutable ABC vector and magnitude for one named Python function."""

    name: str
    qualified_name: str
    line: int
    end_line: int
    assignments: int
    branches: int
    conditions: int
    magnitude: float
    definition: str = PYTHON_ABC_DEFINITION

    def as_dict(self) -> dict[str, int | float | str]:
        """Return a JSON-compatible representation with stable field names."""

        return {
            "definition": self.definition,
            "name": self.name,
            "qualified_name": self.qualified_name,
            "line": self.line,
            "end_line": self.end_line,
            "assignments": self.assignments,
            "branches": self.branches,
            "conditions": self.conditions,
            "magnitude": self.magnitude,
        }


@dataclass(frozen=True, slots=True)
class _Function:
    node: ast.FunctionDef | ast.AsyncFunctionDef
    qualified_name: str


class _FunctionCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.functions: list[_Function] = []
        self._scope: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._collect_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._collect_function(node)

    def _collect_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualified_name = ".".join([*self._scope, node.name])
        self.functions.append(_Function(node, qualified_name))
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()


class _AbcVisitor(ast.NodeVisitor):
    def __init__(self, initial_assignments: int) -> None:
        self.assignments = initial_assignments
        self.branches = 0
        self.conditions = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        return

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        self.assignments += 1
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        self.assignments += 1
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:  # noqa: N802
        self.assignments += 1
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:  # noqa: N802
        self.assignments += 1
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        self.assignments += len(node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        self.assignments += len(node.names)

    def visit_For(self, node: ast.For) -> None:  # noqa: N802
        self.assignments += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:  # noqa: N802
        self.assignments += 1
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self.assignments += 1
        self.conditions += len(node.ifs)
        self.generic_visit(node)

    def visit_withitem(self, node: ast.withitem) -> None:
        if node.optional_vars is not None:
            self.assignments += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:  # noqa: N802
        self.conditions += 1
        if node.name is not None:
            self.assignments += 1
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:  # noqa: N802
        self.assignments += int(node.name is not None)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:  # noqa: N802
        self.assignments += int(node.name is not None)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:  # noqa: N802
        self.assignments += int(node.rest is not None)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        self.branches += 1
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:  # noqa: N802
        self.branches += 1
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:  # noqa: N802
        self.branches += 1
        self.generic_visit(node)

    def visit_Await(self, node: ast.Await) -> None:  # noqa: N802
        self.branches += 1
        self.generic_visit(node)

    def visit_Yield(self, node: ast.Yield) -> None:  # noqa: N802
        self.branches += 1
        self.generic_visit(node)

    def visit_YieldFrom(self, node: ast.YieldFrom) -> None:  # noqa: N802
        self.branches += 1
        self.generic_visit(node)

    def visit_Break(self, node: ast.Break) -> None:  # noqa: N802
        self.branches += 1

    def visit_Continue(self, node: ast.Continue) -> None:  # noqa: N802
        self.branches += 1

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        self.conditions += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:  # noqa: N802
        self.conditions += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:  # noqa: N802
        self.conditions += 1
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:  # noqa: N802
        self.conditions += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:  # noqa: N802
        self.conditions += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:  # noqa: N802
        self.conditions += len(node.ops)
        self.generic_visit(node)

    def visit_match_case(self, node: ast.match_case) -> None:
        self.conditions += 1 + int(node.guard is not None)
        self.generic_visit(node)


def analyze_python_abc(source: str, *, filename: str = "<string>") -> tuple[PythonAbcMetric, ...]:
    """Measure all named functions in *source* or raise ``PythonAbcError``."""

    if not isinstance(source, str):
        raise PythonAbcError(f"{filename}: Python source must be text")
    try:
        tree = ast.parse(source, filename=filename)
    except (SyntaxError, ValueError) as error:
        line = getattr(error, "lineno", None)
        location = f" at line {line}" if line is not None else ""
        raise PythonAbcError(f"{filename}: invalid Python{location}: {error}") from error
    collector = _FunctionCollector()
    collector.visit(tree)
    functions = sorted(
        collector.functions,
        key=lambda item: (item.node.lineno, item.node.col_offset, item.qualified_name),
    )
    return tuple(_measure_function(function) for function in functions)


def analyze_python_file(path: str | Path) -> tuple[PythonAbcMetric, ...]:
    """Read and measure a UTF-8 Python file or raise ``PythonAbcError``."""

    source_path = Path(path)
    try:
        source = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise PythonAbcError(f"{source_path}: unable to read Python source: {error}") from error
    return analyze_python_abc(source, filename=str(source_path))


def _measure_function(function: _Function) -> PythonAbcMetric:
    visitor = _AbcVisitor(_argument_count(function.node.args))
    for statement in function.node.body:
        visitor.visit(statement)
    magnitude = math.sqrt(visitor.assignments**2 + visitor.branches**2 + visitor.conditions**2)
    return PythonAbcMetric(
        name=function.node.name,
        qualified_name=function.qualified_name,
        line=function.node.lineno,
        end_line=function.node.end_lineno or function.node.lineno,
        assignments=visitor.assignments,
        branches=visitor.branches,
        conditions=visitor.conditions,
        magnitude=magnitude,
    )


def _argument_count(arguments: ast.arguments) -> int:
    positional = len(arguments.posonlyargs) + len(arguments.args)
    keyword_only = len(arguments.kwonlyargs)
    variadic = int(arguments.vararg is not None) + int(arguments.kwarg is not None)
    return positional + keyword_only + variadic
