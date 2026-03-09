"""Service construction and wiring.

Bootstrap now orchestrates focused runtime builders instead of acting as a
monolithic composition root.
"""

from __future__ import annotations

from .config import AppConfig
from .runtime import (
    RuntimeState,
    build_runtime_state,
)
from .runtime.builders import (
    build_diagnostics_subsystem,
    build_ingress_subsystem,
    build_persistence_subsystem,
    build_processing_subsystem,
    build_route_services,
    build_settings_subsystem,
    build_update_subsystem,
    build_websocket_subsystem,
    resolve_accel_scale_g_per_lsb,
)


def build_services(config: AppConfig) -> RuntimeState:
    """Construct all services and return a wired RuntimeState."""
    accel_scale_g_per_lsb = resolve_accel_scale_g_per_lsb(config)
    persistence = build_persistence_subsystem(config=config)
    ingress = build_ingress_subsystem(
        config=config,
        persistence=persistence,
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
    )
    settings = build_settings_subsystem(
        persistence=persistence,
        gps_enabled=config.gps.gps_enabled,
    )
    persistence.bind_history_services(settings.settings_store)
    diagnostics = build_diagnostics_subsystem(
        config=config,
        ingress=ingress,
        settings=settings,
        persistence=persistence,
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
    )
    updates = build_update_subsystem(config=config)
    processing = build_processing_subsystem(config=config, ingress=ingress)
    websocket = build_websocket_subsystem(
        config=config,
        ingress=ingress,
        settings=settings,
    )
    runtime = build_runtime_state(
        config=config,
        ingress=ingress,
        settings=settings,
        diagnostics=diagnostics,
        persistence=persistence,
        updates=updates,
        processing=processing,
        websocket=websocket,
        routes=build_route_services(
            ingress=ingress,
            settings=settings,
            diagnostics=diagnostics,
            persistence=persistence,
            updates=updates,
            processing=processing,
            websocket=websocket,
        ),
    )
    settings.apply_car_settings()
    settings.apply_speed_source_settings()
    return runtime
