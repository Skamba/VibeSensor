"""Composition root: construct every runtime service from the loaded config."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.app.composition.history import build_history_deps, create_history_db
from vibesensor.app.composition.live import build_live_runtime
from vibesensor.app.composition.settings import build_settings_service_bundle
from vibesensor.app.composition.speed import build_speed_runtime
from vibesensor.app.composition.updates import build_update_deps
from vibesensor.app.config_schema import AppConfig
from vibesensor.app.lifecycle import LifecycleRuntime
from vibesensor.web.dependencies import RouterDeps
from vibesensor.web.health_state import RuntimeHealthState


@dataclass(slots=True)
class AppRuntime:
    """Everything ``create_app()`` needs: lifecycle-owned services plus HTTP route deps."""

    lifecycle: LifecycleRuntime
    router: RouterDeps


def build_runtime(config: AppConfig) -> AppRuntime:
    """Construct all services and return the app runtime bundle."""
    health_state = RuntimeHealthState()

    history = create_history_db(
        config,
        corruption_reporter=health_state.mark_db_corrupted,
    )
    speed_runtime = build_speed_runtime(config)
    settings_services = build_settings_service_bundle(
        snapshot_repository=history,
        speed_control=speed_runtime.speed_services.control,
    )
    runtime_settings = settings_services.runtime_deps()
    history_deps = build_history_deps(
        history=history,
        current_car_reader=settings_services.settings_reader,
    )
    live = build_live_runtime(
        config=config,
        history=history,
        speed_runtime=speed_runtime,
        runtime_settings=runtime_settings,
    )
    updates = build_update_deps(config)
    lifecycle = LifecycleRuntime(
        health_state=health_state,
        history_db_path=config.logging.history_db_path,
        udp_data_host=config.udp.data_host,
        udp_data_port=config.udp.data_port,
        registry=live.registry,
        processor=live.processor,
        ingest_diagnostics=live.ingest_diagnostics,
        control_plane=live.control_plane,
        processing_loop=live.processing_loop,
        ws_broadcaster=live.ws_broadcaster,
        run_recorder=live.run_recorder,
        gps_monitor=speed_runtime.gps_monitor,
        obd_runner=speed_runtime.obd,
        update_manager=updates.update_manager,
        esp_flash_manager=updates.esp_flash_manager,
        history_db=history,
    )
    router = RouterDeps(
        health=live.http_health_deps(health_state=health_state),
        settings=settings_services.http_settings_deps(
            speed_status_service=speed_runtime.speed_services.observation,
            obd_admin_service=speed_runtime.obd,
        ),
        live=live.http_live_deps(sensor_metadata_store=settings_services.sensor_metadata_store),
        history=history_deps,
        updates=updates,
    )
    settings_services.speed_source_service.sync_all()
    return AppRuntime(lifecycle=lifecycle, router=router)
