"""Shared boundary helpers for analysis-settings HTTP payloads."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.shared.boundaries.codecs.analysis_settings import (
    analysis_settings_snapshot_to_metadata,
)
from vibesensor.shared.types.settings_types import (
    AnalysisSettingsPayload,
    analysis_settings_payload_from_mapping,
)


def analysis_settings_update_payload_from_mapping(
    payload: Mapping[str, object],
) -> AnalysisSettingsPayload:
    """Project a request-like mapping into the canonical analysis update payload."""

    filtered: dict[str, float | str] = {}
    for key, value in payload.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            filtered[key] = float(value)
        elif key == "default_axle_for_speed" and value in {"front", "rear", "average"}:
            filtered[key] = value
    return analysis_settings_payload_from_mapping(filtered)


def analysis_settings_response_payload(snapshot: AnalysisSettingsSnapshot) -> Mapping[str, object]:
    """Project the typed analysis snapshot into the HTTP response shape."""

    return analysis_settings_snapshot_to_metadata(snapshot)


__all__ = ["analysis_settings_response_payload", "analysis_settings_update_payload_from_mapping"]
