"""Cover sensor settings service mutations, defaults, and rollback behavior."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock

import pytest

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


def test_sensor_settings_set_and_get_sensor() -> None:
    settings = _sensor_settings_service()

    settings.set_sensor(
        "aa:bb:cc:dd:ee:ff",
        {"name": "FL Wheel", "location_code": "front_left_wheel"},
    )

    sensors = settings.get_sensors()
    assert "aabbccddeeff" in sensors
    assert sensors["aabbccddeeff"]["name"] == "FL Wheel"
    assert sensors["aabbccddeeff"]["location_code"] == "front_left_wheel"


def test_sensor_settings_rejects_duplicate_location() -> None:
    settings = _sensor_settings_service()
    settings.set_sensor("aa:bb:cc:dd:ee:ff", {"location_code": "front_left_wheel"})

    with pytest.raises(ValueError, match="already assigned"):
        settings.set_sensor("11:22:33:44:55:66", {"location_code": "front_left_wheel"})


def test_sensor_settings_remove_sensor() -> None:
    settings = _sensor_settings_service()
    settings.set_sensor("aa:bb:cc:dd:ee:ff", {"name": "Test"})

    assert settings.remove_sensor("aa:bb:cc:dd:ee:ff") is True
    assert settings.remove_sensor("aa:bb:cc:dd:ee:ff") is False


def test_sensor_settings_creates_entry_with_defaults() -> None:
    settings = _sensor_settings_service()

    settings.set_sensor("aa:bb:cc:dd:ee:ff", {})

    sensors = settings.get_sensors()
    assert "aabbccddeeff" in sensors
    assert sensors["aabbccddeeff"]["name"] == "aabbccddeeff"


def _raise_persistence_error() -> None:
    raise PersistenceError("disk full")


def test_sensor_settings_rolls_back_new_sensor_on_persist_error() -> None:
    settings = _sensor_settings_service(persist=_raise_persistence_error)

    with pytest.raises(PersistenceError, match="disk full"):
        settings.set_sensor("aa:bb:cc:dd:ee:ff", {"name": "FL Wheel"})

    assert settings.get_sensors() == {}
