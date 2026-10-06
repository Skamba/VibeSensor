"""Shared snapshot persistence coordinator for focused settings services."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from threading import RLock
from typing import TYPE_CHECKING, TypeVar

from vibesensor.common.exceptions import PersistenceError
from vibesensor.settings.car_config import car_from_persistence_dict, car_to_persistence_dict
from vibesensor.settings.car_settings import CarSettingsState
from vibesensor.settings.sensor_config import SensorConfig
from vibesensor.settings.sensor_settings import SensorSettingsState
from vibesensor.settings.settings_snapshot import SettingsSnapshotPayload
from vibesensor.settings.settings_transaction import update_with_rollback
from vibesensor.settings.speed_source_settings import SpeedSourceSettingsState
from vibesensor.settings.ui_preferences import UiPreferencesState
from vibesensor.speed.speed_source_config import SpeedSourceConfig

if TYPE_CHECKING:
    from vibesensor.domain.car import Car
    from vibesensor.history.history_db import HistoryDB

__all__ = ["SettingsPersistenceCoordinator"]

LOGGER = logging.getLogger(__name__)

_SettingsSnapshotT = TypeVar("_SettingsSnapshotT")
_SettingsResultT = TypeVar("_SettingsResultT")


class SettingsPersistenceCoordinator:
    """Own only the shared load/save/rollback mechanics for settings snapshots."""

    __slots__ = (
        "_car_state",
        "_db",
        "_lock",
        "_sensor_state",
        "_speed_source_state",
        "_ui_preferences_state",
    )

    def __init__(
        self,
        db: HistoryDB | None = None,
    ) -> None:
        self._lock = RLock()
        self._db = db
        self._car_state = CarSettingsState()
        self._sensor_state = SensorSettingsState()
        self._speed_source_state = SpeedSourceSettingsState()
        self._ui_preferences_state = UiPreferencesState()
        self._load()

    @property
    def lock(self) -> RLock:
        return self._lock

    @property
    def car_state(self) -> CarSettingsState:
        return self._car_state

    @property
    def sensor_state(self) -> SensorSettingsState:
        return self._sensor_state

    @property
    def speed_source_state(self) -> SpeedSourceSettingsState:
        return self._speed_source_state

    @property
    def ui_preferences_state(self) -> UiPreferencesState:
        return self._ui_preferences_state

    def _load(self) -> None:
        if self._db is None:
            return
        snapshot = self._db.get_settings_snapshot()
        if snapshot is None:
            return

        with self._lock:
            cars = [car_from_persistence_dict(car) for car in snapshot["cars"]]
            self._car_state.cars = _with_library_fields(cars)
            filled_in = any(
                new is not old for new, old in zip(self._car_state.cars, cars, strict=True)
            )

            active_id = snapshot["activeCarId"] or ""
            car_ids = {car.id for car in self._car_state.cars}
            self._car_state.active_car_id = active_id if active_id in car_ids else None

            self._speed_source_state.config = SpeedSourceConfig.from_dict(snapshot)
            self._ui_preferences_state.language = snapshot["language"]
            self._ui_preferences_state.speed_unit = snapshot["speedUnit"]
            self._ui_preferences_state.time_zone = snapshot["timeZone"]

            self._sensor_state.sensors = {
                sensor_id: SensorConfig.from_dict(sensor_id, value)
                for sensor_id, value in snapshot["sensorsByMac"].items()
            }
            if filled_in:
                try:
                    self._persist()
                except PersistenceError:
                    LOGGER.warning("Drive layouts filled in from the car library were not saved")

    def snapshot(self) -> SettingsSnapshotPayload:
        with self._lock:
            return {
                "cars": [car_to_persistence_dict(car) for car in self._car_state.cars],
                "activeCarId": self._car_state.active_car_id,
                **self._speed_source_state.config.to_dict(),
                "language": self._ui_preferences_state.language,
                "speedUnit": self._ui_preferences_state.speed_unit,
                "timeZone": self._ui_preferences_state.time_zone,
                "sensorsByMac": {
                    sensor_id: config.to_dict()
                    for sensor_id, config in self._sensor_state.sensors.items()
                },
            }

    def _persist(self) -> None:
        if self._db is None:
            return
        payload = self.snapshot()
        try:
            self._db.set_settings_snapshot(payload)
        except (sqlite3.Error, OSError) as exc:
            LOGGER.error("Failed to persist settings to SQLite", exc_info=True)
            raise PersistenceError("Failed to persist settings to SQLite") from exc

    def update_with_rollback(
        self,
        *,
        snapshot: Callable[[], _SettingsSnapshotT],
        apply: Callable[[_SettingsSnapshotT], bool],
        restore: Callable[[_SettingsSnapshotT], None],
        audit_log: Callable[[_SettingsSnapshotT], None] | None = None,
        after_persist: Callable[[], None] | None = None,
        result: Callable[[], _SettingsResultT],
    ) -> _SettingsResultT:
        return update_with_rollback(
            lock=self._lock,
            persist=self._persist,
            snapshot=snapshot,
            apply=apply,
            restore=restore,
            audit_log=audit_log,
            after_persist=after_persist,
            result=result,
        )


def _with_library_fields(cars: list[Car]) -> list[Car]:
    """Fill the drive layout and powertrain of cars saved before they existed.

    Only a car picked from the library (it has a variant) and missing one of
    them needs the library, so the library is loaded only then.
    """

    if all(
        (car.drive_layout is not None and car.fuel_type is not None) or not car.variant
        for car in cars
    ):
        return cars
    from vibesensor.settings.car_library import with_library_fields

    return [with_library_fields(car) for car in cars]
