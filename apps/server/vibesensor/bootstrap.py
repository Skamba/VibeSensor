"""Service construction and wiring.

Bootstrap orchestrates focused runtime builders instead of acting as a
monolithic composition root.
"""

from __future__ import annotations

from .config import AppConfig
from .esp_flash_manager import EspFlashManager
from .runtime import RuntimeState
from .runtime.builders import (
    build_ingress_subsystem,
    build_metrics_logger,
    build_persistence_subsystem,
    build_processing_subsystem,
    build_settings_subsystem,
    build_update_manager,
    build_websocket_subsystem,
    create_history_db,
    resolve_accel_scale_g_per_lsb,
)
from .runtime.lifecycle import LifecycleManager


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
    metrics_logger = build_metrics_logger(
        config=config,
        ingress=ingress,
        settings=settings,
        persistence=persistence,
        accel_scale_g_per_lsb=accel_scale_g_per_lsb,
    )
    update_manager = build_update_manager(config=config)
    esp_flash_manager = EspFlashManager()
    processing = build_processing_subsystem(config=config, ingress=ingress)
    websocket = build_websocket_subsystem(
        config=config,
        ingress=ingress,
        settings=settings,
    )
    runtime = RuntimeState(
        config=config,
        ingress=ingress,
        settings=settings,
        metrics_logger=metrics_logger,
        persistence=persistence,
        update_manager=update_manager,
        esp_flash_manager=esp_flash_manager,
        processing=processing,
        websocket=websocket,
        lifecycle=LifecycleManager(
            config=config,
            ingress=ingress,
            settings=settings,
            metrics_logger=metrics_logger,
            persistence=persistence,
            update_manager=update_manager,
            esp_flash_manager=esp_flash_manager,
            processing=processing,
            websocket=websocket,
        ),
    )
    settings.apply_car_settings()
    settings.apply_speed_source_settings()
    return runtime
