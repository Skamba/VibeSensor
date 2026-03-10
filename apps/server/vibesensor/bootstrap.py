"""Service construction and wiring.

Bootstrap orchestrates focused runtime builders instead of acting as a
monolithic composition root.
"""

from __future__ import annotations

from .config import AppConfig
from .runtime import (
    RuntimeState,
    build_runtime_state,
)
from .runtime.builders import (
    build_ingress_subsystem,
    build_persistence_subsystem,
    build_processing_subsystem,
    build_recording_subsystem,
    build_settings_subsystem,
    build_update_subsystem,
    build_websocket_subsystem,
    create_history_db,
    resolve_accel_scale_g_per_lsb,
)


def build_services(config: AppConfig) -> RuntimeState:
    """Construct all services and return a wired RuntimeState."""
    accel_scale_g_per_lsb = resolve_accel_scale_g_per_lsb(config)
    # Create DB first, then settings (needs DB), then persistence services
    # (needs both DB and SettingsStore) — single construction, no rebuild.
    history_db = create_history_db(config)
    settings = build_settings_subsystem(
        history_db=history_db,
        gps_enabled=config.gps.gps_enabled,
    )
    persistence = build_persistence_subsystem(
        history_db=history_db,
        settings_store=settings.settings_store,
    )
    ingress = build_ingress_subsystem(
        config=config,
        persistence=persistence,
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
    )
    recording = build_recording_subsystem(
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
        recording=recording,
        persistence=persistence,
        updates=updates,
        processing=processing,
        websocket=websocket,
    )
    settings.apply_car_settings()
    settings.apply_speed_source_settings()
    return runtime
