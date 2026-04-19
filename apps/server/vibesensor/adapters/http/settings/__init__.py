"""Settings route package – compose bounded-context micro-routers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from vibesensor.adapters.http.settings.analysis import create_analysis_settings_routes
from vibesensor.adapters.http.settings.cars import create_car_settings_routes
from vibesensor.adapters.http.settings.dependencies import (
    AnalysisSettingsRouteDeps,
    CarSettingsRouteDeps,
    ObdAdminRouteDeps,
    SpeedSourceRouteDeps,
    UiPreferencesRouteDeps,
)
from vibesensor.adapters.http.settings.obd import create_obd_admin_routes
from vibesensor.adapters.http.settings.preferences import create_ui_preferences_routes
from vibesensor.adapters.http.settings.speed_source import create_speed_source_routes

if TYPE_CHECKING:
    from vibesensor.adapters.http.dependencies import (
        ObdAdminServiceProtocol,
        SettingsSpeedServiceProtocol,
        SpeedSourceSettingsServiceProtocol,
    )
    from vibesensor.shared.ports import (
        AnalysisSettingsStore,
        CarSettingsStore,
        UiPreferencesStore,
    )


def create_settings_routes(
    car_settings: CarSettingsStore,
    analysis_settings: AnalysisSettingsStore,
    ui_preferences: UiPreferencesStore,
    speed_source_service: SpeedSourceSettingsServiceProtocol,
    speed_status_service: SettingsSpeedServiceProtocol,
    obd_admin_service: ObdAdminServiceProtocol,
) -> APIRouter:
    """Compose the bounded-context settings micro-routers."""
    router = APIRouter()
    router.include_router(
        create_car_settings_routes(
            CarSettingsRouteDeps(car_settings=car_settings),
        ),
    )
    router.include_router(
        create_speed_source_routes(
            SpeedSourceRouteDeps(
                speed_source_service=speed_source_service,
                speed_status_service=speed_status_service,
            ),
        ),
    )
    router.include_router(
        create_obd_admin_routes(
            ObdAdminRouteDeps(
                speed_source_service=speed_source_service,
                speed_status_service=speed_status_service,
                obd_admin_service=obd_admin_service,
            ),
        ),
    )
    router.include_router(
        create_ui_preferences_routes(
            UiPreferencesRouteDeps(ui_preferences=ui_preferences),
        ),
    )
    router.include_router(
        create_analysis_settings_routes(
            AnalysisSettingsRouteDeps(analysis_settings=analysis_settings),
        ),
    )
    return router
