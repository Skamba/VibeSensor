"""Shared JSON type aliases and runtime narrowing helpers."""

from __future__ import annotations

from typing import TypeGuard

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
type JsonObject = dict[str, JsonValue]
type JsonArray = list[JsonValue]
type JsonSchemaScalar = JsonScalar

# OpenAPI -> TypeScript generation cannot represent recursive component aliases
# safely here, so keep the schema-facing JSON shape bounded to the nesting depth
# used by the persisted analysis/history payloads.
type JsonSchemaLeafObject = dict[str, JsonSchemaScalar]
type JsonSchemaNestedValue = (
    JsonSchemaScalar | JsonSchemaLeafObject | list[JsonSchemaScalar | JsonSchemaLeafObject]
)
type JsonSchemaNestedObject = dict[str, JsonSchemaNestedValue]
type JsonSchemaValue = (
    JsonSchemaNestedValue
    | JsonSchemaNestedObject
    | list[JsonSchemaNestedValue | JsonSchemaNestedObject]
)
type JsonSchemaObject = dict[str, JsonSchemaValue]

__all__ = [
    "JsonArray",
    "JsonObject",
    "JsonSchemaLeafObject",
    "JsonSchemaNestedObject",
    "JsonSchemaNestedValue",
    "JsonSchemaObject",
    "JsonSchemaScalar",
    "JsonSchemaValue",
    "JsonScalar",
    "JsonValue",
    "is_json_array",
    "is_json_object",
]


def is_json_object(value: object) -> TypeGuard[JsonObject]:
    """Narrow *value* to a JSON object shape."""
    return isinstance(value, dict)


def is_json_array(value: object) -> TypeGuard[JsonArray]:
    """Narrow *value* to a JSON array shape."""
    return isinstance(value, list)
