"""Storage JSON codec for the persisted-analysis value object."""

from __future__ import annotations

from copy import deepcopy

from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.persisted_analysis import (
    PERSISTED_ANALYSIS_SCHEMA_VERSION,
    STORAGE_SCHEMA_VERSION_KEY,
    PersistedAnalysis,
)

__all__ = [
    "persisted_analysis_from_storage_json_object",
    "persisted_analysis_to_storage_json_object",
]


def persisted_analysis_from_storage_json_object(payload: JsonObject) -> PersistedAnalysis:
    """Build from storage JSON, validating and stripping the schema-version field."""

    normalized = deepcopy(payload)
    raw_version = normalized.pop(STORAGE_SCHEMA_VERSION_KEY, None)
    if raw_version != PERSISTED_ANALYSIS_SCHEMA_VERSION:
        raise ValueError(f"Unsupported persisted analysis schema version: {raw_version!r}")
    return PersistedAnalysis.from_json_object(normalized)


def persisted_analysis_to_storage_json_object(model: PersistedAnalysis) -> JsonObject:
    """Return a storage payload with the persisted-analysis schema version attached."""

    payload = model.to_json_object()
    payload[STORAGE_SCHEMA_VERSION_KEY] = PERSISTED_ANALYSIS_SCHEMA_VERSION
    return payload
