"""Focused tests for shared settings snapshot persistence and rollback behavior."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from test_support.settings_services import build_settings_services, write_raw_settings_snapshot

from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.shared.exceptions import PersistenceError
from vibesensor.shared.types.settings_snapshot import SettingsSnapshotPayload


class FakeSettingsSnapshotStore:
    def __init__(self, snapshot: SettingsSnapshotPayload | None = None) -> None:
        self.snapshot = snapshot

    def get_settings_snapshot(self) -> SettingsSnapshotPayload | None:
        return self.snapshot

    def set_settings_snapshot(self, snapshot: SettingsSnapshotPayload) -> None:
        self.snapshot = snapshot


def _sabotaged_services(tmp_path: Path):
    db = HistoryDB(tmp_path / "history.db")
    services = build_settings_services(db=db)

    def _boom(payload: object) -> None:
        raise OSError("disk full")

    db.set_settings_snapshot = _boom
    return services


def test_settings_snapshot_defaults_are_empty_and_gps() -> None:
    services = build_settings_services()
    snapshot = services.coordinator.snapshot()
    assert snapshot["cars"] == []
    assert snapshot["activeCarId"] is None
    assert snapshot["speedSource"] == "gps"
    assert snapshot["manualSpeedKph"] is None
    assert "obdDeviceMac" not in snapshot
    assert "obdDeviceName" not in snapshot


def test_settings_snapshot_persists_and_loads(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    services = build_settings_services(db=db)
    added = services.car_settings.add_car({"name": "Persisted Car", "type": "suv"})
    services.car_settings.set_active_car(added.cars[0]["id"])
    services.speed_source_settings.update_speed_source(
        {
            "speedSource": "obd2",
            "manualSpeedKph": 60,
            "obdDeviceMac": "00:04:3E:5A:4A:4D",
            "obdDeviceName": "OBDLink MX+ 80163",
        }
    )
    services.sensor_settings.assign_sensor_location("11:22:33:44:55:66", "rear_left_wheel")
    services.ui_preferences.set_language("nl")
    services.ui_preferences.set_speed_unit("mps")

    reloaded = build_settings_services(db=db)
    snapshot = reloaded.coordinator.snapshot()
    assert len(snapshot["cars"]) == 1
    assert snapshot["cars"][0]["name"] == "Persisted Car"
    assert snapshot["activeCarId"] == snapshot["cars"][0]["id"]
    assert snapshot["speedSource"] == "obd2"
    assert snapshot["manualSpeedKph"] == 60.0
    assert snapshot["obdDeviceMac"] == "00043e5a4a4d"
    assert snapshot["obdDeviceName"] == "OBDLink MX+ 80163"
    assert snapshot["sensorsByMac"]["112233445566"]["name"] == "Rear Left Wheel"
    assert snapshot["language"] == "nl"
    assert snapshot["speedUnit"] == "mps"


def test_settings_snapshot_persists_with_protocol_shaped_store() -> None:
    snapshot_store = FakeSettingsSnapshotStore()
    services = build_settings_services(db=snapshot_store)
    created = services.car_settings.add_car({"name": "Protocol Car", "type": "suv"})
    car_id = created.cars[0]["id"]
    services.car_settings.set_active_car(car_id)

    reloaded = build_settings_services(db=snapshot_store)
    snapshot = reloaded.coordinator.snapshot()
    assert len(snapshot["cars"]) == 1
    assert snapshot["cars"][0]["name"] == "Protocol Car"
    assert snapshot["activeCarId"] == car_id


def test_settings_snapshot_corrupted_json_falls_back_to_defaults(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    write_raw_settings_snapshot(db, "not-valid-json{{{")
    services = build_settings_services(db=db)
    snapshot = services.coordinator.snapshot()
    assert snapshot["cars"] == []
    assert snapshot["activeCarId"] is None
    assert snapshot["speedSource"] == "gps"


def test_settings_snapshot_with_empty_cars_stays_empty(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    write_raw_settings_snapshot(db, '{"cars": [], "activeCarId": ""}')
    services = build_settings_services(db=db)
    snapshot = services.coordinator.snapshot()
    assert snapshot["cars"] == []
    assert snapshot["activeCarId"] is None


def test_settings_snapshot_invalid_active_car_id_clears_selection(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    write_raw_settings_snapshot(
        db,
        (
            '{"cars": [{"id": "car-1", "name": "Only", "type": "sedan", "aspects": {}}], '
            '"activeCarId": "missing-car"}'
        ),
    )
    services = build_settings_services(db=db)
    snapshot = services.coordinator.snapshot()
    assert len(snapshot["cars"]) == 1
    assert snapshot["activeCarId"] is None


def test_settings_snapshot_persist_failure_raises_persistence_error(tmp_path: Path) -> None:
    services = _sabotaged_services(tmp_path)
    with pytest.raises(PersistenceError, match="Failed to persist"):
        services.car_settings.add_car({"name": "Will Fail"})


def test_settings_snapshot_persist_failure_propagates_on_speed_source_update(
    tmp_path: Path,
) -> None:
    services = _sabotaged_services(tmp_path)
    with pytest.raises(PersistenceError):
        services.speed_source_settings.update_speed_source(
            {"speedSource": "manual", "manualSpeedKph": 80}
        )


def test_settings_snapshot_persist_failure_propagates_on_set_language(tmp_path: Path) -> None:
    services = _sabotaged_services(tmp_path)
    with pytest.raises(PersistenceError):
        services.ui_preferences.set_language("nl")


def test_settings_snapshot_persist_failure_logs_error(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    services = _sabotaged_services(tmp_path)
    with caplog.at_level(logging.ERROR, logger="vibesensor.infra.config.settings_persistence"):
        with pytest.raises(PersistenceError):
            services.ui_preferences.set_speed_unit("mps")

    assert any(
        "Failed to persist" in record.message and record.levelname == "ERROR"
        for record in caplog.records
    )
