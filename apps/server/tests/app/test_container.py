"""Container wiring coverage for history-db startup and settings assembly."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

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
    bundle.sensor_metadata_store.set_sensor(
        "00:11:22:33:44:55",
        {"name": "Front Left", "location_code": "front_left"},
    )

    runtime_deps = bundle.runtime_deps()
    http_deps = bundle.http_settings_deps(
        speed_status_service=speed_status_service,
        obd_admin_service=obd_admin_service,
    )

    assert runtime_deps.settings_reader.active_car_snapshot().car_id == car_id
    assert runtime_deps.settings_reader.analysis_settings_snapshot().tire_width_mm == 255.0
    assert runtime_deps.sensor_metadata_reader is bundle.sensor_metadata_store
    assert runtime_deps.sensor_metadata_reader.get_sensors()["001122334455"]["name"] == "Front Left"
    assert runtime_deps.speed_source_reader is bundle.speed_source_settings
    assert (
        bundle.speed_source_service.get_speed_source()
        == bundle.speed_source_settings.get_speed_source()
    )
    assert runtime_deps.language_provider() == bundle.ui_preferences.language == "en"

    assert http_deps.car_settings is bundle.car_settings
    assert http_deps.analysis_settings is bundle.analysis_settings
    assert http_deps.sensor_metadata_store is bundle.sensor_metadata_store
    assert http_deps.ui_preferences is bundle.ui_preferences
    assert http_deps.speed_source_service is bundle.speed_source_service
    assert http_deps.speed_status_service is speed_status_service
    assert http_deps.obd_admin_service is obd_admin_service
