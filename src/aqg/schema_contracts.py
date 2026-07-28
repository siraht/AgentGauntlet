"""Dependency-free validation for AQG's published JSON evidence contracts."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import ConfigurationError

SCHEMA_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


def _is_array(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


TYPE_PREDICATES: dict[str, Callable[[Any], bool]] = {
    "object": lambda value: isinstance(value, Mapping),
    "array": _is_array,
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
}


def _type_matches(value: Any, expected: str) -> bool:
    predicate = TYPE_PREDICATES.get(expected)
    return predicate(value) if predicate is not None else False


def _valid_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _json_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    return bool(left == right)


def _validate_const_enum(value: Any, schema: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    if "const" in schema and not _json_equal(value, schema["const"]):
        errors.append(f"{path}: expected constant {schema['const']!r}")
    choices = schema.get("enum")
    if isinstance(choices, list) and not any(_json_equal(value, choice) for choice in choices):
        errors.append(f"{path}: value {value!r} is not in the declared enum")
    return errors


def _validate_string(value: str, schema: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    minimum_length = schema.get("minLength")
    if isinstance(minimum_length, int) and len(value) < minimum_length:
        errors.append(f"{path}: string is shorter than {minimum_length}")
    pattern = schema.get("pattern")
    if isinstance(pattern, str) and re.search(pattern, value) is None:
        errors.append(f"{path}: string does not match {pattern!r}")
    if schema.get("format") == "date-time" and not _valid_datetime(value):
        errors.append(f"{path}: expected a timezone-aware date-time")
    return errors


def _validate_number(value: int | float, schema: Mapping[str, Any], path: str) -> list[str]:
    minimum = schema.get("minimum")
    if isinstance(minimum, (int, float)) and value < minimum:
        return [f"{path}: value is below minimum {minimum}"]
    return []


def _validate_object(
    value: Mapping[str, Any],
    schema: Mapping[str, Any],
    path: str,
) -> list[str]:
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    errors = _missing_required(value, required, path)
    if not isinstance(properties, Mapping):
        return errors
    errors.extend(_validate_properties(value, properties, path))
    if schema.get("additionalProperties") is False:
        errors.extend(
            f"{path}: unexpected property {name!r}" for name in sorted(set(value) - set(properties))
        )
    return errors


def _missing_required(value: Mapping[str, Any], required: Any, path: str) -> list[str]:
    errors: list[str] = []
    if isinstance(required, list):
        for name in required:
            if isinstance(name, str) and name not in value:
                errors.append(f"{path}: missing required property {name!r}")
    return errors


def _validate_properties(
    value: Mapping[str, Any],
    properties: Mapping[str, Any],
    path: str,
) -> list[str]:
    errors: list[str] = []
    for name, child in properties.items():
        if name in value and isinstance(child, Mapping):
            errors.extend(validate_instance(value[name], child, f"{path}.{name}"))
    return errors


def _validate_array(
    value: Sequence[Any],
    schema: Mapping[str, Any],
    path: str,
) -> list[str]:
    errors: list[str] = []
    minimum_items = schema.get("minItems")
    if isinstance(minimum_items, int) and len(value) < minimum_items:
        errors.append(f"{path}: array has fewer than {minimum_items} items")
    item_schema = schema.get("items")
    if isinstance(item_schema, Mapping):
        for index, item in enumerate(value):
            errors.extend(validate_instance(item, item_schema, f"{path}[{index}]"))
    return errors


def _type_error(value: Any, schema: Mapping[str, Any], path: str) -> str | None:
    declared_type = schema.get("type")
    accepted_types = list(declared_type) if isinstance(declared_type, list) else [declared_type]
    if declared_type is not None and not any(
        isinstance(name, str) and _type_matches(value, name) for name in accepted_types
    ):
        return f"{path}: expected type {declared_type!r}"
    return None


def _shape_errors(value: Any, schema: Mapping[str, Any], path: str) -> list[str]:
    errors = _validate_const_enum(value, schema, path)
    if isinstance(value, str):
        errors.extend(_validate_string(value, schema, path))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        errors.extend(_validate_number(value, schema, path))
    if isinstance(value, Mapping):
        errors.extend(_validate_object(value, schema, path))
    if _is_array(value):
        errors.extend(_validate_array(value, schema, path))
    return errors


def validate_instance(value: Any, schema: Mapping[str, Any], path: str = "$") -> list[str]:
    """Validate the JSON-Schema subset used by AQG's versioned contracts."""
    type_error = _type_error(value, schema, path)
    return [type_error] if type_error is not None else _shape_errors(value, schema, path)


def load_named_schema(root: Path, name: str) -> dict[str, Any]:
    if not SCHEMA_NAME_RE.fullmatch(name):
        raise ConfigurationError(f"unsafe schema contract name: {name!r}")
    path = root / "quality" / "schemas" / f"{name}.schema.json"
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"schema contract does not exist: {name}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"cannot read schema contract {name}: {exc}") from exc
    if not isinstance(schema, dict):
        raise ConfigurationError(f"schema contract {name} must contain an object")
    return schema


def validate_named_schema(root: Path, name: str, value: Any) -> list[str]:
    return validate_instance(value, load_named_schema(root, name))


def validate_document_path(root: Path, name: str, document: Path) -> list[str]:
    """Validate a JSON document file against one published AQG contract."""
    try:
        value = json.loads(document.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigurationError(f"JSON contract document does not exist: {document}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"cannot read JSON contract document {document}: {exc}") from exc
    return validate_named_schema(root, name, value)


def require_document_contract(root: Path, name: str, document: Path) -> None:
    """Fail closed when a persisted document violates its named contract."""
    errors = validate_document_path(root, name, document)
    if errors:
        raise ConfigurationError(f"{name} contract violations: {'; '.join(errors)}")
