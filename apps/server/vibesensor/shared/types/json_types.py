"""Shared JSON type aliases and runtime narrowing helpers."""

from __future__ import annotations

from typing import TypeAlias, TypeGuard

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
JsonArray: TypeAlias = list[JsonValue]
JsonSchemaScalar: TypeAlias = JsonScalar

# OpenAPI -> TypeScript generation cannot represent recursive component aliases
# safely here, so keep the schema-facing JSON shape bounded to the nesting depth
# used by the persisted analysis/history payloads.
JsonSchemaLeafObject: TypeAlias = dict[str, JsonSchemaScalar]
JsonSchemaNestedValue: TypeAlias = (
    JsonSchemaScalar | JsonSchemaLeafObject | list[JsonSchemaScalar | JsonSchemaLeafObject]
)
JsonSchemaValue: TypeAlias = (
    JsonSchemaNestedValue | dict[str, JsonSchemaNestedValue] | list[JsonSchemaNestedValue]
)
JsonSchemaObject: TypeAlias = dict[str, JsonSchemaValue]

__all__ = [
    "JsonArray",
    "JsonObject",
    "JsonSchemaLeafObject",
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
