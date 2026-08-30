"""Fail-closed Python structure evidence with ABC no-regression comparison."""

from __future__ import annotations

import ast
import json
import subprocess
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .abc_metrics import PythonAbcError, PythonAbcMetric, analyze_python_abc
from .errors import ConfigurationError


def python_structure_evidence(
    root: Path,
    files: list[str],
    payload: Mapping[str, Any],
    limits: Mapping[str, Any],
    changed: Mapping[str, set[int]],
    *,
    adopt_mode: bool,
    base_ref: str,
    base_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine Radon and AST evidence and enforce touched-function limits."""
    ast_metrics = _python_ast_metrics(root, files)
    if adopt_mode and base_payload is None:
        raise ConfigurationError("base Python complexity evidence is required in adopt mode")
    base_metrics = (
        _base_function_metrics(root, files, base_ref, base_payload or {}) if adopt_mode else {}
    )
    functions, failures = _measure_functions(
        payload, ast_metrics, base_metrics, changed, limits, adopt_mode
    )
    return {
        "functions": sorted(
            functions, key=lambda item: (item["complexity"], item["lines"]), reverse=True
        ),
        "failures": failures,
        "limits": dict(limits),
        "scope": "changed-functions" if adopt_mode else "full",
    }


def _measure_functions(
    payload: Mapping[str, Any],
    ast_metrics: Mapping[tuple[str, int], Mapping[str, Any]],
    base_metrics: Mapping[str, Mapping[str, Mapping[str, Any]]],
    changed: Mapping[str, set[int]],
    limits: Mapping[str, Any],
    adopt_mode: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    functions: list[dict[str, Any]] = []
    failures: list[str] = []
    for filename, block in _radon_blocks(payload):
        item = _function_item(filename, block, ast_metrics, changed, adopt_mode)
        _classify_metrics(item, base_metrics.get(filename, {}), limits, adopt_mode)
        functions.append(item)
        failures.extend(_function_failures(item, limits))
    return functions, failures


def _radon_blocks(payload: Mapping[str, Any]) -> Iterable[tuple[str, Mapping[str, Any]]]:
    for filename, blocks in payload.items():
        if not isinstance(blocks, list):
            raise ConfigurationError(f"Radon blocks for {filename} must be an array")
        for block in blocks:
            if not isinstance(block, Mapping):
                raise ConfigurationError(f"Radon returned a malformed block for {filename}")
            if block.get("type") == "class":
                yield from _radon_methods(filename, block.get("methods"))
            elif block.get("type") in {"function", "method"}:
                yield filename, block


def _radon_methods(filename: str, value: Any) -> Iterable[tuple[str, Mapping[str, Any]]]:
    if not isinstance(value, list):
        raise ConfigurationError(f"Radon class methods for {filename} must be an array")
    for method in value:
        if not isinstance(method, Mapping):
            raise ConfigurationError(f"Radon returned a malformed method for {filename}")
        yield filename, method


def _function_nesting(node: ast.AST, depth: int = 0) -> int:
    nesting_nodes = (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.Try,
        ast.With,
        ast.AsyncWith,
        ast.Match,
    )
    maximum = depth
    for child in ast.iter_child_nodes(node):
        if (
            isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
            and child is not node
        ):
            continue
        child_depth = depth + 1 if isinstance(child, nesting_nodes) else depth
        maximum = max(maximum, _function_nesting(child, child_depth))
    return maximum


def _python_ast_metrics(root: Path, files: list[str]) -> dict[tuple[str, int], dict[str, Any]]:
    metrics: dict[tuple[str, int], dict[str, Any]] = {}
    for filename in files:
        try:
            source = (root / filename).read_text(encoding="utf-8")
            tree = ast.parse(source, filename=filename)
            abc_metrics = {
                item.line: item for item in analyze_python_abc(source, filename=filename)
            }
        except (OSError, SyntaxError, PythonAbcError) as error:
            raise ConfigurationError(
                f"unable to measure Python structure for {filename}: {error}"
            ) from error
        _collect_ast_metrics(metrics, filename, tree, abc_metrics)
    return metrics


def base_radon_payload(
    root: Path, files: list[str], base_ref: str, radon_executable: str
) -> dict[str, Any]:
    """Measure Git-base complexity with the same pinned Radon executable."""
    _verify_base_ref(root, base_ref)
    work_root = root / ".aqg" / "work"
    work_root.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="structure-base-", dir=work_root) as directory:
        temporary = Path(directory)
        for index, filename in enumerate(files):
            source = _git_source(root, base_ref, filename)
            if source is None:
                payload[filename] = []
                continue
            candidate = temporary / f"source-{index}.py"
            candidate.write_bytes(source)
            payload[filename] = _run_base_radon(root, candidate, radon_executable)
    return payload


def _run_base_radon(root: Path, path: Path, executable: str) -> list[Any]:
    result = subprocess.run(
        [executable, "cc", "-j", "-s", str(path)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    if result.returncode != 0:
        raise ConfigurationError(
            f"unable to measure base Python complexity for {path.name}: "
            f"Radon exited {result.returncode}"
        )
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ConfigurationError("base Python complexity evidence is malformed") from error
    blocks = parsed.get(str(path)) if isinstance(parsed, Mapping) else None
    if not isinstance(blocks, list):
        raise ConfigurationError("base Python complexity evidence is missing")
    return blocks


def _collect_ast_metrics(
    result: dict[tuple[str, int], dict[str, Any]],
    filename: str,
    tree: ast.Module,
    abc_metrics: Mapping[int, PythonAbcMetric],
) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        abc = abc_metrics.get(int(node.lineno))
        if abc is None:
            raise ConfigurationError(f"Python ABC evidence is missing for {filename}:{node.lineno}")
        end = int(getattr(node, "end_lineno", node.lineno))
        result[(filename, int(node.lineno))] = {
            "lines": end - int(node.lineno) + 1,
            "nesting": _function_nesting(node),
            "qualified_name": abc.qualified_name,
            "assignments": abc.assignments,
            "branches": abc.branches,
            "conditions": abc.conditions,
            "abc_magnitude": abc.magnitude,
            "abc_definition": abc.definition,
        }


def _function_item(
    filename: str,
    block: Mapping[str, Any],
    ast_metrics: Mapping[tuple[str, int], Mapping[str, Any]],
    changed: Mapping[str, set[int]],
    adopt_mode: bool,
) -> dict[str, Any]:
    start = int(block.get("lineno", 0))
    end = int(block.get("endline", start))
    structural = ast_metrics.get((filename, start))
    if structural is None:
        raise ConfigurationError(f"Python AST evidence is missing for {filename}:{start}")
    enforced = not adopt_mode or bool(
        changed.get(filename, set()).intersection(range(start, end + 1))
    )
    return {
        "path": filename,
        "name": block.get("name"),
        "qualified_name": structural["qualified_name"],
        "line": start,
        "end_line": end,
        "complexity": int(block.get("complexity", 1)),
        **{
            key: structural[key]
            for key in (
                "lines",
                "nesting",
                "assignments",
                "branches",
                "conditions",
                "abc_magnitude",
                "abc_definition",
            )
        },
        "enforced": enforced,
        "abc_enforced": enforced,
    }


def _verify_base_ref(root: Path, base_ref: str) -> None:
    revision = subprocess.run(
        ["git", "rev-parse", "--verify", f"{base_ref}^{{commit}}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if revision.returncode != 0:
        raise ConfigurationError(f"Python structure comparison base does not resolve: {base_ref}")


def _git_source(root: Path, base_ref: str, filename: str) -> bytes | None:
    source = subprocess.run(
        ["git", "show", f"{base_ref}:{filename}"], cwd=root, capture_output=True, check=False
    )
    return source.stdout if source.returncode == 0 else None


def _base_function_metrics(
    root: Path,
    files: list[str],
    base_ref: str,
    base_payload: Mapping[str, Any],
) -> dict[str, dict[str, dict[str, Any]]]:
    _verify_base_ref(root, base_ref)
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for filename in files:
        source = _git_source(root, base_ref, filename)
        if source is None:
            result[filename] = {}
            continue
        try:
            text = source.decode("utf-8")
            tree = ast.parse(text, filename=filename)
            abc = {item.line: item for item in analyze_python_abc(text, filename=filename)}
        except (UnicodeError, SyntaxError, PythonAbcError) as error:
            raise ConfigurationError(
                f"unable to measure base Python structure for {filename}"
            ) from error
        ast_metrics: dict[tuple[str, int], dict[str, Any]] = {}
        _collect_ast_metrics(ast_metrics, filename, tree, abc)
        result[filename] = _merge_base_metrics(
            filename, ast_metrics, base_payload.get(filename, [])
        )
    return result


def _merge_base_metrics(
    filename: str,
    ast_metrics: Mapping[tuple[str, int], Mapping[str, Any]],
    blocks: Any,
) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for _path, block in _radon_blocks({filename: blocks}):
        line = int(block.get("lineno", 0))
        structural = ast_metrics.get((filename, line))
        if structural is None:
            raise ConfigurationError(f"base Python AST evidence is missing for {filename}:{line}")
        merged[str(structural["qualified_name"])] = {
            "complexity": int(block.get("complexity", 1)),
            "lines": int(structural["lines"]),
            "nesting": int(structural["nesting"]),
            "abc_magnitude": float(structural["abc_magnitude"]),
        }
    return merged


def _classify_metrics(
    item: dict[str, Any],
    base: Mapping[str, Mapping[str, Any]],
    limits: Mapping[str, Any],
    adopt_mode: bool,
) -> None:
    prior = base.get(str(item["qualified_name"])) if adopt_mode else None
    for metric, threshold in _METRIC_LIMITS:
        _classify_metric(item, prior, metric, limits.get(threshold), adopt_mode)


def _classify_metric(
    item: dict[str, Any],
    prior: Mapping[str, Any] | None,
    metric: str,
    limit: Any,
    adopt_mode: bool,
) -> None:
    enforcement_key = _enforcement_key(metric)
    item[enforcement_key] = bool(item["enforced"])
    if limit is None or not item["enforced"] or float(item[metric]) <= float(limit):
        return
    if not adopt_mode or prior is None or float(prior[metric]) <= float(limit):
        item[f"{metric}_debt_origin"] = "new_violation"
        return
    item[f"base_{metric}"] = prior[metric]
    regressed = float(item[metric]) > float(prior[metric])
    item[enforcement_key] = regressed
    item[f"{metric}_debt_origin"] = "regression" if regressed else "inherited_git_base"


_METRIC_LIMITS = (
    ("complexity", "max_cyclomatic_complexity"),
    ("lines", "max_function_lines"),
    ("nesting", "max_nesting_depth"),
    ("abc_magnitude", "max_abc_score"),
)


def _enforcement_key(metric: str) -> str:
    return "abc_enforced" if metric == "abc_magnitude" else f"{metric}_enforced"


def _function_failures(item: Mapping[str, Any], limits: Mapping[str, Any]) -> list[str]:
    if not item.get("enforced"):
        return []
    failures: list[str] = []
    for metric, threshold in _METRIC_LIMITS:
        if threshold not in limits:
            continue
        if not item.get(_enforcement_key(metric)):
            continue
        if float(item[metric]) > float(limits[threshold]):
            failures.append(
                f"{item['path']}:{item['line']} {item['name']} {metric} "
                f"{item[metric]} > {limits[threshold]}"
            )
    return failures
