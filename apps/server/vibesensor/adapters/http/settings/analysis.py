"""Analysis-settings routes for the active car profile."""

from __future__ import annotations

import asyncio
from dataclasses import asdict

from fastapi import APIRouter

from vibesensor.adapters.http._helpers import OpenAPIResponses
from vibesensor.adapters.http.analysis_settings_request_codec import (
    analysis_settings_payload_from_request,
)
from vibesensor.adapters.http.error_boundary import http_exception_for_value_error
from vibesensor.adapters.http.models import (
    AnalysisSettingsRequest,
    AnalysisSettingsResponse,
)
from vibesensor.adapters.http.settings.dependencies import AnalysisSettingsRouteDeps

_SET_ANALYSIS_SETTINGS_RESPONSES: OpenAPIResponses = {
    400: {"description": "Analysis settings are invalid or no active car is configured."},
}


def _analysis_settings_response(
    deps: AnalysisSettingsRouteDeps,
) -> AnalysisSettingsResponse:
    return AnalysisSettingsResponse.model_validate(
        asdict(deps.analysis_settings.analysis_settings_snapshot())
    )


def create_analysis_settings_routes(deps: AnalysisSettingsRouteDeps) -> APIRouter:
    """Create routes for active-car analysis settings."""

    router = APIRouter(tags=["settings"])

    @router.get("/api/settings/analysis", response_model=AnalysisSettingsResponse)
    async def get_analysis_settings() -> AnalysisSettingsResponse:
        """Return the validated analysis settings derived from the active car profile."""

        return _analysis_settings_response(deps)

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
            changes = analysis_settings_payload_from_request(req)
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
        return _analysis_settings_response(deps)

    return router
