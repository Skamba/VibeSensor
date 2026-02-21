from __future__ import annotations

from pathlib import Path

import pytest

from vibesensor.domain_models import CarConfig, SensorConfig, _parse_manual_speed
from vibesensor.history_db import HistoryDB
from vibesensor.settings_store import (
    DEFAULT_CAR_ASPECTS,
    SettingsStore,
    _sanitize_aspects,
)

# -- _sanitize_aspects --------------------------------------------------------


def test_sanitize_aspects_filters_invalid_positive_required() -> None:
    out = _sanitize_aspects({"tire_width_mm": -1.0, "rim_in": 0.0})
    assert "tire_width_mm" not in out
    assert "rim_in" not in out


def test_sanitize_aspects_allows_valid() -> None:
    out = _sanitize_aspects({"tire_width_mm": 225.0, "rim_in": 18.0})
    assert out["tire_width_mm"] == 225.0
    assert out["rim_in"] == 18.0


def test_sanitize_aspects_rejects_negative_non_negative() -> None:
    out = _sanitize_aspects({"speed_uncertainty_pct": -0.1})
    assert "speed_uncertainty_pct" not in out


def test_sanitize_aspects_allows_zero_non_negative() -> None:
    out = _sanitize_aspects({"speed_uncertainty_pct": 0.0})
    assert out["speed_uncertainty_pct"] == 0.0


def test_sanitize_aspects_ignores_unknown() -> None:
    out = _sanitize_aspects({"unknown_key": 42.0})
    assert "unknown_key" not in out


# -- _validate_car -------------------------------------------------------------


def test_validate_car_fills_defaults() -> None:
    car = CarConfig.from_dict({}).to_dict()
    assert car["name"] == "Unnamed Car"
    assert car["type"] == "sedan"
    assert car["id"]
    assert car["aspects"] == DEFAULT_CAR_ASPECTS


def test_validate_car_preserves_aspects() -> None:
    car = CarConfig.from_dict({"aspects": {"tire_width_mm": 245.0}}).to_dict()
    assert car["aspects"]["tire_width_mm"] == 245.0
    assert car["aspects"]["rim_in"] == DEFAULT_CAR_ASPECTS["rim_in"]


def test_validate_car_truncates_name() -> None:
    car = CarConfig.from_dict({"name": "x" * 100}).to_dict()
    assert len(car["name"]) <= 64


# -- _validate_sensor ----------------------------------------------------------


def test_validate_sensor_defaults_name_to_mac() -> None:
    sensor = SensorConfig.from_dict("aa:bb:cc:dd:ee:ff", {}).to_dict()
    assert sensor["name"] == "aa:bb:cc:dd:ee:ff"
    assert sensor["location"] == ""


def test_validate_sensor_uses_provided_name() -> None:
    sensor = SensorConfig.from_dict("aa:bb:cc:dd:ee:ff", {"name": "Front Left"}).to_dict()
    assert sensor["name"] == "Front Left"


# -- SettingsStore full lifecycle -----------------------------------------------


def test_store_default_has_one_car() -> None:
    store = SettingsStore()
    snap = store.snapshot()
    assert len(snap["cars"]) == 1
    assert snap["activeCarId"] == snap["cars"][0]["id"]
    assert snap["speedSource"] == "gps"
    assert snap["manualSpeedKph"] is None


def test_store_add_and_delete_car() -> None:
    store = SettingsStore()
    initial_id = store.snapshot()["cars"][0]["id"]
    store.add_car({"name": "Track Car", "type": "coupe"})
    snap = store.snapshot()
    assert len(snap["cars"]) == 2
    new_car = snap["cars"][1]
    assert new_car["name"] == "Track Car"
    assert new_car["type"] == "coupe"

    store.delete_car(new_car["id"])
    assert len(store.snapshot()["cars"]) == 1
    assert store.snapshot()["cars"][0]["id"] == initial_id


def test_store_cannot_delete_last_car() -> None:
    store = SettingsStore()
    car_id = store.snapshot()["cars"][0]["id"]
    with pytest.raises(ValueError, match="Cannot delete the last car"):
        store.delete_car(car_id)


def test_store_update_car_aspects() -> None:
    store = SettingsStore()
    car_id = store.snapshot()["cars"][0]["id"]
    store.update_car(car_id, {"aspects": {"tire_width_mm": 245.0}})
    aspects = store.active_car_aspects()
    assert aspects["tire_width_mm"] == 245.0
    assert aspects["rim_in"] == DEFAULT_CAR_ASPECTS["rim_in"]


def test_store_update_active_car_aspects() -> None:
    store = SettingsStore()
    updated = store.update_active_car_aspects({"tire_width_mm": 255.0, "rim_in": 19.0})
    assert updated["tire_width_mm"] == 255.0
    assert updated["rim_in"] == 19.0
    assert store.active_car_aspects()["tire_width_mm"] == 255.0


def test_store_set_active_car() -> None:
    store = SettingsStore()
    store.add_car({"name": "Second Car"})
    second_id = store.snapshot()["cars"][1]["id"]
    store.set_active_car(second_id)
    assert store.snapshot()["activeCarId"] == second_id


def test_store_set_active_car_unknown_raises() -> None:
    store = SettingsStore()
    with pytest.raises(ValueError, match="Unknown car id"):
        store.set_active_car("nonexistent-id")


# -- speed source ---------------------------------------------------------------


