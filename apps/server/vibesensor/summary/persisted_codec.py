"""Storage JSON codec for the persisted-analysis value object."""

from __future__ import annotations

from typing import cast

from vibesensor.common.json_types import JsonObject
from vibesensor.summary.contracts import AnalysisSummary
from vibesensor.summary.persisted_analysis import (
    PERSISTED_ANALYSIS_SCHEMA_VERSION,
    STORAGE_SCHEMA_VERSION_KEY,
    PersistedAnalysis,
)

__all__ = [
    "persisted_analysis_from_storage_json_object",
    "persisted_analysis_to_storage_json_object",
]


def persisted_analysis_from_storage_json_object(payload: JsonObject) -> PersistedAnalysis:
    """Build from storage JSON, validating and stripping the schema-version field.

    The result holds *payload*'s values without copying them (a long drive's
    analysis is millions of values), so pass a payload nothing else changes,
    such as one just decoded from storage.
    """

    normalized = dict(payload)
    raw_version = normalized.pop(STORAGE_SCHEMA_VERSION_KEY, None)
    if raw_version != PERSISTED_ANALYSIS_SCHEMA_VERSION:
        raise ValueError(f"Unsupported persisted analysis schema version: {raw_version!r}")
    return PersistedAnalysis(payload=cast("AnalysisSummary", normalized))


def persisted_analysis_to_storage_json_object(model: PersistedAnalysis) -> JsonObject:
    """Return a storage payload with the persisted-analysis schema version attached."""

    # A shallow copy: the storage payload is only serialised, never changed.
    return {
        **cast("JsonObject", model.payload),
        STORAGE_SCHEMA_VERSION_KEY: PERSISTED_ANALYSIS_SCHEMA_VERSION,
    }
