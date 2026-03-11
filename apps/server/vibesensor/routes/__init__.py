"""Route package – assembles domain-specific sub-routers into one APIRouter.

Each sub-module defines a ``create_*_routes(...)`` function that returns
an ``APIRouter`` with endpoints scoped to a single domain.  This package
combines them so that ``app.py`` only needs::

    from .routes import create_router

Route modules receive only the specific services they need. The package-level
assembler now depends on explicit route services instead of a broad runtime
facade.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from .car_library import create_car_library_routes
from .clients import create_client_routes
from .debug import create_debug_routes
from .health import create_health_routes
from .history import create_history_routes
from .recording import create_recording_routes
from .settings import create_settings_routes
from .updates import create_update_routes
from .websocket import create_websocket_routes

if TYPE_CHECKING:
    from ..runtime import RuntimeState


def create_router(services: RuntimeState) -> APIRouter:
    """Assemble all domain-specific route groups into one router."""
    router = APIRouter()
    router.include_router(
        create_health_routes(
            services.processing_loop_state,
            services.health_state,
            services.processor,
            services.registry,
            services.metrics_logger,
        ),
    )
    router.include_router(
        create_settings_routes(
            services.settings_store,
            services.gps_monitor,
            services.analysis_settings,
        ),
    )
    router.include_router(
        create_client_routes(
            services.registry,
            services.control_plane,
            services.settings_store,
            services.processor,
        ),
    )
    router.include_router(
        create_recording_routes(
            services.metrics_logger,
        ),
    )
    router.include_router(
        create_history_routes(
            run_service=services.run_service,
            report_service=services.report_service,
            export_service=services.export_service,
        ),
    )
    router.include_router(create_websocket_routes(services.ws_hub))
    router.include_router(
        create_update_routes(
            services.update_manager,
            services.esp_flash_manager,
        ),
    )
    router.include_router(create_car_library_routes())
    router.include_router(create_debug_routes(services.processor))
    return router
