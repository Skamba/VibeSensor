"""Focused tests for shared settings snapshot persistence and rollback behavior."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from test_support.settings_services import write_raw_settings_snapshot

from vibesensor.common.exceptions import PersistenceError
from vibesensor.history.history_db import HistoryDB
from vibesensor.settings.services import build_settings_services
from vibesensor.settings.settings_snapshot import SettingsSnapshotPayload


class FakeSettingsSnapshotStore:
    def __init__(self, snapshot: SettingsSnapshotPayload | None = None) -> None:
        self.snapshot = snapshot

    def get_settings_snapshot(self) -> SettingsSnapshotPayload | None:
        return self.snapshot

    def set_settings_snapshot(self, snapshot: SettingsSnapshotPayload) -> None:
        self.snapshot = snapshot


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
            "obdDeviceMac": "02:00:00:00:00:4D",
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
    assert snapshot["obdDeviceMac"] == "02000000004d"
    assert snapshot["obdDeviceName"] == "OBDLink MX+ 80163"
    assert snapshot["sensorsByMac"]["112233445566"]["name"] == "Rear Left Wheel"
    assert snapshot["language"] == "nl"
    assert snapshot["speedUnit"] == "mps"


def test_an_explicit_speed_source_choice_survives_a_restart_and_pairing(tmp_path: Path) -> None:
    """The choice was dropped on save, so after a restart a paired adapter took over."""
    db = HistoryDB(tmp_path / "history.db")
    services = build_settings_services(db=db)
    services.speed_source_settings.update_speed_source({"speedSource": "gps"})
    services.speed_source_settings.update_speed_source({"obdDeviceMac": "02:00:00:00:00:4D"})

    reloaded = build_settings_services(db=db).speed_source_settings.speed_source_config()

    assert (reloaded.speed_source, reloaded.speed_source_chosen) == ("gps", True)
    assert reloaded.obd_device_mac == "02000000004d"


def test_settings_snapshot_reload_keeps_order_reference_status_and_axle_tires(
    tmp_path: Path,
) -> None:
    db = HistoryDB(tmp_path / "history.db")
    services = build_settings_services(db=db)
    created = services.car_settings.add_car(
        {
            "name": "Library Car",
            "aspects": {"tire_width_mm": 205.0, "tire_aspect_pct": 55.0, "rim_in": 16.0},
            "order_reference_status": {
                "selection_source_status": "exact_row",
                "requires_manual_confirmation": False,
                "tire_dimensions_confidence": "official_exact",
            },
        }
    )
    car_id = created.cars[0]["id"]
    services.car_settings.update_car(
        car_id,
        {
            "aspects": {
                "front_tire_width_mm": 225.0,
                "front_tire_aspect_pct": 45.0,
                "front_rim_in": 17.0,
                "rear_tire_width_mm": 245.0,
                "rear_tire_aspect_pct": 40.0,
                "rear_rim_in": 17.0,
                "default_axle_for_speed": "front",
            }
        },
    )

    reloaded = build_settings_services(db=db).coordinator.snapshot()["cars"][0]

    assert reloaded["aspects"]["default_axle_for_speed"] == "front"
    assert reloaded["aspects"]["front_tire_width_mm"] == 225.0
    status = reloaded.get("order_reference_status")
    assert status is not None
    # Editing the tires made them user-confirmed; the status survives the reload.
    assert status["selection_source_status"] == "manual_entry"
    assert status.get("tire_dimensions_confidence") == "user_confirmed"


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


@pytest.mark.parametrize(
    ("raw_snapshot", "expected"),
    [
        pytest.param(
            "not-valid-json{{{",
            {"cars": [], "activeCarId": None, "speedSource": "gps"},
            id="corrupted-json-falls-back-to-defaults",
        ),
        pytest.param(
            '{"cars": [{"id": "", "name": " Legacy ", "type": " coupe ", "aspects": {}}], '
            '"activeCarId": "missing-car", "manualSpeedKph": "80", "language": " NL ", '
            '"speedUnit": " MPS ", "sensorsByMac": {"11:22:33:44:55:66": '
            '{"name": "Rear Left Wheel", "location_code": "rear_left_wheel"}}}',
            {
                "cars": [],
                "activeCarId": None,
                "speedSource": "gps",
                "manualSpeedKph": None,
                "language": "en",
                "speedUnit": "kmh",
                "sensorsByMac": {},
            },
            id="legacy-payload-falls-back-to-defaults",
        ),
        pytest.param(
            '{"cars": [], "activeCarId": ""}',
            {"cars": [], "activeCarId": None},
            id="empty-cars-stay-empty",
        ),
    ],
)
def test_settings_snapshot_rejects_invalid_stored_payload(
    tmp_path: Path, raw_snapshot: str, expected: dict[str, object]
) -> None:
    db = HistoryDB(tmp_path / "history.db")
    write_raw_settings_snapshot(db, raw_snapshot)
    snapshot = build_settings_services(db=db).coordinator.snapshot()
    assert {key: snapshot[key] for key in expected} == expected


def test_settings_snapshot_drops_removed_band_width_aspects(tmp_path: Path) -> None:
    removed_keys = {
        "wheel_bandwidth_pct",
        "driveshaft_bandwidth_pct",
        "engine_bandwidth_pct",
        "min_abs_band_hz",
        "max_band_half_width_pct",
    }
    db = HistoryDB(tmp_path / "history.db")
    write_raw_settings_snapshot(
        db,
        (
            '{"cars": [{"id": "car-1", "name": "Old", "type": "sedan", "aspects": '
            '{"tire_width_mm": 225, "rim_in": 17, "speed_uncertainty_pct": 2.5, '
            '"wheel_bandwidth_pct": 7.5, "driveshaft_bandwidth_pct": 8.5, '
            '"engine_bandwidth_pct": 9.5, "min_abs_band_hz": 0.7, '
            '"max_band_half_width_pct": 12}}], "activeCarId": "car-1"}'
        ),
    )
    services = build_settings_services(db=db)

    aspects = services.coordinator.snapshot()["cars"][0]["aspects"]
    assert removed_keys.isdisjoint(aspects)
    assert aspects["tire_width_mm"] == 225.0
    assert aspects["speed_uncertainty_pct"] == 2.5
    analysis = services.analysis_settings.analysis_settings_snapshot()
    assert analysis.rim_in == 17.0

    services.analysis_settings.update_active_car_aspects({"rim_in": 18.0})
    persisted = db.get_settings_snapshot()
    assert persisted is not None
    assert removed_keys.isdisjoint(persisted["cars"][0]["aspects"])


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


class _ReadOnlySettingsDB(HistoryDB):
    """A real HistoryDB whose settings writes fail (disk full) once armed."""

    fail_writes = False

    def set_settings_snapshot(self, snapshot: SettingsSnapshotPayload) -> None:
        if self.fail_writes:
            raise OSError("disk full")
        super().set_settings_snapshot(snapshot)


def _sabotaged_services(tmp_path: Path):
    db = _ReadOnlySettingsDB(tmp_path / "history.db")
    services = build_settings_services(db=db)
    created = services.car_settings.add_car({"name": "Test Car", "type": "sedan"})
    services.car_settings.set_active_car(created.cars[0]["id"])
    services.sensor_settings.assign_sensor_location("11:22:33:44:55:66", "rear_left_wheel")
    db.fail_writes = True
    return services


def _settings_state(services) -> tuple[object, ...]:
    return (
        services.car_settings.get_cars(),
        services.speed_source_settings.get_speed_source(),
        services.ui_preferences.language,
        services.ui_preferences.speed_unit,
        services.sensor_settings.get_sensors(),
    )


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda s: s.car_settings.add_car({"name": "Will Fail"}), id="add-car"),
        pytest.param(
            lambda s: s.analysis_settings.update_active_car_aspects({"tire_width_mm": 255.0}),
            id="car-aspects",
        ),
        pytest.param(
            lambda s: s.speed_source_settings.update_speed_source(
                {"speedSource": "manual", "manualSpeedKph": 80}
            ),
            id="speed-source",
        ),
        pytest.param(lambda s: s.ui_preferences.set_language("nl"), id="language"),
        pytest.param(lambda s: s.ui_preferences.set_speed_unit("mps"), id="speed-unit"),
        pytest.param(
            lambda s: s.sensor_settings.assign_sensor_location(
                "AA:BB:CC:DD:EE:FF", "front_left_wheel"
            ),
            id="new-sensor-location",
        ),
        pytest.param(
            lambda s: s.sensor_settings.assign_sensor_location(
                "11:22:33:44:55:66", "front_left_wheel"
            ),
            id="existing-sensor-location",
        ),
    ],
)
def test_persist_failure_raises_and_rolls_back_in_memory_settings(tmp_path: Path, mutate) -> None:
    services = _sabotaged_services(tmp_path)
    before = _settings_state(services)

    with pytest.raises(PersistenceError, match="Failed to persist"):
        mutate(services)

    assert _settings_state(services) == before


def test_settings_snapshot_persist_failure_logs_error(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    services = _sabotaged_services(tmp_path)
    with caplog.at_level(logging.ERROR, logger="vibesensor.settings.settings_persistence"):
        with pytest.raises(PersistenceError):
            services.ui_preferences.set_speed_unit("mps")

    assert any(
        "Failed to persist" in record.message and record.levelname == "ERROR"
        for record in caplog.records
    )


def test_drive_layout_survives_a_restart(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    services = build_settings_services(db=db)
    services.car_settings.add_car({"name": "Custom", "type": "Custom", "drive_layout": "RWD"})

    reloaded = build_settings_services(db=db).coordinator.snapshot()["cars"][0]

    assert (reloaded.get("drive_layout"), reloaded.get("final_drive_axle")) == ("RWD", "rear")


def _saved_car(car_id: str, name: str, car_type: str, variant: str | None, **extra: object) -> str:
    car: dict[str, object] = {"id": car_id, "name": name, "type": car_type, "aspects": {}}
    car.update(extra)
    if variant is not None:
        car["variant"] = variant
    return json.dumps(car)


def test_saved_cars_get_the_drive_layout_of_their_library_row_on_load(tmp_path: Path) -> None:
    """Cars saved before the drive layout existed take it from their library row."""
    xdrive_status = {
        "selection_source_status": "exact_row",
        "requires_manual_confirmation": False,
        "transmission_name": "8-speed Steptronic",
    }
    cars = [
        _saved_car("fwd", "BMW X1 (F48, 2015–2022) sDrive18i", "SUV", "sDrive18i"),
        _saved_car("rwd", "BMW 3 Series (G20, 2019–2025) 320d", "Sedan", "320d"),
        _saved_car(
            "e-awd",
            "BMW 2 Series Active Tourer (F45, 2014–2021) 225xe",
            "Hatchback",
            "225xe",
            # The library's final drive is on the front axle: the engine drives it.
            aspects={"final_drive_ratio": 3.944},
            fuel_type="PHEV",
        ),
        _saved_car(
            "awd",
            "BMW X1 (F48, 2015–2022) xDrive20d (2019–2022)",
            "SUV",
            "xDrive20d (2019–2022)",
            order_reference_status=xdrive_status,
        ),
        _saved_car("custom", "My project car", "Custom", None),
        _saved_car("unknown-variant", "BMW X1 (F48, 2015–2022) Prototype", "SUV", "Prototype"),
        # A layout the owner already set is never overwritten by the library.
        _saved_car(
            "kept", "BMW 3 Series (G20, 2019–2025) 320d", "Sedan", "320d", drive_layout="AWD"
        ),
    ]
    db = HistoryDB(tmp_path / "history.db")
    write_raw_settings_snapshot(db, '{"cars": [' + ", ".join(cars) + '], "activeCarId": "fwd"}')

    services = build_settings_services(db=db)

    loaded = {car["id"]: car for car in services.coordinator.snapshot()["cars"]}
    layouts = {
        car_id: (car.get("drive_layout"), car.get("final_drive_axle"))
        for car_id, car in loaded.items()
    }
    assert layouts == {
        "fwd": ("FWD", "front"),
        "rwd": ("RWD", "rear"),
        "e-awd": ("AWD", "front"),
        "awd": ("AWD", None),
        "custom": (None, None),
        "unknown-variant": (None, None),
        "kept": ("AWD", None),
    }
    assert loaded["fwd"]["name"] == "BMW X1 (F48, 2015–2022) sDrive18i"
    snapshot = services.car_settings.active_car_snapshot()
    assert snapshot is not None and snapshot.drive_layout == "FWD"
    # The filled-in layout is saved, so the next start does not redo it.
    persisted = db.get_settings_snapshot()
    assert persisted is not None
    assert persisted["cars"][0].get("drive_layout") == "FWD"
