"""One declarative JSON codec for persisted frozen-dataclass contracts.

Frozen dataclasses that inherit :class:`JsonContract` are their own persisted
JSON shape *and* their own HTTP/OpenAPI schema. Pydantic derives the decoder,
encoder, and JSON schema from the dataclass field types, so contracts carry no
hand-written ``from_mapping``/``to_json_object`` bodies:

- decoding (``from_mapping``) validates field types in pydantic lax mode
  (unknown keys ignored, missing fields fall back to dataclass defaults) and
  then runs the dataclass ``__post_init__`` invariants;
- encoding (``to_json_object``) omits ``None`` values, so optional fields stay
  absent from persisted JSON; HTTP models embed contracts as
  ``Annotated[Contract, AsJsonObject]`` to serve that same JSON;
- the JSON schema marks every non-nullable field as required because encoding
  always emits it, and leaves nullable fields optional.

Invariant helpers below are shared by the contracts' ``__post_init__`` checks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from typing import Any, ClassVar, Self, cast

from pydantic import ConfigDict, SerializerFunctionWrapHandler, TypeAdapter, WrapSerializer

from vibesensor.common.json_types import JsonObject

__all__ = [
    "AsJsonObject",
    "JsonContract",
    "require_non_empty_text",
    "require_non_negative",
    "require_positive",
    "require_ratio",
]


def _schema_required_non_nullable(schema: dict[str, Any], cls: type) -> None:
    properties: dict[str, dict[str, Any]] = schema.get("properties", {})
    for prop in properties.values():
        prop.pop("default", None)
    required = [
        field.name
        for field in fields(cls)
        if field.name in properties and not _nullable(properties[field.name])
    ]
    if required:
        schema["required"] = required
    else:
        schema.pop("required", None)


def _nullable(prop: Mapping[str, Any]) -> bool:
    return any(option.get("type") == "null" for option in prop.get("anyOf", ()))


_ADAPTERS: dict[type, TypeAdapter[Any]] = {}


def _adapter(cls: type) -> TypeAdapter[Any]:
    adapter = _ADAPTERS.get(cls)
    if adapter is None:
        adapter = _ADAPTERS[cls] = TypeAdapter(cls)
    return adapter


class JsonContract:
    """Mixin that gives a frozen dataclass its pydantic-derived JSON codec."""

    __slots__ = ()
    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(
        extra="ignore",
        json_schema_extra=cast(Any, _schema_required_non_nullable),
    )

    def to_json_object(self) -> JsonObject:
        """Encode this contract as a JSON object without ``None`` values."""
        return cast(
            JsonObject,
            _adapter(type(self)).dump_python(self, mode="json", exclude_none=True),
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> Self:
        """Decode one JSON object; raises ``ValueError`` on invalid payloads."""
        return cast(Self, _adapter(cls).validate_python(data))


# Pydantic takes a serializer's output schema from its return annotation; leaving
# it unannotated keeps the contract's own schema in OpenAPI.
def _serialize_as_json_object(  # type: ignore[no-untyped-def]
    contract: JsonContract,
    _handler: SerializerFunctionWrapHandler,
):
    return contract.to_json_object()


AsJsonObject = WrapSerializer(_serialize_as_json_object)
"""Annotate a ``JsonContract`` field inside a pydantic/HTTP model with this so the
response carries exactly the persisted JSON (``None`` fields omitted)."""


def require_non_empty_text(contract: object, *field_names: str) -> None:
    """Raise ``ValueError`` unless each named field is a non-blank string."""
    for name in field_names:
        value = getattr(contract, name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")


def require_non_negative(contract: object, *field_names: str) -> None:
    """Raise ``ValueError`` when a named numeric field is negative (``None`` passes)."""
    for name in field_names:
        value = getattr(contract, name)
        if value is not None and value < 0:
            raise ValueError(f"{name} must be >= 0")


def require_positive(contract: object, *field_names: str) -> None:
    """Raise ``ValueError`` unless each named numeric field is > 0."""
    for name in field_names:
        if getattr(contract, name) <= 0:
            raise ValueError(f"{name} must be > 0")


def require_ratio(contract: object, *field_names: str) -> None:
    """Raise ``ValueError`` when a named field is outside [0, 1] (``None`` passes)."""
    for name in field_names:
        value = getattr(contract, name)
        if value is not None and not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be in [0, 1]")
