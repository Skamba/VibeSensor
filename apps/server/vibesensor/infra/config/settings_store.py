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
from threading import RLock
from typing import cast, get_args

from vibesensor.domain import (
    Car,
    Sensor,
    SensorPlacement,
    SpeedSource,
    normalize_sensor_id,
)
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.infra.config.car_settings import CarSettingsMixin
from vibesensor.infra.config.car_settings import _clamp_str as _clamp_str
from vibesensor.shared.exceptions import PersistenceError as PersistenceError
from vibesensor.shared.ports import SettingsSnapshotPersistence, SpeedSourceSync
from vibesensor.shared.types.backend_types import (
    LanguageCode,
    SensorConfig,
    SensorConfigUpdatePayload,
    SensorsByMacPayload,
    SettingsSnapshotPayload,
    SpeedSourceConfig,
    SpeedSourcePayload,
    SpeedSourceUpdatePayload,
    SpeedUnitCode,
    car_to_persistence_dict,
)
from vibesensor.shared.types.json_types import JsonObject

LOGGER = logging.getLogger(__name__)

VALID_LANGUAGES: frozenset[str] = frozenset(get_args(LanguageCode))
"""Supported UI languages — derived from ``LanguageCode``."""

VALID_SPEED_UNITS: frozenset[str] = frozenset(get_args(SpeedUnitCode))
"""Supported speed display units — derived from ``SpeedUnitCode``."""


def _normalize_choice(value: object, default: str) -> str:
    """Normalize a choice-like value into a lowercase trimmed token."""
    return str(value or default).strip().lower()


def _coerce_language(value: object) -> LanguageCode:
    language = _normalize_choice(value, "en")
    return "nl" if language.startswith("nl") else "en"


def _coerce_speed_unit(value: object) -> SpeedUnitCode:
    unit = _normalize_choice(value, "kmh")
    return "mps" if unit == "mps" else "kmh"


def _validated_language(value: object) -> LanguageCode | None:
    normalized = _normalize_choice(value, "")
    if normalized == "en":
        return "en"
    if normalized == "nl":
        return "nl"
    return None


def _validated_speed_unit(value: object) -> SpeedUnitCode | None:
    normalized = _normalize_choice(value, "")
    if normalized == "kmh":
        return "kmh"
    if normalized == "mps":
        return "mps"
    return None


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
        raw = self._db.get_settings_snapshot()
        if not isinstance(raw, dict):
            return

        with self._lock:
            # Cars
            raw_cars = raw.get("cars")
            if isinstance(raw_cars, list) and raw_cars:
                self._cars = [Car.from_persisted_dict(c) for c in raw_cars if isinstance(c, dict)]

            active_id = str(raw.get("activeCarId") or "")
            car_ids = {c.id for c in self._cars}
            self._active_car_id = active_id if active_id in car_ids else None

            # Speed source
            self._speed_cfg = SpeedSourceConfig.from_dict(
                {
                    "speedSource": raw.get("speedSource"),
                    "manualSpeedKph": raw.get("manualSpeedKph"),
                    "staleTimeoutS": raw.get("staleTimeoutS"),
                },
            )
            self._language = _coerce_language(raw.get("language"))
            self._speed_unit = _coerce_speed_unit(raw.get("speedUnit"))

            # Sensors
            sensors = raw.get("sensorsByMac")
            if isinstance(sensors, dict):
                normalized: dict[str, SensorConfig] = {}
                for mac, value in sensors.items():
                    if not isinstance(value, dict):
                        continue
                    try:
                        sensor_id = normalize_sensor_id(str(mac))
                    except ValueError:
                        continue
                    normalized[sensor_id] = SensorConfig.from_dict(sensor_id, value)
                self._sensors = normalized

    def _persist(self) -> None:
        if self._db is None:
            return
        payload = self.snapshot()
        try:
            self._db.set_settings_snapshot(cast("JsonObject", payload))
        except (sqlite3.Error, OSError) as exc:
            LOGGER.error("Failed to persist settings to SQLite", exc_info=True)
            raise PersistenceError("Failed to persist settings to SQLite") from exc

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
        self._gps_monitor.set_manual_source_selected(ss.is_manual)
        self._gps_monitor.set_speed_override_kmh(ss.effective_speed_kmh)
        self._gps_monitor.set_fallback_settings(
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
        with self._lock:
            old_dict = self._speed_cfg.to_dict()
            self._speed_cfg.apply_update(data)
            try:
                self._persist()
            except PersistenceError:
                self._speed_cfg = SpeedSourceConfig.from_dict(old_dict)
                raise
            self._sync_speed_source()
            return self._speed_cfg.to_dict()

    # -- sensors ---------------------------------------------------------------

    def get_sensors(self) -> SensorsByMacPayload:
        with self._lock:
            return {sid: s.to_dict() for sid, s in self._sensors.items()}

    def set_sensor(self, mac: str, data: SensorConfigUpdatePayload) -> SensorsByMacPayload:
        sensor_id = normalize_sensor_id(mac)
        with self._lock:
            existing = self._sensors.get(sensor_id)
            is_new = existing is None
            if existing is None:
                existing = SensorConfig(sensor_id=sensor_id, name=sensor_id, location_code="")
            old_name, old_location = existing.name, existing.location_code
            if "name" in data:
                name = _clamp_str(data["name"], 64)
                existing.name = name or sensor_id
            if "location_code" in data:
                existing.location_code = _clamp_str(data["location_code"], 64)
            self._sensors[sensor_id] = existing
            try:
                self._persist()
            except PersistenceError:
                if is_new:
                    self._sensors.pop(sensor_id, None)
                else:
                    existing.name, existing.location_code = old_name, old_location
                raise
            return {sensor_id: existing.to_dict()}

    def remove_sensor(self, mac: str) -> bool:
        sensor_id = normalize_sensor_id(mac)
        with self._lock:
            old_sensor = self._sensors.pop(sensor_id, None)
            if old_sensor is None:
                return False
            try:
                self._persist()
            except PersistenceError:
                self._sensors[sensor_id] = old_sensor
                raise
            return True

    @property
    def language(self) -> LanguageCode:
        with self._lock:
            return self._language

    def set_language(self, value: str) -> LanguageCode:
        language = _validated_language(value)
        if language is None:
            raise ValueError(f"language must be one of {sorted(VALID_LANGUAGES)}")
        with self._lock:
            old_language = self._language
            self._language = language
            try:
                self._persist()
            except PersistenceError:
                self._language = old_language
                raise
            return self._language

    @property
    def speed_unit(self) -> SpeedUnitCode:
        with self._lock:
            return self._speed_unit

    def set_speed_unit(self, value: str) -> SpeedUnitCode:
        unit = _validated_speed_unit(value)
        if unit is None:
            raise ValueError(f"speed_unit must be one of {sorted(VALID_SPEED_UNITS)}")
        with self._lock:
            old_unit = self._speed_unit
            self._speed_unit = unit
            try:
                self._persist()
            except PersistenceError:
                self._speed_unit = old_unit
                raise
            return self._speed_unit
