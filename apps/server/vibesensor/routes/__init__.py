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
    router.include_router(create_health_routes(state.loop_state, state.processor))
    router.include_router(
        create_settings_routes(
            state.settings_store,
            state.gps_monitor,
            state.analysis_settings,
            state.apply_car_settings,
            state.apply_speed_source_settings,
        )
    )
    router.include_router(
        create_client_routes(state.registry, state.control_plane, state.settings_store)
    )
    router.include_router(create_recording_routes(state.metrics_logger, state.live_diagnostics))
    router.include_router(create_history_routes(state.history_db))
    router.include_router(create_websocket_routes(state.ws_hub))
    router.include_router(create_update_routes(state.update_manager, state.esp_flash_manager))
    router.include_router(create_car_library_routes())
    router.include_router(create_debug_routes(state.processor))
    return router
