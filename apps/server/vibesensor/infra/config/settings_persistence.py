"""Shared snapshot persistence coordinator for focused settings services."""

from __future__ import annotations

import logging
from collections.abc import Callable
from threading import RLock
from typing import TypeVar

import aiosqlite

from vibesensor.infra.config.car_settings import CarSettingsState
from vibesensor.infra.config.sensor_settings import SensorSettingsState
from vibesensor.infra.config.settings_transaction import update_with_rollback
from vibesensor.infra.config.speed_source_settings import SpeedSourceSettingsState
from vibesensor.infra.config.ui_preferences import UiPreferencesState
from vibesensor.shared.exceptions import PersistenceError
from vibesensor.shared.ports import SettingsSnapshotPersistence
from vibesensor.shared.types.car_config import car_from_persistence_dict, car_to_persistence_dict
from vibesensor.shared.types.sensor_config import SensorConfig
from vibesensor.shared.types.settings_snapshot import SettingsSnapshotPayload
from vibesensor.shared.types.speed_source_config import SpeedSourceConfig

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
        db: SettingsSnapshotPersistence | None = None,
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
            self._car_state.cars = [car_from_persistence_dict(car) for car in snapshot["cars"]]

            active_id = snapshot["activeCarId"] or ""
            car_ids = {car.id for car in self._car_state.cars}
            self._car_state.active_car_id = active_id if active_id in car_ids else None

            self._speed_source_state.config = SpeedSourceConfig.from_dict(snapshot)
            self._ui_preferences_state.language = snapshot["language"]
            self._ui_preferences_state.speed_unit = snapshot["speedUnit"]

            self._sensor_state.sensors = {
                sensor_id: SensorConfig.from_dict(sensor_id, value)
                for sensor_id, value in snapshot["sensorsByMac"].items()
            }

    def snapshot(self) -> SettingsSnapshotPayload:
        with self._lock:
            return {
                "cars": [car_to_persistence_dict(car) for car in self._car_state.cars],
                "activeCarId": self._car_state.active_car_id,
                **self._speed_source_state.config.to_dict(),
                "language": self._ui_preferences_state.language,
                "speedUnit": self._ui_preferences_state.speed_unit,
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
        except (aiosqlite.Error, OSError) as exc:
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
