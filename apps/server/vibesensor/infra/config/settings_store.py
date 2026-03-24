"""Settings store — persists user settings (car profile, analysis config, etc.).

``SettingsStore`` provides thread-safe read/write access to JSON-backed
settings and exposes the canonical vehicle and analysis settings to other
modules at runtime.

Boundary note
-------------
Settings management spans two layers:

- ``settings_store.py`` (this module) — user-facing settings (cars, speed
  source, language, unit, sensors) persisted through a narrow snapshot
  persistence port. Also owns the in-memory analysis parameter cache
  (tire_diameter, tire_aspect, etc.) recomputed from the active car's
  aspects whenever car settings change.
- concrete adapters such as ``history_db/`` implement
  ``get_settings_snapshot()`` / ``set_settings_snapshot()`` and persist
  settings as a single JSON blob.

``SettingsStore`` owns the semantic meaning of settings, delegates
persistence to its injected snapshot-store collaborator, and is the canonical source for
runtime settings queries.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from threading import RLock
from typing import TypeVar, get_args

from vibesensor.domain import (
    Car,
    Sensor,
    SensorPlacement,
    SpeedSource,
    normalize_sensor_id,
)
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.infra.config.car_settings import (
    CarSettingsMixin,
    _clamp_str,
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
from vibesensor.shared.ports import SettingsSnapshotPersistence, SpeedSourceSync
from vibesensor.shared.structured_logging import log_extra
from vibesensor.shared.types.car_config import car_to_persistence_dict
from vibesensor.shared.types.sensor_config import (
    SensorConfig,
    SensorConfigUpdatePayload,
    SensorsByMacPayload,
)
from vibesensor.shared.types.settings_snapshot import SettingsSnapshotPayload
from vibesensor.shared.types.settings_types import LanguageCode, SpeedUnitCode
from vibesensor.shared.types.speed_source_config import (
    SpeedSourceConfig,
    SpeedSourcePayload,
    SpeedSourceUpdatePayload,
)

LOGGER = logging.getLogger(__name__)

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


class SettingsStore(CarSettingsMixin):
    """Holds the full app settings: cars, speed source, and sensors.

    Persistence is backed by a snapshot-store collaborator.
    When no *db* is provided the store operates in memory only (useful for tests).
    """

    def __init__(
        self,
        db: SettingsSnapshotPersistence | None = None,
        *,
        gps_monitor: SpeedSourceSync | None = None,
    ) -> None:
        """Initialise the settings store, loading persisted settings from *db* if provided."""
        self._lock = RLock()
        self._db = db
        self._gps_monitor = gps_monitor
        self._sanitize_analysis = AnalysisSettingsSnapshot.sanitize
        self._analysis_values: dict[str, float] = dict(AnalysisSettingsSnapshot.DEFAULTS)

        self._cars: list[Car] = []
        self._active_car_id: str | None = None
        self._speed_cfg = SpeedSourceConfig.default()
        self._language: LanguageCode = "en"
        self._speed_unit: SpeedUnitCode = "kmh"
        self._sensors: dict[str, SensorConfig] = {}

        self._load()

    # -- persistence -----------------------------------------------------------

    def _load(self) -> None:
        if self._db is None:
            return
        snapshot = self._db.get_settings_snapshot()
        if snapshot is None:
            return

        with self._lock:
            self._cars = [Car.from_persisted_dict(car) for car in snapshot["cars"]]

            active_id = snapshot["activeCarId"] or ""
            car_ids = {c.id for c in self._cars}
            self._active_car_id = active_id if active_id in car_ids else None

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
        with self._lock:
            previous = snapshot()
            changed = apply(previous)
            if not changed:
                return result()
            try:
                self._persist()
            except PersistenceError:
                restore(previous)
                raise
            if audit_log is not None:
                audit_log(previous)
            if after_persist is not None:
                after_persist()
            return result()

    def _sync_analysis_settings(self) -> None:
        """Recompute in-memory analysis settings from the active car's aspects."""
        aspects = self.active_car_aspects()
        if aspects:
            sanitized = self._sanitize_analysis(aspects)
            self._analysis_values.update(sanitized)

    def _sync_speed_source(self) -> None:
        """Push current speed-source config into the GPS monitor."""
        if self._gps_monitor is None:
            return
        ss = self.speed_source()
        raw = self.get_speed_source()
        self._gps_monitor.apply_speed_source_settings(
            effective_speed_kmh=ss.effective_speed_kmh,
            manual_source_selected=ss.is_manual,
            stale_timeout_s=raw.get("staleTimeoutS"),
        )

    def sync_all(self) -> None:
        """Push all current settings into dependent services.

        Called once at startup after all services are wired.
        """
        self._sync_analysis_settings()
        self._sync_speed_source()

    def analysis_settings_snapshot(self) -> AnalysisSettingsSnapshot:
        """Return a thread-safe typed snapshot of the current analysis settings."""
        with self._lock:
            return AnalysisSettingsSnapshot.from_dict(self._analysis_values)

    # -- full snapshot ---------------------------------------------------------

    def snapshot(self) -> SettingsSnapshotPayload:
        with self._lock:
            return {
                "cars": [car_to_persistence_dict(c) for c in self._cars],
                "activeCarId": self._active_car_id,
                **self._speed_cfg.to_dict(),
                "language": self._language,
                "speedUnit": self._speed_unit,
                "sensorsByMac": {sid: s.to_dict() for sid, s in self._sensors.items()},
            }

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
            after_persist=self._sync_speed_source,
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
                updated.location_code = _clamp_str(data["location_code"], 64)
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
