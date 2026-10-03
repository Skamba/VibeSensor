"""UI language and unit preference routes."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter

from vibesensor.settings.settings_types import LanguageCode, SpeedUnitCode
from vibesensor.web.models.settings import (
    LanguageRequest,
    LanguageResponse,
    SpeedUnitRequest,
    SpeedUnitResponse,
)

if TYPE_CHECKING:
    from vibesensor.settings.ui_preferences import UiPreferencesService


def create_ui_preferences_routes(ui_preferences: UiPreferencesService) -> APIRouter:
    """Create routes for UI language and speed-unit preferences."""

    router = APIRouter(tags=["settings"])

    @router.get("/api/settings/language", response_model=LanguageResponse)
    async def get_language() -> LanguageResponse:
        """Return the currently selected dashboard language code."""

        return LanguageResponse.model_validate(language_response_payload(ui_preferences.language))

    @router.put("/api/settings/language", response_model=LanguageResponse)
    async def set_language(req: LanguageRequest) -> LanguageResponse:
        """Update the dashboard language used by the local UI."""

        language = await asyncio.to_thread(ui_preferences.set_language, req.language)
        return LanguageResponse.model_validate(language_response_payload(language))

    @router.get("/api/settings/speed-unit", response_model=SpeedUnitResponse)
    async def get_speed_unit() -> SpeedUnitResponse:
        """Return the speed unit currently used for UI display and input."""

        return SpeedUnitResponse.model_validate(
            speed_unit_response_payload(ui_preferences.speed_unit)
        )

    @router.put("/api/settings/speed-unit", response_model=SpeedUnitResponse)
    async def set_speed_unit(req: SpeedUnitRequest) -> SpeedUnitResponse:
        """Update the speed unit used for UI display and manual speed entry."""

        unit = await asyncio.to_thread(ui_preferences.set_speed_unit, req.speed_unit)
        return SpeedUnitResponse.model_validate(speed_unit_response_payload(unit))

    return router


def language_response_payload(language: LanguageCode) -> dict[str, object]:
    """Project the active language code into the HTTP response shape."""

    return {"language": language}


def speed_unit_response_payload(speed_unit: SpeedUnitCode) -> dict[str, object]:
    """Project the active speed-unit code into the HTTP response shape."""

    return {"speed_unit": speed_unit}


__all__ = ["language_response_payload", "speed_unit_response_payload"]
