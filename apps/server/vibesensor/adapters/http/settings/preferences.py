"""UI language and unit preference routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from vibesensor.adapters.http._helpers import OpenAPIResponses
from vibesensor.adapters.http.error_boundary import http_exception_for_value_error
from vibesensor.adapters.http.models import (
    LanguageRequest,
    LanguageResponse,
    SpeedUnitRequest,
    SpeedUnitResponse,
)
from vibesensor.adapters.http.settings.dependencies import UiPreferencesRouteDeps

_SET_LANGUAGE_RESPONSES: OpenAPIResponses = {
    400: {"description": "Unsupported language code."},
}

_SET_SPEED_UNIT_RESPONSES: OpenAPIResponses = {
    400: {"description": "Unsupported speed unit."},
}


def create_ui_preferences_routes(deps: UiPreferencesRouteDeps) -> APIRouter:
    """Create routes for UI language and speed-unit preferences."""

    router = APIRouter(tags=["settings"])

    @router.get("/api/settings/language", response_model=LanguageResponse)
    async def get_language() -> LanguageResponse:
        """Return the currently selected dashboard language code."""

        return LanguageResponse(language=deps.ui_preferences.language)

    @router.put(
        "/api/settings/language",
        response_model=LanguageResponse,
        responses=_SET_LANGUAGE_RESPONSES,
    )
    async def set_language(req: LanguageRequest) -> LanguageResponse:
        """Update the dashboard language used by the local UI."""

        try:
            language = await asyncio.to_thread(
                deps.ui_preferences.set_language,
                req.language,
            )
        except ValueError as exc:
            raise http_exception_for_value_error(exc, status_code=400) from exc
        return LanguageResponse(language=language)

    @router.get("/api/settings/speed-unit", response_model=SpeedUnitResponse)
    async def get_speed_unit() -> SpeedUnitResponse:
        """Return the speed unit currently used for UI display and input."""

        return SpeedUnitResponse(speed_unit=deps.ui_preferences.speed_unit)

    @router.put(
        "/api/settings/speed-unit",
        response_model=SpeedUnitResponse,
        responses=_SET_SPEED_UNIT_RESPONSES,
    )
    async def set_speed_unit(req: SpeedUnitRequest) -> SpeedUnitResponse:
        """Update the speed unit used for UI display and manual speed entry."""

        try:
            unit = await asyncio.to_thread(
                deps.ui_preferences.set_speed_unit,
                req.speed_unit,
            )
        except ValueError as exc:
            raise http_exception_for_value_error(exc, status_code=400) from exc
        return SpeedUnitResponse(speed_unit=unit)

    return router
