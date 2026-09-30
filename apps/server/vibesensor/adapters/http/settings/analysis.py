"""Analysis-settings routes for the active car profile."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from fastapi import APIRouter

from vibesensor.adapters.http._helpers import OpenAPIResponses
from vibesensor.adapters.http.error_boundary import http_exception_for_value_error
from vibesensor.adapters.http.models.settings import (
    AnalysisSettingsRequest,
    AnalysisSettingsResponse,
)
from vibesensor.adapters.http.settings.dependencies import AnalysisSettingsRouteDeps
from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.shared.boundaries.codecs.analysis_settings import (
    analysis_settings_snapshot_to_metadata,
)
from vibesensor.shared.types.settings_types import (
    AnalysisSettingsPayload,
    analysis_settings_payload_from_mapping,
)

_SET_ANALYSIS_SETTINGS_RESPONSES: OpenAPIResponses = {
    400: {"description": "Analysis settings are invalid or no active car is configured."},
}


def create_analysis_settings_routes(deps: AnalysisSettingsRouteDeps) -> APIRouter:
    """Create routes for active-car analysis settings."""

    router = APIRouter(tags=["settings"])

    @router.get("/api/settings/analysis", response_model=AnalysisSettingsResponse)
    async def get_analysis_settings() -> AnalysisSettingsResponse:
        """Return the validated analysis settings derived from the active car profile."""

        return AnalysisSettingsResponse.model_validate(
            analysis_settings_response_payload(deps.analysis_settings.analysis_settings_snapshot())
        )

    @router.put(
        "/api/settings/analysis",
        response_model=AnalysisSettingsResponse,
        responses=_SET_ANALYSIS_SETTINGS_RESPONSES,
    )
    async def set_analysis_settings(
        req: AnalysisSettingsRequest,
    ) -> AnalysisSettingsResponse:
        """Update analysis-specific car aspects such as tire geometry and drivetrain ratios."""

        try:
            changes = analysis_settings_update_payload_from_mapping(
                req.model_dump(exclude_none=True)
            )
        except ValueError as exc:
            raise http_exception_for_value_error(exc, status_code=400) from exc
        if changes:
            try:
                await asyncio.to_thread(
                    deps.analysis_settings.update_active_car_aspects,
                    changes,
                )
            except ValueError as exc:
                raise http_exception_for_value_error(exc, status_code=400) from exc
        return AnalysisSettingsResponse.model_validate(
            analysis_settings_response_payload(deps.analysis_settings.analysis_settings_snapshot())
        )

    return router


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
