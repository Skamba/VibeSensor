"""Domain route bundles for the HTTP adapter surface."""

from __future__ import annotations

from fastapi import APIRouter

from vibesensor.adapters.http.car_library import create_car_library_routes
from vibesensor.adapters.http.clients import create_client_routes
from vibesensor.adapters.http.dependencies import (
    HealthDeps,
    HistoryDeps,
    LiveDeps,
    SettingsDeps,
    UpdateDeps,
)
from vibesensor.adapters.http.health import create_health_routes
from vibesensor.adapters.http.history import create_history_routes
from vibesensor.adapters.http.recording import create_recording_routes
from vibesensor.adapters.http.settings import create_settings_routes
from vibesensor.adapters.http.updates import create_update_routes
from vibesensor.adapters.http.websocket import create_websocket_routes

__all__ = [
    "create_health_route_bundle",
    "create_history_route_bundle",
    "create_live_route_bundle",
    "create_settings_route_bundle",
    "create_update_route_bundle",
]


def create_health_route_bundle(services: HealthDeps) -> APIRouter:
    """Compose the runtime health routes."""
    router = APIRouter()
    router.include_router(
        create_health_routes(
            services.processing_loop_state,
            services.health_state,
            services.processor,
            services.registry,
            services.run_recorder,
        ),
    )
    return router


def create_settings_route_bundle(services: SettingsDeps) -> APIRouter:
    """Compose settings and reference-data routes."""
    router = APIRouter()
    router.include_router(
        create_settings_routes(
            services.car_settings,
            services.analysis_settings,
            services.ui_preferences,
            services.speed_source_service,
            services.speed_status_service,
            services.obd_admin_service,
        ),
    )
    router.include_router(create_car_library_routes())
    return router


def create_live_route_bundle(services: LiveDeps) -> APIRouter:
    """Compose operator-facing live runtime routes."""
    router = APIRouter()
    router.include_router(
        create_client_routes(
            services.registry,
            services.control_plane,
            services.sensor_metadata_store,
            services.processor,
        ),
    )
    router.include_router(create_recording_routes(services.run_recorder))
    router.include_router(create_websocket_routes(services.ws_hub))
    return router


def create_history_route_bundle(services: HistoryDeps) -> APIRouter:
    """Compose persisted history, report, and export routes."""
    router = APIRouter()
    router.include_router(
        create_history_routes(
            run_service=services.run_service,
            report_service=services.report_service,
            export_service=services.export_service,
        ),
    )
    return router


def create_update_route_bundle(services: UpdateDeps) -> APIRouter:
    """Compose software update and ESP flash routes."""
    router = APIRouter()
    router.include_router(
        create_update_routes(
            services.update_manager,
            services.esp_flash_manager,
        ),
    )
    return router
