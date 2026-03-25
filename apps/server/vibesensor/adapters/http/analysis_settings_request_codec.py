"""HTTP adapter codec for analysis-settings update requests."""

from __future__ import annotations

from vibesensor.adapters.http.models.settings import AnalysisSettingsRequest
from vibesensor.shared.types.settings_types import (
    AnalysisSettingsPayload,
    analysis_settings_payload_from_mapping,
)


def analysis_settings_payload_from_request(
    request: AnalysisSettingsRequest,
) -> AnalysisSettingsPayload:
    """Project a partial HTTP request body into the internal settings payload."""
    return analysis_settings_payload_from_mapping(
        {
            key: float(value)
            for key, value in request.model_dump(exclude_none=True).items()
        }
    )
