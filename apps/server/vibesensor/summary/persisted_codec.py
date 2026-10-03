"""Storage JSON codec for the persisted-analysis value object."""

from __future__ import annotations

from copy import deepcopy

from vibesensor.common.json_types import JsonObject
from vibesensor.summary.persisted_analysis import (
    PERSISTED_ANALYSIS_SCHEMA_VERSION,
    STORAGE_SCHEMA_VERSION_KEY,
    PersistedAnalysis,
)

__all__ = [
    "persisted_analysis_from_storage_json_object",
    "persisted_analysis_to_storage_json_object",
]


# Analyses stored before the whole-run pipeline was removed carry these fields.
# Drop them on load so the outward contracts (which forbid unknown keys) and the
# report never see them.
_RETIRED_TOP_LEVEL_KEYS = (
    "whole_run_context_intervals",
    "whole_run_order_summaries",
    "whole_run_spatial_summaries",
    "whole_run_diagnosis_summaries",
)
_RETIRED_PREFIX = "whole_run_"


def persisted_analysis_from_storage_json_object(payload: JsonObject) -> PersistedAnalysis:
    """Build from storage JSON, validating and stripping the schema-version field."""

    normalized = deepcopy(payload)
    raw_version = normalized.pop(STORAGE_SCHEMA_VERSION_KEY, None)
    if raw_version != PERSISTED_ANALYSIS_SCHEMA_VERSION:
        raise ValueError(f"Unsupported persisted analysis schema version: {raw_version!r}")
    _drop_retired_whole_run_fields(normalized)
    return PersistedAnalysis.from_json_object(normalized)


def _drop_retired_whole_run_fields(payload: JsonObject) -> None:
    for key in _RETIRED_TOP_LEVEL_KEYS:
        payload.pop(key, None)
    metadata = payload.get("analysis_metadata")
    if isinstance(metadata, dict):
        for key in [key for key in metadata if key.startswith(_RETIRED_PREFIX)]:
            del metadata[key]
        metadata.pop("raw_capture_loss_policy_gate_whole_run", None)
    warnings = payload.get("warnings")
    if isinstance(warnings, list):
        payload["warnings"] = [
            warning
            for warning in warnings
            if not (
                isinstance(warning, dict)
                and str(warning.get("code", "")).startswith(_RETIRED_PREFIX)
            )
        ]


def persisted_analysis_to_storage_json_object(model: PersistedAnalysis) -> JsonObject:
    """Return a storage payload with the persisted-analysis schema version attached."""

    payload = model.to_json_object()
    payload[STORAGE_SCHEMA_VERSION_KEY] = PERSISTED_ANALYSIS_SCHEMA_VERSION
    return payload
