"""Base classes and aliases for HTTP API Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from vibesensor.common.json_types import JsonSchemaObject, JsonSchemaValue

type ApiPayloadObject = JsonSchemaObject
type ApiPayloadValue = JsonSchemaValue


class _FrozenBase(BaseModel):
    """Immutable base for request models (constructed once, never mutated)."""

    model_config = ConfigDict(frozen=True)


class _StrictBase(BaseModel):
    """Base for response models that must reject undocumented extra fields."""

    model_config = ConfigDict(extra="forbid")
