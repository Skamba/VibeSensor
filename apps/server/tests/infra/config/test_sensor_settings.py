"""Cover sensor settings service location assignment, defaults, and rollback behavior."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock

import pytest
from test_support.settings_services import build_settings_services

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.infra.config.sensor_settings import (
    SensorSettingsService,
    SensorSettingsState,
)
from vibesensor.infra.config.settings_transaction import update_with_rollback
from vibesensor.shared.exceptions import PersistenceError


def _sensor_settings_service(
    *,
    persist: Callable[[], None] | None = None,
) -> SensorSettingsService:
    lock = RLock()
    state = SensorSettingsState()

    def _persist() -> None:
        if persist is not None:
            persist()

    def _update_with_rollback(**kwargs: object):
        return update_with_rollback(lock=lock, persist=_persist, **kwargs)

    return SensorSettingsService(
        lock=lock,
        state=state,
        update_with_rollback=_update_with_rollback,
    )


def test_assign_sensor_location_sets_and_gets_sensor() -> None:
    settings = _sensor_settings_service()

    settings.assign_sensor_location("aa:bb:cc:dd:ee:ff", "front_left_wheel")

    sensors = settings.get_sensors()
    assert "aabbccddeeff" in sensors
    assert sensors["aabbccddeeff"]["name"] == "Front Left Wheel"
    assert sensors["aabbccddeeff"]["location_code"] == "front_left_wheel"


def test_assign_sensor_location_rejects_duplicate_location() -> None:
    settings = _sensor_settings_service()
    settings.assign_sensor_location("aa:bb:cc:dd:ee:ff", "front_left_wheel")

    with pytest.raises(ValueError, match="already assigned"):
        settings.assign_sensor_location("11:22:33:44:55:66", "front_left_wheel")


def test_assign_sensor_location_rejects_unknown_location_code() -> None:
    settings = _sensor_settings_service()

    with pytest.raises(ValueError, match="Unknown location_code"):
        settings.assign_sensor_location("aa:bb:cc:dd:ee:ff", "not_a_real_location")


def test_assign_sensor_location_can_clear_back_to_sensor_defaults() -> None:
    settings = _sensor_settings_service()
    settings.assign_sensor_location("aa:bb:cc:dd:ee:ff", "front_left_wheel")
    settings.assign_sensor_location("aa:bb:cc:dd:ee:ff", "")

    assert settings.get_sensors()["aabbccddeeff"] == {
        "name": "aabbccddeeff",
        "location_code": "",
    }


def _raise_persistence_error() -> None:
    raise PersistenceError("disk full")


def test_assign_sensor_location_rolls_back_new_sensor_on_persist_error() -> None:
    settings = _sensor_settings_service(persist=_raise_persistence_error)

    with pytest.raises(PersistenceError, match="disk full"):
        settings.assign_sensor_location("aa:bb:cc:dd:ee:ff", "front_left_wheel")

    assert settings.get_sensors() == {}


def test_sensor_settings_round_trip_through_shared_snapshot(tmp_path) -> None:
    db = create_history_persistence_adapters(tmp_path / "history.db")
    services = build_settings_services(db=db.settings_snapshot_repository)

    services.sensor_settings.assign_sensor_location("aa:bb:cc:dd:ee:ff", "front_left_wheel")

    reloaded = build_settings_services(db=db.settings_snapshot_repository)
    sensors = reloaded.sensor_settings.get_sensors()
    assert "aabbccddeeff" in sensors
    assert sensors["aabbccddeeff"] == {
        "name": "Front Left Wheel",
        "location_code": "front_left_wheel",
    }
