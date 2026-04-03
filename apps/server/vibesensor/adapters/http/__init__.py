"""Route package – assembles domain-specific sub-routers into one APIRouter.

Each sub-module defines a ``create_*_routes(...)`` function that returns
an ``APIRouter`` with endpoints scoped to a single domain.  This package
combines them so that ``app.py`` only needs::

    from vibesensor.adapters.http import create_router

Route modules receive only the specific services they need. The package-level
assembler accepts focused dependency groups instead of the full app runtime bag.
"""

from __future__ import annotations

from fastapi import APIRouter

from vibesensor.adapters.http.car_library import create_car_library_routes
from vibesensor.adapters.http.clients import create_client_routes
from vibesensor.adapters.http.debug import create_debug_routes
from vibesensor.adapters.http.dependencies import RouterDeps
from vibesensor.adapters.http.health import create_health_routes
from vibesensor.adapters.http.history import create_history_routes
from vibesensor.adapters.http.recording import create_recording_routes
from vibesensor.adapters.http.settings import create_settings_routes
from vibesensor.adapters.http.updates import create_update_routes
from vibesensor.adapters.http.websocket import create_websocket_routes


def create_router(services: RouterDeps) -> APIRouter:
    """Assemble all domain-specific route groups into one router."""
    router = APIRouter()
    router.include_router(
        create_health_routes(
            services.telemetry.processing_loop_state,
            services.telemetry.health_state,
            services.telemetry.processor,
            services.telemetry.registry,
            services.telemetry.run_recorder,
        ),
    )
    router.include_router(
        create_settings_routes(
            services.settings.settings_store,
            services.settings.speed_source_service,
            services.settings.speed_status_service,
            services.settings.obd_admin_service,
        ),
    )
    router.include_router(
        create_client_routes(
            services.telemetry.registry,
            services.telemetry.control_plane,
            services.settings.settings_store,
            services.telemetry.processor,
        ),
    )
    router.include_router(
        create_recording_routes(
            services.telemetry.run_recorder,
        ),
    )
    router.include_router(
        create_history_routes(
            run_service=services.history.run_service,
            report_service=services.history.report_service,
            export_service=services.history.export_service,
        ),
    )
    router.include_router(create_websocket_routes(services.telemetry.ws_hub))
    router.include_router(
        create_update_routes(
            services.updates.update_manager,
            services.updates.esp_flash_manager,
        ),
    )
    router.include_router(create_car_library_routes())
    router.include_router(create_debug_routes(services.telemetry.processor))
    return router