def test_store_update_speed_source_manual() -> None:
    store = SettingsStore()
    result = store.update_speed_source({"speedSource": "manual", "manualSpeedKph": 80})
    assert result["speedSource"] == "manual"
    assert result["manualSpeedKph"] == 80.0


def test_store_update_speed_source_gps_clears_manual() -> None:
    store = SettingsStore()
    store.update_speed_source({"speedSource": "manual", "manualSpeedKph": 80})
    result = store.update_speed_source({"speedSource": "gps", "manualSpeedKph": None})
    assert result["speedSource"] == "gps"
    assert result["manualSpeedKph"] is None


def test_store_invalid_speed_source_defaults_to_gps() -> None:
    store = SettingsStore()
    result = store.update_speed_source({"speedSource": "unknown"})
    assert result["speedSource"] == "gps"


# -- sensors -------------------------------------------------------------------


def test_store_set_and_get_sensor() -> None:
    store = SettingsStore()
    store.set_sensor("aa:bb:cc:dd:ee:ff", {"name": "FL Wheel", "location": "front_left_wheel"})
    sensors = store.get_sensors()
    assert "aabbccddeeff" in sensors
    assert sensors["aabbccddeeff"]["name"] == "FL Wheel"
    assert sensors["aabbccddeeff"]["location"] == "front_left_wheel"


def test_store_remove_sensor() -> None:
    store = SettingsStore()
    store.set_sensor("aa:bb:cc:dd:ee:ff", {"name": "Test"})
    assert store.remove_sensor("aa:bb:cc:dd:ee:ff") is True
    assert store.remove_sensor("aa:bb:cc:dd:ee:ff") is False


def test_store_set_sensor_creates_entry_with_defaults() -> None:
    store = SettingsStore()
    store.set_sensor("aa:bb:cc:dd:ee:ff", {})
    sensors = store.get_sensors()
    assert "aabbccddeeff" in sensors
    assert sensors["aabbccddeeff"]["name"] == "aabbccddeeff"


def test_store_set_sensor_persists_defaults(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    store = SettingsStore(db=db)
    store.set_sensor("aa:bb:cc:dd:ee:ff", {})
    reloaded = SettingsStore(db=db)
    sensors = reloaded.get_sensors()
    assert "aabbccddeeff" in sensors


# -- persistence ---------------------------------------------------------------


def test_store_persists_and_loads(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    store1 = SettingsStore(db=db)
    store1.add_car({"name": "Persisted Car", "type": "suv"})
    store1.update_speed_source({"speedSource": "manual", "manualSpeedKph": 60})
    store1.set_sensor("11:22:33:44:55:66", {"name": "Rear", "location": "rear_left_wheel"})

    store2 = SettingsStore(db=db)
    snap = store2.snapshot()
    assert len(snap["cars"]) == 2
    assert snap["cars"][1]["name"] == "Persisted Car"
    assert snap["speedSource"] == "manual"
    assert snap["manualSpeedKph"] == 60.0
    assert snap["sensorsByMac"]["112233445566"]["name"] == "Rear"


def test_store_handles_no_db() -> None:
    store = SettingsStore()
    # Should fall back to defaults without crashing
    assert len(store.snapshot()["cars"]) == 1


def test_parse_manual_speed_returns_none_for_invalid() -> None:
    assert _parse_manual_speed(None) is None
    assert _parse_manual_speed("not_a_number") is None
    assert _parse_manual_speed(-5) is None
    assert _parse_manual_speed(0) is None
    assert _parse_manual_speed(60) == 60.0


def test_store_update_car_name_and_type() -> None:
    store = SettingsStore()
    cars = store.get_cars()["cars"]
    car_id = cars[0]["id"]
    result = store.update_car(car_id, {"name": "Updated", "type": "SUV"})
    updated = next(c for c in result["cars"] if c["id"] == car_id)
    assert updated["name"] == "Updated"
    assert updated["type"] == "SUV"


def test_store_update_car_unknown_raises() -> None:
    store = SettingsStore()
    with pytest.raises(ValueError, match="Unknown car id"):
        store.update_car("nonexistent", {"name": "X"})


def test_store_delete_car_switches_active() -> None:
    store = SettingsStore()
    added = store.add_car({"name": "Second"})
    car_ids = [c["id"] for c in added["cars"]]
    store.set_active_car(car_ids[1])
    result = store.delete_car(car_ids[1])
    # Active car should switch to remaining car
    assert result["activeCarId"] == car_ids[0]


def test_store_delete_car_unknown_raises() -> None:
    store = SettingsStore()
    store.add_car({"name": "Extra"})
    with pytest.raises(ValueError, match="Unknown car id"):
        store.delete_car("nonexistent")


def test_store_language_roundtrip() -> None:
    store = SettingsStore()
    assert store.language == "en"
    assert store.set_language("nl") == "nl"
    assert store.language == "nl"


def test_store_corrupted_snapshot_falls_back_to_defaults(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    # Write invalid JSON directly into the settings_kv table
    db.set_setting("settings_snapshot", "not-valid-json{{{")
    store = SettingsStore(db=db)
    snap = store.snapshot()
    assert len(snap["cars"]) == 1
    assert snap["speedSource"] == "gps"


def test_store_snapshot_with_empty_cars_falls_back(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    db.set_settings_snapshot({"cars": [], "activeCarId": ""})
    store = SettingsStore(db=db)
    snap = store.snapshot()
    # Should fall back to one default car
    assert len(snap["cars"]) >= 1
    assert snap["activeCarId"] == snap["cars"][0]["id"]
