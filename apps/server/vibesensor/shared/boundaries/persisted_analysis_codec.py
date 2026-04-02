"""Explicit translation boundary between summary and persisted-analysis contracts."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

from vibesensor.shared.types.history_analysis_contracts import AnalysisSummary
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.persisted_analysis import (
    PERSISTED_ANALYSIS_SCHEMA_VERSION,
    STORAGE_SCHEMA_VERSION_KEY,
    PersistedAnalysis,
)
from vibesensor.shared.types.persisted_analysis_contracts import PersistedAnalysisPayload

__all__ = [
    "persisted_analysis_from_json_object",
    "persisted_analysis_from_storage_json_object",
    "persisted_analysis_from_summary",
    "persisted_analysis_to_json_object",
    "persisted_analysis_to_storage_json_object",
    "persisted_analysis_to_summary",
]


def persisted_analysis_from_summary(summary: AnalysisSummary) -> PersistedAnalysis:
    """Translate a summary payload into the storage-owned persisted-analysis model."""
    return PersistedAnalysis(payload=deepcopy(summary))


def persisted_analysis_from_json_object(payload: JsonObject) -> PersistedAnalysis:
    """Build a persisted-analysis object from a raw in-memory JSON payload."""

    return PersistedAnalysis(payload=deepcopy(cast(PersistedAnalysisPayload, payload)))


def persisted_analysis_from_storage_json_object(payload: JsonObject) -> PersistedAnalysis:
    """Build from storage JSON, validating and stripping the schema-version field."""

    normalized = deepcopy(payload)
    raw_version = normalized.pop(STORAGE_SCHEMA_VERSION_KEY, 0)
    if raw_version not in (0, PERSISTED_ANALYSIS_SCHEMA_VERSION):
        raise ValueError(f"Unsupported persisted analysis schema version: {raw_version!r}")
    return persisted_analysis_from_json_object(normalized)


def persisted_analysis_to_summary(model: PersistedAnalysis) -> AnalysisSummary:
    """Translate a persisted-analysis model back into the outward summary shape."""

    return cast(AnalysisSummary, persisted_analysis_to_json_object(model))


def persisted_analysis_to_json_object(model: PersistedAnalysis) -> JsonObject:
    """Return a deep-copied JSON payload for in-memory consumers."""

    return cast(JsonObject, deepcopy(model.payload))


def persisted_analysis_to_storage_json_object(model: PersistedAnalysis) -> JsonObject:
    """Return a storage payload with the persisted-analysis schema version attached."""

    payload = persisted_analysis_to_json_object(model)
    payload[STORAGE_SCHEMA_VERSION_KEY] = PERSISTED_ANALYSIS_SCHEMA_VERSION
    return payload
