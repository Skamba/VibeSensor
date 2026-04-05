"""Top-level composition root for HTTP route bundles."""

from __future__ import annotations

from fastapi import APIRouter

from vibesensor.adapters.http.dependencies import RouterDeps
from vibesensor.adapters.http.route_bundles import (
    create_health_route_bundle,
    create_history_route_bundle,
    create_live_route_bundle,
    create_settings_route_bundle,
    create_update_route_bundle,
)

__all__ = ["create_router"]


def create_router(services: RouterDeps) -> APIRouter:
    """Assemble the application HTTP router from domain route bundles."""
    router = APIRouter()
    router.include_router(create_health_route_bundle(services.health))
    router.include_router(create_settings_route_bundle(services.settings))
    router.include_router(create_live_route_bundle(services.live))
    router.include_router(create_history_route_bundle(services.history))
    router.include_router(create_update_route_bundle(services.updates))
    return router
