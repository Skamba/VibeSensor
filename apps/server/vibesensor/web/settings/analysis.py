"""Analysis-settings routes for the active car profile."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.settings.analysis_settings_codec import (
    analysis_settings_snapshot_to_metadata,
)
from vibesensor.settings.settings_types import analysis_settings_payload_from_mapping
from vibesensor.web._helpers import OpenAPIResponses
from vibesensor.web.error_boundary import http_exception_for_value_error
from vibesensor.web.models.settings import (
    AnalysisSettingsRequest,
    AnalysisSettingsResponse,
)
from vibesensor.web.settings.dependencies import AnalysisSettingsRouteDeps

_SET_ANALYSIS_SETTINGS_RESPONSES: OpenAPIResponses = {
    400: {"description": "Analysis settings are invalid or no active car is configured."},
}


def create_analysis_settings_routes(deps: AnalysisSettingsRouteDeps) -> APIRouter:
    """Create routes for active-car analysis settings."""

    router = APIRouter(tags=["settings"])

    @router.get("/api/settings/analysis", response_model=AnalysisSettingsResponse)
    async def get_analysis_settings() -> AnalysisSettingsResponse:
        """Return the validated analysis settings derived from the active car profile."""

        return _analysis_settings_response(deps.analysis_settings.analysis_settings_snapshot())

    @router.put(
        "/api/settings/analysis",
        response_model=AnalysisSettingsResponse,
        responses=_SET_ANALYSIS_SETTINGS_RESPONSES,
    )
    async def set_analysis_settings(
        req: AnalysisSettingsRequest,
    ) -> AnalysisSettingsResponse:
        """Update analysis-specific car aspects such as tire geometry and drivetrain ratios."""

        changes = analysis_settings_payload_from_mapping(req.model_dump(exclude_none=True))
        if changes:
            try:
                await asyncio.to_thread(
                    deps.analysis_settings.update_active_car_aspects,
                    changes,
                )
            except ValueError as exc:
                raise http_exception_for_value_error(exc, status_code=400) from exc
        return _analysis_settings_response(deps.analysis_settings.analysis_settings_snapshot())

    return router


def _analysis_settings_response(snapshot: AnalysisSettingsSnapshot) -> AnalysisSettingsResponse:
    return AnalysisSettingsResponse.model_validate(analysis_settings_snapshot_to_metadata(snapshot))
