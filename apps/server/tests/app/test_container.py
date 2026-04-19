"""Container wiring coverage for history-db startup and assembly bundles."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from vibesensor.app import container as container_module


def test_create_history_db_skips_stale_recovery_when_quick_check_marked_corrupted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    recovered = {"called": False}
    pruned = {"called": False}
    fake_history = SimpleNamespace(
        lifecycle=SimpleNamespace(corruption_detected=True),
        run_repository=SimpleNamespace(
            recover_stale_recording_runs=lambda: recovered.__setitem__("called", True),
            prune_terminal_runs_older_than_days=lambda _days: pruned.__setitem__("called", True),
        ),
    )

    def _fake_history_adapters(_path: Path, *, corruption_reporter=None):
        assert corruption_reporter is not None
        return fake_history

    monkeypatch.setattr(
        container_module,
        "create_history_persistence_adapters",
        _fake_history_adapters,
    )
    config = SimpleNamespace(
        logging=SimpleNamespace(history_db_path=tmp_path / "history.db", run_retention_days=7),
    )

    result = container_module.create_history_db(
        config,
        corruption_reporter=lambda _details: None,
    )

    assert result is fake_history
    assert recovered["called"] is False
    assert pruned["called"] is False


def test_create_history_db_prunes_old_terminal_runs_on_startup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[tuple[str, int | None]] = []

    def _recover() -> int:
        calls.append(("recover", None))
        return 0

    def _prune(days: int) -> int:
        calls.append(("prune", days))
        return 2

    fake_history = SimpleNamespace(
        lifecycle=SimpleNamespace(corruption_detected=False),
        run_repository=SimpleNamespace(
            recover_stale_recording_runs=_recover,
            prune_terminal_runs_older_than_days=_prune,
        ),
    )

    def _fake_history_adapters(_path: Path, *, corruption_reporter=None):
        assert corruption_reporter is not None
        return fake_history

    monkeypatch.setattr(
        container_module,
        "create_history_persistence_adapters",
        _fake_history_adapters,
    )
    config = SimpleNamespace(
        logging=SimpleNamespace(history_db_path=tmp_path / "history.db", run_retention_days=14),
    )

    result = container_module.create_history_db(
        config,
        corruption_reporter=lambda _details: None,
    )

    assert result is fake_history
    assert calls == [("recover", None), ("prune", 14)]


def test_create_history_db_continues_when_retention_prune_fails(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    fake_history = SimpleNamespace(
        lifecycle=SimpleNamespace(corruption_detected=False),
        run_repository=SimpleNamespace(
            recover_stale_recording_runs=lambda: 0,
            prune_terminal_runs_older_than_days=lambda _days: (_ for _ in ()).throw(
                sqlite3.OperationalError("prune failed")
            ),
        ),
    )

    def _fake_history_adapters(_path: Path, *, corruption_reporter=None):
        assert corruption_reporter is not None
        return fake_history

    monkeypatch.setattr(
        container_module,
        "create_history_persistence_adapters",
        _fake_history_adapters,
    )
    config = SimpleNamespace(
        logging=SimpleNamespace(history_db_path=tmp_path / "history.db", run_retention_days=7),
    )

    with caplog.at_level("WARNING"):
        result = container_module.create_history_db(
            config,
            corruption_reporter=lambda _details: None,
        )

    assert result is fake_history
    assert "Failed to prune terminal runs older than 7 day(s)" in caplog.text


def test_build_settings_service_bundle_exposes_runtime_and_http_dependency_groups() -> None:
    speed_status_service = SimpleNamespace(name="speed-status")
    obd_admin_service = SimpleNamespace(name="obd-admin")
    bundle = container_module.build_settings_service_bundle(
        snapshot_repository=None,
        speed_control=None,
    )

    created = bundle.car_settings.add_car({"name": "Bundle Car", "type": "coupe"})
    car_id = created.cars[0]["id"]
    bundle.car_settings.set_active_car(car_id)
    bundle.analysis_settings.update_active_car_aspects({"tire_width_mm": 255.0})
    bundle.sensor_metadata_store.assign_sensor_location(
        "00:11:22:33:44:55",
        "front_left_wheel",
    )

    runtime_deps = bundle.runtime_deps()
    http_deps = bundle.http_settings_deps(
        speed_status_service=speed_status_service,
        obd_admin_service=obd_admin_service,
    )

    assert runtime_deps.settings_reader.active_car_snapshot().car_id == car_id
    assert runtime_deps.settings_reader.analysis_settings_snapshot().tire_width_mm == 255.0
    assert runtime_deps.sensor_metadata_reader is bundle.sensor_metadata_store
    assert (
        runtime_deps.sensor_metadata_reader.get_sensors()["001122334455"]["name"]
        == "Front Left Wheel"
    )
    assert runtime_deps.speed_source_reader is bundle.speed_source_settings
    assert (
        bundle.speed_source_service.get_speed_source()
        == bundle.speed_source_settings.get_speed_source()
    )
    assert runtime_deps.language_reader is bundle.ui_preferences
    assert runtime_deps.language_reader.language == bundle.ui_preferences.language == "en"

    assert http_deps.car_settings is bundle.car_settings
    assert http_deps.analysis_settings is bundle.analysis_settings
    assert http_deps.ui_preferences is bundle.ui_preferences
    assert http_deps.speed_source_service is bundle.speed_source_service
    assert http_deps.speed_status_service is speed_status_service
    assert http_deps.obd_admin_service is obd_admin_service


def test_build_speed_runtime_groups_gps_obd_and_speed_services(monkeypatch) -> None:
    gps_monitor = SimpleNamespace(name="gps-monitor")
    obd_admin_client = SimpleNamespace(name="obd-admin-client")
    obd_runtime = SimpleNamespace(
        observation=SimpleNamespace(facts="obd-facts", projection="obd-projection"),
        control=SimpleNamespace(admin="obd-admin", settings="obd-settings"),
    )
    speed_services = SimpleNamespace(
        observation="speed-observation",
        admin="speed-admin",
        control="speed-control",
    )
    calls: dict[str, object] = {}

    def _fake_gps_monitor(*, gps_enabled: bool) -> SimpleNamespace:
        calls["gps_enabled"] = gps_enabled
        return gps_monitor

    def _fake_obd_runtime(*, admin_client: object) -> SimpleNamespace:
        calls["obd_admin_client"] = admin_client
        return obd_runtime

    def _fake_speed_services(**kwargs: object) -> SimpleNamespace:
        calls["speed_services_kwargs"] = kwargs
        return speed_services

    monkeypatch.setattr(container_module, "GPSSpeedMonitor", _fake_gps_monitor)
    monkeypatch.setattr(container_module, "ObdAdminClient", lambda: obd_admin_client)
    monkeypatch.setattr(container_module, "build_obd_runtime", _fake_obd_runtime)
    monkeypatch.setattr(
        container_module,
        "build_speed_source_services",
        _fake_speed_services,
    )

    bundle = container_module.build_speed_runtime(
        SimpleNamespace(gps=SimpleNamespace(gps_enabled=True))
    )

    assert bundle.gps_monitor is gps_monitor
    assert bundle.obd_runtime is obd_runtime
    assert bundle.speed_services is speed_services
    assert calls["gps_enabled"] is True
    assert calls["obd_admin_client"] is obd_admin_client
    assert calls["speed_services_kwargs"] == {
        "gps_monitor": gps_monitor,
        "obd_facts": "obd-facts",
        "obd_projection": "obd-projection",
        "obd_device_admin": obd_admin_client,
        "obd_status_refresher": "obd-admin",
        "obd_control": "obd-settings",
    }


def test_build_history_service_bundle_exposes_http_history_deps(monkeypatch) -> None:
    history = SimpleNamespace(run_repository="run-repository")
    current_car_reader = SimpleNamespace(name="current-car-reader")
    history_run_service = SimpleNamespace(name="history-run-service")
    projected_run_service = SimpleNamespace(name="projected-run-service")
    report_service = SimpleNamespace(name="report-service")
    history_export_service = SimpleNamespace(name="history-export-service")
    projected_export_service = SimpleNamespace(name="projected-export-service")
    calls: dict[str, object] = {}

    def _fake_history_run_service(run_repository: object) -> SimpleNamespace:
        calls["history_run_repository"] = run_repository
        return history_run_service

    def _fake_projected_run_service(
        base_service: object,
        *,
        current_car_reader: object,
    ) -> SimpleNamespace:
        calls["projected_run_args"] = (base_service, current_car_reader)
        return projected_run_service

    def _fake_report_service(
        run_repository: object,
        *,
        pdf_renderer: object,
    ) -> SimpleNamespace:
        calls["report_args"] = (run_repository, pdf_renderer)
        return report_service

    def _fake_history_export_service(run_repository: object) -> SimpleNamespace:
        calls["history_export_repository"] = run_repository
        return history_export_service

    def _fake_projected_export_service(base_service: object) -> SimpleNamespace:
        calls["projected_export_arg"] = base_service
        return projected_export_service

    monkeypatch.setattr(container_module, "HistoryRunService", _fake_history_run_service)
    monkeypatch.setattr(
        container_module,
        "ProjectedHistoryRunService",
        _fake_projected_run_service,
    )
    monkeypatch.setattr(container_module, "HistoryReportService", _fake_report_service)
    monkeypatch.setattr(
        container_module,
        "HistoryExportService",
        _fake_history_export_service,
    )
    monkeypatch.setattr(
        container_module,
        "ProjectedHistoryExportService",
        _fake_projected_export_service,
    )

    bundle = container_module.build_history_service_bundle(
        history=history,
        current_car_reader=current_car_reader,
    )
    http_deps = bundle.http_deps()

    assert bundle.run_service is projected_run_service
    assert bundle.report_service is report_service
    assert bundle.export_service is projected_export_service
    assert http_deps.run_service is projected_run_service
    assert http_deps.report_service is report_service
    assert http_deps.export_service is projected_export_service
    assert calls["history_run_repository"] == "run-repository"
    assert calls["projected_run_args"] == (history_run_service, current_car_reader)
    assert calls["report_args"] == (
        "run-repository",
        container_module._build_prepared_pdf_bytes,
    )
    assert calls["history_export_repository"] == "run-repository"
    assert calls["projected_export_arg"] is history_export_service


def test_build_live_runtime_exposes_http_route_bundle_deps_and_requeues_stale_runs(
    monkeypatch,
) -> None:
    registry = SimpleNamespace(name="registry")
    worker_pool = SimpleNamespace(name="worker-pool")
    processor = SimpleNamespace(name="processor")
    control_plane = SimpleNamespace(name="control-plane")
    processing_loop_state = SimpleNamespace(name="processing-loop-state")
    processing_loop = SimpleNamespace(name="processing-loop")
    ws_hub = SimpleNamespace(name="ws-hub")
    ws_payload_projector = SimpleNamespace(name="ws-payload-projector")
    ws_broadcast = SimpleNamespace(name="ws-broadcast")
    calls: dict[str, object] = {}

    class FakeRunRecorder:
        def __init__(self) -> None:
            self.scheduled: list[str] = []

        def schedule_post_analysis(self, run_id: str) -> None:
            self.scheduled.append(run_id)

    run_recorder = FakeRunRecorder()
    history = SimpleNamespace(
        client_name_repository="client-name-repository",
        run_repository=SimpleNamespace(
            stale_analyzing_run_ids=lambda: ["run-1", "run-2"],
        ),
    )
    speed_runtime = SimpleNamespace(speed_services=SimpleNamespace(observation="speed-observation"))
    runtime_settings = container_module.RuntimeSettingsDeps(
        settings_reader="settings-reader",
        speed_source_reader="speed-source-reader",
        sensor_metadata_reader="sensor-reader",
        language_reader="language-reader",
    )
    config = SimpleNamespace(
        processing=SimpleNamespace(
            client_live_ttl_seconds=5,
            client_ttl_seconds=30,
            sample_rate_hz=3200,
            waveform_seconds=2.0,
        ),
        udp=SimpleNamespace(control_host="0.0.0.0", control_port=2000),
        gps=SimpleNamespace(gps_enabled=True),
        logging=SimpleNamespace(
            metrics_log_hz=1.0,
            no_data_timeout_s=3.0,
            persist_history_db=True,
        ),
    )

    def _fake_registry(**kwargs: object) -> SimpleNamespace:
        calls["registry_kwargs"] = kwargs
        return registry

    def _fake_worker_pool(**kwargs: object) -> SimpleNamespace:
        calls["worker_pool_kwargs"] = kwargs
        return worker_pool

    def _fake_processor(**kwargs: object) -> SimpleNamespace:
        calls["processor_kwargs"] = kwargs
        return processor

    def _fake_control_plane(**kwargs: object) -> SimpleNamespace:
        calls["control_plane_kwargs"] = kwargs
        return control_plane

    def _fake_processing_loop(**kwargs: object) -> SimpleNamespace:
        calls["processing_loop_kwargs"] = kwargs
        return processing_loop

    def _fake_ws_broadcast(**kwargs: object) -> SimpleNamespace:
        calls["ws_broadcast_kwargs"] = kwargs
        return ws_broadcast

    monkeypatch.setattr(
        container_module,
        "ClientRegistry",
        _fake_registry,
    )
    monkeypatch.setattr(
        container_module,
        "WorkerPool",
        _fake_worker_pool,
    )
    monkeypatch.setattr(
        container_module,
        "SignalProcessor",
        _fake_processor,
    )
    monkeypatch.setattr(
        container_module,
        "UDPControlPlane",
        _fake_control_plane,
    )
    monkeypatch.setattr(container_module, "ProcessingLoopState", lambda: processing_loop_state)
    monkeypatch.setattr(
        container_module,
        "ProcessingLoop",
        _fake_processing_loop,
    )
    monkeypatch.setattr(container_module, "WebSocketHub", lambda: ws_hub)

    def _fake_ws_payload_projector(**kwargs: object) -> SimpleNamespace:
        calls["ws_payload_projector_kwargs"] = kwargs
        return ws_payload_projector

    monkeypatch.setattr(
        container_module,
        "LiveWsPayloadProjector",
        _fake_ws_payload_projector,
    )
    monkeypatch.setattr(
        container_module,
        "WsBroadcastService",
        _fake_ws_broadcast,
    )

    def _fake_run_recorder(config_obj: object, **kwargs: object) -> FakeRunRecorder:
        calls["run_recorder_config"] = config_obj
        calls["run_recorder_kwargs"] = kwargs
        return run_recorder

    monkeypatch.setattr(container_module, "RunRecorder", _fake_run_recorder)

    bundle = container_module.build_live_runtime(
        config=config,
        accel_scale_g_per_lsb=0.25,
        history=history,
        speed_runtime=speed_runtime,
        runtime_settings=runtime_settings,
    )
    health = bundle.http_health_deps(health_state="health-state")
    live = bundle.http_live_deps(sensor_metadata_store="sensor-store")

    assert bundle.registry is registry
    assert bundle.worker_pool is worker_pool
    assert bundle.processor is processor
    assert bundle.control_plane is control_plane
    assert bundle.processing_loop_state is processing_loop_state
    assert bundle.processing_loop is processing_loop
    assert bundle.ws_hub is ws_hub
    assert bundle.ws_broadcast is ws_broadcast
    assert bundle.run_recorder is run_recorder
    assert run_recorder.scheduled == ["run-1", "run-2"]
    assert calls["registry_kwargs"] == {
        "db": "client-name-repository",
        "live_ttl_seconds": 5,
        "retention_ttl_seconds": 30,
    }
    assert calls["worker_pool_kwargs"] == {
        "max_workers": 4,
        "thread_name_prefix": "vibesensor-fft",
    }
    assert calls["control_plane_kwargs"] == {
        "registry": registry,
        "bind_host": "0.0.0.0",
        "bind_port": 2000,
    }
    assert calls["ws_payload_projector_kwargs"] == {
        "registry": registry,
        "processor": processor,
        "gps_monitor": "speed-observation",
        "gps_enabled": True,
        "settings_reader": "settings-reader",
        "speed_source_reader": "speed-source-reader",
        "sensor_metadata_reader": "sensor-reader",
    }
    assert calls["ws_broadcast_kwargs"] == {
        "ui_push_hz": container_module.UI_PUSH_HZ,
        "ui_heavy_push_hz": container_module.UI_HEAVY_PUSH_HZ,
        "payload_source": ws_payload_projector,
    }
    assert calls["run_recorder_kwargs"] == {
        "registry": registry,
        "gps_monitor": "speed-observation",
        "processor": processor,
        "history_db": history.run_repository,
        "settings_reader": "settings-reader",
        "sensor_metadata_reader": "sensor-reader",
        "language_reader": runtime_settings.language_reader,
    }
    assert health.processing_loop_state is processing_loop_state
    assert health.health_state == "health-state"
    assert health.processor is processor
    assert health.registry is registry
    assert health.run_recorder is run_recorder
    assert live.registry is registry
    assert live.control_plane is control_plane
    assert live.sensor_metadata_store == "sensor-store"
    assert live.processor is processor
    assert live.run_recorder is run_recorder
    assert live.ws_hub is ws_hub


def test_build_router_deps_maps_runtime_bundles_to_route_bundles() -> None:
    speed_status_service = object()
    obd_admin_service = object()
    settings_deps = SimpleNamespace(name="settings-deps")
    history_deps = object()
    health_deps = object()
    live_deps = object()
    updates = object()
    speed_runtime = SimpleNamespace(
        speed_services=SimpleNamespace(
            observation=speed_status_service,
            admin=obd_admin_service,
        )
    )
    settings_services = SimpleNamespace(
        http_settings_deps=Mock(return_value=settings_deps),
        sensor_metadata_store="sensor-store",
    )
    history_services = SimpleNamespace(http_deps=Mock(return_value=history_deps))
    live_runtime = SimpleNamespace(
        http_health_deps=Mock(return_value=health_deps),
        http_live_deps=Mock(return_value=live_deps),
    )

    router_deps = container_module.build_router_deps(
        health_state="health-state",
        speed_runtime=speed_runtime,
        settings_services=settings_services,
        history_services=history_services,
        live_runtime=live_runtime,
        updates=updates,
    )

    assert router_deps.health is health_deps
    assert router_deps.settings is settings_deps
    assert router_deps.live is live_deps
    assert router_deps.history is history_deps
    assert router_deps.updates is updates
    live_runtime.http_health_deps.assert_called_once_with(health_state="health-state")
    settings_services.http_settings_deps.assert_called_once_with(
        speed_status_service=speed_status_service,
        obd_admin_service=obd_admin_service,
    )
    live_runtime.http_live_deps.assert_called_once_with(sensor_metadata_store="sensor-store")
    history_services.http_deps.assert_called_once_with()


def test_build_runtime_assembles_app_runtime_through_domain_builders(
    monkeypatch,
) -> None:
    config = SimpleNamespace(name="config")
    health_state = SimpleNamespace(mark_db_corrupted=Mock())
    history = SimpleNamespace(settings_snapshot_repository="settings-snapshot")
    speed_runtime = SimpleNamespace(speed_services=SimpleNamespace(control="speed-control"))
    runtime_settings = SimpleNamespace(name="runtime-settings")
    sync_all = Mock()
    settings_services = SimpleNamespace(
        runtime_deps=Mock(return_value=runtime_settings),
        speed_source_service=SimpleNamespace(sync_all=sync_all),
        settings_reader="settings-reader",
    )
    history_services = SimpleNamespace(name="history-services")
    live_runtime = SimpleNamespace(name="live-runtime")
    updates = SimpleNamespace(name="updates")
    lifecycle = SimpleNamespace(name="lifecycle")
    router = SimpleNamespace(name="router")
    calls: dict[str, object] = {}

    monkeypatch.setattr(container_module, "resolve_accel_scale_g_per_lsb", lambda _config: 0.125)
    monkeypatch.setattr(container_module, "RuntimeHealthState", lambda: health_state)

    def _fake_create_history_db(
        passed_config: object,
        *,
        corruption_reporter: object,
    ) -> SimpleNamespace:
        calls["create_history_db_args"] = (passed_config, corruption_reporter)
        return history

    monkeypatch.setattr(container_module, "create_history_db", _fake_create_history_db)

    def _fake_speed_runtime(passed_config: object):
        calls["speed_config"] = passed_config
        return speed_runtime

    monkeypatch.setattr(
        container_module,
        "build_speed_runtime",
        _fake_speed_runtime,
    )

    def _fake_settings_bundle(*, snapshot_repository: object, speed_control: object):
        calls["settings_bundle_args"] = (snapshot_repository, speed_control)
        return settings_services

    monkeypatch.setattr(
        container_module,
        "build_settings_service_bundle",
        _fake_settings_bundle,
    )

    def _fake_history_services(*, history: object, current_car_reader: object):
        calls["history_service_args"] = (history, current_car_reader)
        return history_services

    monkeypatch.setattr(
        container_module,
        "build_history_service_bundle",
        _fake_history_services,
    )

    def _fake_live_runtime(**kwargs: object):
        calls["live_runtime_args"] = kwargs
        return live_runtime

    monkeypatch.setattr(container_module, "build_live_runtime", _fake_live_runtime)

    def _fake_update_deps(passed_config: object):
        calls["update_config"] = passed_config
        return updates

    monkeypatch.setattr(
        container_module,
        "build_update_deps",
        _fake_update_deps,
    )

    def _fake_lifecycle_state(**kwargs: object):
        calls["lifecycle_args"] = kwargs
        return lifecycle

    def _fake_router_deps(**kwargs: object):
        calls["router_args"] = kwargs
        return router

    monkeypatch.setattr(container_module, "build_lifecycle_state", _fake_lifecycle_state)
    monkeypatch.setattr(container_module, "build_router_deps", _fake_router_deps)

    result = container_module.build_runtime(config)

    assert result.lifecycle is lifecycle
    assert result.router is router
    assert calls["create_history_db_args"] == (config, health_state.mark_db_corrupted)
    assert calls["speed_config"] is config
    assert calls["settings_bundle_args"] == ("settings-snapshot", "speed-control")
    assert settings_services.runtime_deps.call_count == 1
    assert calls["history_service_args"] == (history, "settings-reader")
    assert calls["live_runtime_args"] == {
        "config": config,
        "accel_scale_g_per_lsb": 0.125,
        "history": history,
        "speed_runtime": speed_runtime,
        "runtime_settings": runtime_settings,
    }
    assert calls["update_config"] is config
    assert calls["lifecycle_args"] == {
        "config": config,
        "health_state": health_state,
        "history": history,
        "speed_runtime": speed_runtime,
        "runtime_settings": runtime_settings,
        "live_runtime": live_runtime,
        "updates": updates,
    }
    assert calls["router_args"] == {
        "health_state": health_state,
        "speed_runtime": speed_runtime,
        "settings_services": settings_services,
        "history_services": history_services,
        "live_runtime": live_runtime,
        "updates": updates,
    }
    sync_all.assert_called_once_with()
