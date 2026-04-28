"""Focused tests for app-owned runtime composition helpers."""

from __future__ import annotations

from types import SimpleNamespace

from vibesensor.app.runtime_state import RuntimeState
from vibesensor.infra.runtime.health_state import RuntimeHealthState


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        logging=SimpleNamespace(
            history_db_path="/tmp/history.db",
            shutdown_analysis_timeout_s=12.5,
        ),
        udp=SimpleNamespace(
            data_host="0.0.0.0",
            data_port=9000,
            data_queue_maxsize=321,
        ),
        gps=SimpleNamespace(
            gpsd_host="gpsd.local",
            gpsd_port=2947,
        ),
    )


def test_runtime_state_projects_lifecycle_runtime() -> None:
    registry = object()
    processor = object()
    control_plane = object()
    worker_pool = object()
    settings_reader = object()
    gps_monitor = object()
    obd_runner = object()
    history_db = object()
    processing_loop_state = object()
    health_state = RuntimeHealthState()
    ingest_diagnostics = object()
    processing_loop = object()
    ws_hub = object()
    ws_broadcast = object()
    run_recorder = object()
    update_manager = object()
    esp_flash_manager = object()
    state = RuntimeState(
        config=_config(),
        registry=registry,
        processor=processor,
        control_plane=control_plane,
        worker_pool=worker_pool,
        settings_reader=settings_reader,
        gps_monitor=gps_monitor,
        obd_runner=obd_runner,
        history_db=history_db,
        processing_loop_state=processing_loop_state,
        health_state=health_state,
        ingest_diagnostics=ingest_diagnostics,
        processing_loop=processing_loop,
        ws_hub=ws_hub,
        ws_broadcast=ws_broadcast,
        run_recorder=run_recorder,
        update_manager=update_manager,
        esp_flash_manager=esp_flash_manager,
    )

    lifecycle_runtime = state.lifecycle_runtime()

    assert lifecycle_runtime.health_state is health_state
    assert lifecycle_runtime.history_db_path == "/tmp/history.db"
    assert lifecycle_runtime.udp_data_host == "0.0.0.0"
    assert lifecycle_runtime.udp_data_port == 9000
    assert lifecycle_runtime.udp_data_queue_maxsize == 321
    assert lifecycle_runtime.gpsd_host == "gpsd.local"
    assert lifecycle_runtime.gpsd_port == 2947
    assert lifecycle_runtime.shutdown_analysis_timeout_s == 12.5
    assert lifecycle_runtime.registry is registry
    assert lifecycle_runtime.processor is processor
    assert lifecycle_runtime.ingest_diagnostics is ingest_diagnostics
    assert lifecycle_runtime.control_plane is control_plane
    assert lifecycle_runtime.processing_loop is processing_loop
    assert lifecycle_runtime.ws_hub is ws_hub
    assert lifecycle_runtime.ws_broadcast is ws_broadcast
    assert lifecycle_runtime.run_recorder is run_recorder
    assert lifecycle_runtime.gps_monitor is gps_monitor
    assert lifecycle_runtime.obd_runner is obd_runner
    assert lifecycle_runtime.update_manager is update_manager
    assert lifecycle_runtime.esp_flash_manager is esp_flash_manager
    assert lifecycle_runtime.worker_pool is worker_pool
    assert lifecycle_runtime.history_db is history_db
