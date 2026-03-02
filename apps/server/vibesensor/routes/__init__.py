"""Route package – assembles domain-specific sub-routers into one APIRouter.

Each sub-module defines a ``create_*_routes(state)`` function that returns
an ``APIRouter`` with endpoints scoped to a single domain.  This package
combines them so that ``app.py`` only needs::

    from .routes import create_router

The old monolithic ``api.py`` is preserved as a backward-compatibility
re-export wrapper so existing test imports continue to work.
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
    from ..app import RuntimeState


def create_router(state: RuntimeState) -> APIRouter:
    """Assemble all domain-specific route groups into one router."""
    router = APIRouter()
    router.include_router(create_health_routes(state))
    router.include_router(create_settings_routes(state))
    router.include_router(create_client_routes(state))
    router.include_router(create_recording_routes(state))
    router.include_router(create_history_routes(state))
    router.include_router(create_websocket_routes(state))
    router.include_router(create_update_routes(state))
    router.include_router(create_car_library_routes(state))
    router.include_router(create_debug_routes(state))
    return router
