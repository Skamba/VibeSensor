"""Base classes and aliases for HTTP API Pydantic models."""

from __future__ import annotations

from typing import TypeAlias

from pydantic import BaseModel, ConfigDict

from vibesensor.shared.types.json_types import JsonSchemaObject, JsonSchemaValue

ApiPayloadObject: TypeAlias = JsonSchemaObject
ApiPayloadValue: TypeAlias = JsonSchemaValue


class _FrozenBase(BaseModel):
    """Immutable base for request models (constructed once, never mutated)."""

    model_config = ConfigDict(frozen=True)


class _StrictBase(BaseModel):
    """Base for response models that must reject undocumented extra fields."""

    model_config = ConfigDict(extra="forbid")


class _ExtraAllowBase(BaseModel):
    """Base for models that accept arbitrary extra fields."""

    model_config = ConfigDict(extra="allow")
