"""Route package – assembles domain-specific sub-routers into one APIRouter.

Each sub-module defines a ``create_*_routes(...)`` function that returns
an ``APIRouter`` with endpoints scoped to a single domain.  This package
combines them so that ``app.py`` only needs::

    from .routes import create_router

Route modules receive only the specific services they need, not the full
``RuntimeState``, reducing coupling between route code and the runtime
coordinator.
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


def create_router(state: RuntimeState) -> APIRouter:
    """Assemble all domain-specific route groups into one router."""
    router = APIRouter()
    ingress = getattr(state, "ingress", None)
    operations = getattr(state, "operations", None)
    platform = getattr(state, "platform", None)

    registry = ingress.registry if ingress is not None else state.registry
    processor = ingress.processor if ingress is not None else state.processor
    control_plane = ingress.control_plane if ingress is not None else state.control_plane

    settings_store = operations.settings_store if operations is not None else state.settings_store
    gps_monitor = operations.gps_monitor if operations is not None else state.gps_monitor
    analysis_settings = (
        operations.analysis_settings if operations is not None else state.analysis_settings
    )
    metrics_logger = operations.metrics_logger if operations is not None else state.metrics_logger
    live_diagnostics = (
        operations.live_diagnostics if operations is not None else state.live_diagnostics
    )

    history_db = platform.history_db if platform is not None else state.history_db
    ws_hub = platform.ws_hub if platform is not None else state.ws_hub
    update_manager = platform.update_manager if platform is not None else state.update_manager
    esp_flash_manager = (
        platform.esp_flash_manager if platform is not None else state.esp_flash_manager
    )

    router.include_router(create_health_routes(state.loop_state, processor))
    router.include_router(
        create_settings_routes(
            settings_store,
            gps_monitor,
            analysis_settings,
            state.apply_car_settings,
            state.apply_speed_source_settings,
        )
    )
    router.include_router(
        create_client_routes(
            registry,
            control_plane,
            settings_store,
        )
    )
    router.include_router(
        create_recording_routes(
            metrics_logger,
            live_diagnostics,
        )
    )
    router.include_router(create_history_routes(history_db))
    router.include_router(create_websocket_routes(ws_hub))
    router.include_router(create_update_routes(update_manager, esp_flash_manager))
    router.include_router(create_car_library_routes())
    router.include_router(create_debug_routes(processor))
    return router
