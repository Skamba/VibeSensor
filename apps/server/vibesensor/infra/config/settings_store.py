"""Settings store — persists user settings and exposes semantic settings CRUD.

``SettingsStore`` provides thread-safe read/write access to JSON-backed
settings and exposes the canonical vehicle and analysis settings to other
modules at runtime.

Boundary note
-------------
Settings management spans two layers:

- ``vibesensor.app.config_schema`` / ``AppConfig`` — deployment and process
  configuration loaded at startup (network bindings, retention windows, update
  paths, processing budgets).
- ``settings_store.py`` (this module) — user-facing settings (cars, speed
  source, language, unit, sensors) persisted through a narrow snapshot
  persistence port. Derived analysis/current-context reads and runtime
  application now live in explicit collaborators.
- concrete adapters such as ``history_db/`` implement
  ``get_settings_snapshot()`` / ``set_settings_snapshot()`` and persist
  settings as a single JSON blob.

Per-run captures and history rows then store snapshots derived from those
runtime settings; they are not a second mutable settings source.

``SettingsStore`` owns the semantic meaning of persisted settings and delegates
persistence to its injected snapshot-store collaborator.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from threading import RLock
from typing import TypeVar, get_args

from vibesensor.domain import (
    AnalysisSettingsSnapshot,
    Car,
    CarSnapshot,
    Sensor,
    SensorPlacement,
    SpeedSource,
    normalize_sensor_id,
)
from vibesensor.infra.config.car_settings import (
    CarSettingsService,
    CarSettingsState,
    _clamp_str,
)
from vibesensor.infra.config.settings_derivation import analysis_settings_snapshot_from_aspects
from vibesensor.infra.config.settings_transaction import update_with_rollback
from vibesensor.infra.location_assignment_validator import (
    AssignedLocation,
    LocationAssignmentValidator,
)
from vibesensor.shared.boundaries.settings_snapshot_codec import (
    coerce_language_code as _coerce_language,
)
from vibesensor.shared.boundaries.settings_snapshot_codec import (
    coerce_speed_unit_code as _coerce_speed_unit,
)
from vibesensor.shared.boundaries.settings_snapshot_codec import (
    validated_language_code as _validated_language,
)
from vibesensor.shared.boundaries.settings_snapshot_codec import (
    validated_speed_unit_code as _validated_speed_unit,
)
from vibesensor.shared.exceptions import PersistenceError
from vibesensor.shared.ports import SettingsSnapshotPersistence
from vibesensor.shared.structured_logging import log_extra
from vibesensor.shared.types.car_config import (
    CarConfigUpdatePayload,
    CarsSnapshot,
    car_to_persistence_dict,
)
from vibesensor.shared.types.sensor_config import (
    SensorConfig,
    SensorConfigUpdatePayload,
    SensorsByMacPayload,
)
from vibesensor.shared.types.settings_snapshot import SettingsSnapshotPayload
from vibesensor.shared.types.settings_types import (
    AnalysisSettingsPayload,
    LanguageCode,
    SpeedUnitCode,
)
from vibesensor.shared.types.speed_source_config import (
    SpeedSourceConfig,
    SpeedSourcePayload,
    SpeedSourceUpdatePayload,
)

LOGGER = logging.getLogger(__name__)
_LOCATION_VALIDATOR = LocationAssignmentValidator()

VALID_LANGUAGES: frozenset[str] = frozenset(get_args(LanguageCode))
"""Supported UI languages — derived from ``LanguageCode``."""

VALID_SPEED_UNITS: frozenset[str] = frozenset(get_args(SpeedUnitCode))
"""Supported speed display units — derived from ``SpeedUnitCode``."""

_SettingsSnapshotT = TypeVar("_SettingsSnapshotT")
_SettingsResultT = TypeVar("_SettingsResultT")


def _log_settings_change(*, action: str, before: object, after: object, **fields: object) -> None:
    LOGGER.info(
        "settings_change",
        extra=log_extra(
            event="settings_change",
            settings_action=action,
            before=before,
            after=after,
            **fields,
        ),
    )


class SettingsStore:
    """Holds the full app settings: cars, speed source, and sensors.

    Persistence is backed by a snapshot-store collaborator.
    When no *db* is provided the store operates in memory only (useful for tests).
    """

    def __init__(
        self,
        db: SettingsSnapshotPersistence | None = None,
    ) -> None:
        """Initialise the settings store, loading persisted settings from *db* if provided."""
        self._lock = RLock()
        self._db = db
        self._after_speed_source_change: Callable[[], None] | None = None
        self._car_state = CarSettingsState()
        self._speed_cfg = SpeedSourceConfig.default()
        self._language: LanguageCode = "en"
        self._speed_unit: SpeedUnitCode = "kmh"
        self._sensors: dict[str, SensorConfig] = {}
        self._car_settings = CarSettingsService(
            lock=self._lock,
            state=self._car_state,
            update_with_rollback=self._update_with_rollback,
        )

        self._load()

    # -- persistence -----------------------------------------------------------

    def _load(self) -> None:
        if self._db is None:
            return
        snapshot = self._db.get_settings_snapshot()
        if snapshot is None:
            return

        with self._lock:
            self._car_state.cars = [Car.from_persisted_dict(car) for car in snapshot["cars"]]

            active_id = snapshot["activeCarId"] or ""
            car_ids = {c.id for c in self._car_state.cars}
            self._car_state.active_car_id = active_id if active_id in car_ids else None

            self._speed_cfg = SpeedSourceConfig.from_dict(snapshot)
            self._language = _coerce_language(snapshot["language"])
            self._speed_unit = _coerce_speed_unit(snapshot["speedUnit"])

            self._sensors = {
                sensor_id: SensorConfig.from_dict(sensor_id, value)
                for sensor_id, value in snapshot["sensorsByMac"].items()
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

    def _update_with_rollback(
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

    def analysis_settings_snapshot(self) -> AnalysisSettingsSnapshot:
        """Return the current typed analysis snapshot derived from the active car."""
        return analysis_settings_snapshot_from_aspects(self.active_car_aspects())

    def bind_speed_source_sync(self, callback: Callable[[], None]) -> None:
        """Register the runtime speed-source applier used after persisted updates."""
        self._after_speed_source_change = callback

    # -- full snapshot ---------------------------------------------------------

    def snapshot(self) -> SettingsSnapshotPayload:
        with self._lock:
            return {
                "cars": [car_to_persistence_dict(car) for car in self._car_state.cars],
                "activeCarId": self._car_state.active_car_id,
                **self._speed_cfg.to_dict(),
                "language": self._language,
                "speedUnit": self._speed_unit,
                "sensorsByMac": {sid: s.to_dict() for sid, s in self._sensors.items()},
            }

    # -- car settings -----------------------------------------------------------

    def active_car(self) -> Car | None:
        return self._car_settings.active_car()

    def get_cars(self) -> CarsSnapshot:
        return self._car_settings.get_cars()

    def active_car_aspects(self) -> AnalysisSettingsPayload | None:
        return self._car_settings.active_car_aspects()

    def active_car_snapshot(self) -> CarSnapshot | None:
        return self._car_settings.active_car_snapshot()

    def set_active_car(self, car_id: str) -> CarsSnapshot:
        return self._car_settings.set_active_car(car_id)

    def add_car(self, car_data: CarConfigUpdatePayload) -> CarsSnapshot:
        return self._car_settings.add_car(car_data)

    def update_car(self, car_id: str, car_data: CarConfigUpdatePayload) -> CarsSnapshot:
        return self._car_settings.update_car(car_id, car_data)

    def update_active_car_aspects(
        self,
        aspects: AnalysisSettingsPayload,
    ) -> AnalysisSettingsPayload:
        return self._car_settings.update_active_car_aspects(aspects)

    def delete_car(self, car_id: str) -> CarsSnapshot:
        return self._car_settings.delete_car(car_id)

    # -- domain-object accessors -----------------------------------------------

    def speed_source(self) -> SpeedSource:
        """Return the current speed source as a domain ``SpeedSource`` value object."""
        with self._lock:
            return self._speed_cfg.to_speed_source()

    def sensors(self) -> list[Sensor]:
        """Return all configured sensors as domain ``Sensor`` value objects."""
        with self._lock:
            return [
                Sensor(
                    sensor_id=cfg.sensor_id,
                    name=cfg.name,
                    placement=(
                        SensorPlacement.from_code(cfg.location_code) if cfg.location_code else None
                    ),
                )
                for cfg in self._sensors.values()
            ]

    # -- speed source ----------------------------------------------------------

    def get_speed_source(self) -> SpeedSourcePayload:
        with self._lock:
            return self._speed_cfg.to_dict()

    def update_speed_source(self, data: SpeedSourceUpdatePayload) -> SpeedSourcePayload:
        def _apply(_previous: SpeedSourcePayload) -> bool:
            self._speed_cfg.apply_update(data)
            return True

        return self._update_with_rollback(
            snapshot=self._speed_cfg.to_dict,
            apply=_apply,
            restore=lambda previous: setattr(
                self,
                "_speed_cfg",
                SpeedSourceConfig.from_dict(previous),
            ),
            audit_log=lambda previous: _log_settings_change(
                action="update_speed_source",
                before=previous,
                after=self._speed_cfg.to_dict(),
            ),
            after_persist=self._after_speed_source_change,
            result=self._speed_cfg.to_dict,
        )

    # -- sensors ---------------------------------------------------------------

    def get_sensors(self) -> SensorsByMacPayload:
        with self._lock:
            return {sid: s.to_dict() for sid, s in self._sensors.items()}

    def _sensor_configs_snapshot_unlocked(self) -> dict[str, SensorConfig]:
        return {
            sensor_id: SensorConfig.from_dict(sensor_id, cfg.to_dict())
            for sensor_id, cfg in self._sensors.items()
        }

    def set_sensor(self, mac: str, data: SensorConfigUpdatePayload) -> SensorsByMacPayload:
        sensor_id = normalize_sensor_id(mac)

        def _apply(_previous: dict[str, SensorConfig]) -> bool:
            existing = self._sensors.get(sensor_id)
            if existing is None:
                updated = SensorConfig(sensor_id=sensor_id, name=sensor_id, location_code="")
            else:
                updated = SensorConfig.from_dict(sensor_id, existing.to_dict())
            if "name" in data:
                name = _clamp_str(data["name"], 64)
                updated.name = name or sensor_id
            if "location_code" in data:
                location_code = _clamp_str(data["location_code"], 64)
                _LOCATION_VALIDATOR.validate_assignment(
                    owner_id=sensor_id,
                    location_code=location_code,
                    assigned_locations=(
                        AssignedLocation(
                            owner_id=other_id,
                            owner_name=other.name or other.sensor_id,
                            location_code=other.location_code,
                        )
                        for other_id, other in self._sensors.items()
                    ),
                )
                updated.location_code = location_code
            self._sensors[sensor_id] = updated
            return True

        return self._update_with_rollback(
            snapshot=self._sensor_configs_snapshot_unlocked,
            apply=_apply,
            restore=lambda previous: setattr(self, "_sensors", previous),
            audit_log=lambda previous: _log_settings_change(
                action="set_sensor",
                before=(
                    previous_sensor.to_dict()
                    if (previous_sensor := previous.get(sensor_id)) is not None
                    else None
                ),
                after=self._sensors[sensor_id].to_dict(),
                sensor_id=sensor_id,
            ),
            result=lambda: {sensor_id: self._sensors[sensor_id].to_dict()},
        )

    def remove_sensor(self, mac: str) -> bool:
        sensor_id = normalize_sensor_id(mac)
        removed = False

        def _apply(_previous: dict[str, SensorConfig]) -> bool:
            nonlocal removed
            removed = self._sensors.pop(sensor_id, None) is not None
            return removed

        return self._update_with_rollback(
            snapshot=self._sensor_configs_snapshot_unlocked,
            apply=_apply,
            restore=lambda previous: setattr(self, "_sensors", previous),
            audit_log=lambda previous: _log_settings_change(
                action="remove_sensor",
                before=(
                    previous_sensor.to_dict()
                    if (previous_sensor := previous.get(sensor_id)) is not None
                    else None
                ),
                after=None,
                sensor_id=sensor_id,
            ),
            result=lambda: removed,
        )

    @property
    def language(self) -> LanguageCode:
        with self._lock:
            return self._language

    def set_language(self, value: str) -> LanguageCode:
        language = _validated_language(value)
        if language is None:
            raise ValueError(f"language must be one of {sorted(VALID_LANGUAGES)}")

        def _apply(_previous: LanguageCode) -> bool:
            self._language = language
            return True

        return self._update_with_rollback(
            snapshot=lambda: self._language,
            apply=_apply,
            restore=lambda previous: setattr(self, "_language", previous),
            audit_log=lambda previous: _log_settings_change(
                action="set_language",
                before=previous,
                after=self._language,
            ),
            result=lambda: self._language,
        )

    @property
    def speed_unit(self) -> SpeedUnitCode:
        with self._lock:
            return self._speed_unit

    def set_speed_unit(self, value: str) -> SpeedUnitCode:
        unit = _validated_speed_unit(value)
        if unit is None:
            raise ValueError(f"speed_unit must be one of {sorted(VALID_SPEED_UNITS)}")

        def _apply(_previous: SpeedUnitCode) -> bool:
            self._speed_unit = unit
            return True

        return self._update_with_rollback(
            snapshot=lambda: self._speed_unit,
            apply=_apply,
            restore=lambda previous: setattr(self, "_speed_unit", previous),
            audit_log=lambda previous: _log_settings_change(
                action="set_speed_unit",
                before=previous,
                after=self._speed_unit,
            ),
            result=lambda: self._speed_unit,
        )
