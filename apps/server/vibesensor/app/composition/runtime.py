from __future__ import annotations

from vibesensor.adapters.http.dependencies import RouterDeps, UpdateDeps
from vibesensor.adapters.persistence.history_db import HistoryPersistenceAdapters
from vibesensor.app.composition.history import HistoryServiceBundle
from vibesensor.app.composition.live import LiveRuntimeBundle
from vibesensor.app.composition.settings import RuntimeSettingsDeps, SettingsServiceBundle
from vibesensor.app.composition.speed import SpeedRuntimeBundle
from vibesensor.app.config_schema import AppConfig
from vibesensor.app.runtime_state import RuntimeState
from vibesensor.infra.runtime.health_state import RuntimeHealthState


def build_lifecycle_state(
    *,
    config: AppConfig,
    health_state: RuntimeHealthState,
    history: HistoryPersistenceAdapters,
    speed_runtime: SpeedRuntimeBundle,
    runtime_settings: RuntimeSettingsDeps,
    live_runtime: LiveRuntimeBundle,
    updates: UpdateDeps,
) -> RuntimeState:
    """Build the lifecycle-focused runtime dependency bundle."""

    return RuntimeState(
        config=config,
        registry=live_runtime.registry,
        processor=live_runtime.processor,
        control_plane=live_runtime.control_plane,
        worker_pool=live_runtime.worker_pool,
        settings_reader=runtime_settings.settings_reader,
        gps_monitor=speed_runtime.gps_monitor,
        obd_runner=speed_runtime.obd_runtime.connection.runner,
        history_db=history.lifecycle,
        processing_loop_state=live_runtime.processing_loop_state,
        health_state=health_state,
        ingest_diagnostics=live_runtime.ingest_diagnostics,
        processing_loop=live_runtime.processing_loop,
        ws_hub=live_runtime.ws_hub,
        ws_broadcast=live_runtime.ws_broadcast,
        run_recorder=live_runtime.run_recorder,
        update_manager=updates.update_manager,
        esp_flash_manager=updates.esp_flash_manager,
    )


def build_router_deps(
    *,
    health_state: RuntimeHealthState,
    speed_runtime: SpeedRuntimeBundle,
    settings_services: SettingsServiceBundle,
    history_services: HistoryServiceBundle,
    live_runtime: LiveRuntimeBundle,
    updates: UpdateDeps,
) -> RouterDeps:
    """Build the grouped HTTP route dependency bundle."""

    settings = settings_services.http_settings_deps(
        speed_status_service=speed_runtime.speed_services.observation,
        obd_admin_service=speed_runtime.speed_services.admin,
    )
    return RouterDeps(
        health=live_runtime.http_health_deps(health_state=health_state),
        settings=settings,
        live=live_runtime.http_live_deps(
            sensor_metadata_store=settings_services.sensor_metadata_store,
        ),
        history=history_services.http_deps(),
        updates=updates,
    )
