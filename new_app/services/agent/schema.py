"""Minimal JSON-schema validation used for agent structured outputs."""

from __future__ import annotations

from typing import Any


def validate_json_schema(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    if not schema:
        return errors
    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(value, item) for item in types):
            errors.append(f"{path}: expected {expected}, got {type(value).__name__}")
            return errors
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} not in enum")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if minimum is not None and value < minimum:
            errors.append(f"{path}: {value} < minimum {minimum}")
        if maximum is not None and value > maximum:
            errors.append(f"{path}: {value} > maximum {maximum}")
    if isinstance(value, dict):
        required = schema.get("required") or []
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required field {key}")
        properties = schema.get("properties") or {}
        for key, subschema in properties.items():
            if key in value and isinstance(subschema, dict):
                errors.extend(validate_json_schema(value[key], subschema, f"{path}.{key}"))
    if isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(value):
                errors.extend(validate_json_schema(item, items, f"{path}[{index}]"))
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if min_items is not None and len(value) < min_items:
            errors.append(f"{path}: fewer than {min_items} items")
        if max_items is not None and len(value) > max_items:
            errors.append(f"{path}: more than {max_items} items")
    return errors


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True
