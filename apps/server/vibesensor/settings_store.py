"""Settings store — persists user settings (car profile, analysis config, etc.).

``SettingsStore`` provides thread-safe read/write access to JSON-backed
settings and exposes the canonical vehicle and analysis settings to other
modules at runtime.

Boundary note
-------------
Settings management spans three layers:

- ``settings_store.py`` (this module) — user-facing settings (cars, speed
  source, language, unit, sensors) persisted to ``HistoryDB``.
- ``analysis_settings.py`` — in-memory-only analysis parameter store
  (tire_diameter, tire_aspect, etc.) recomputed from the active car's
  aspects whenever car settings change.
- ``history_db/_settings.py`` — raw DB-level ``get_setting()`` /
  ``set_setting()`` key-value operations.

``SettingsStore`` owns the semantic meaning of settings, delegates
persistence to ``HistoryDB._settings``, and is the canonical source for
runtime settings queries.
"""

from __future__ import annotations

import logging
import sqlite3
from threading import RLock
from typing import TYPE_CHECKING, cast

from .backend_types import (
    AnalysisSettingsPayload,
    CarConfigPayload,
    CarConfigUpdatePayload,
    CarsPayload,
    LanguageCode,
    SensorConfigUpdatePayload,
    SensorsByMacPayload,
    SettingsSnapshotPayload,
    SpeedSourcePayload,
    SpeedSourceUpdatePayload,
    SpeedUnitCode,
)
from .domain_models import (
    CarConfig,
    SensorConfig,
    SpeedSourceConfig,
    new_car_id,
    normalize_sensor_id,
    sanitize_aspects,
)
from .exceptions import PersistenceError as PersistenceError
from .json_types import JsonObject

if TYPE_CHECKING:
    from .history_db import HistoryDB

LOGGER = logging.getLogger(__name__)

VALID_LANGUAGES: frozenset[str] = frozenset({"en", "nl"})
"""Supported UI languages."""

VALID_SPEED_UNITS: frozenset[str] = frozenset({"kmh", "mps"})
"""Supported speed display units."""


def _clamp_str(value: object, maxlen: int) -> str:
    """Strip and truncate *value* to *maxlen* characters."""
    return str(value).strip()[:maxlen]


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


class SettingsStore:
    """Holds the full app settings: cars, speed source, and sensors.

    Persistence is backed by a :class:`HistoryDB` instance (SQLite).
    When no *db* is provided the store operates in memory only (useful for tests).
    """

    def __init__(self, db: HistoryDB | None = None) -> None:
        """Initialise the settings store, loading persisted settings from *db* if provided."""
        self._lock = RLock()
        self._db = db

        self._cars: list[CarConfig] = []
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
                self._cars = [CarConfig.from_dict(c) for c in raw_cars if isinstance(c, dict)]

            active_id = str(raw.get("activeCarId") or "")
            car_ids = {c.id for c in self._cars}
            self._active_car_id = active_id if active_id in car_ids else None

            # Speed source
            self._speed_cfg = SpeedSourceConfig.from_dict(
                {
                    "speedSource": raw.get("speedSource"),
                    "manualSpeedKph": raw.get("manualSpeedKph"),
                    "obd2Config": raw.get("obd2Config"),
                    "staleTimeoutS": raw.get("staleTimeoutS"),
                    "fallbackMode": raw.get("fallbackMode"),
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

    # -- full snapshot ---------------------------------------------------------

    def snapshot(self) -> SettingsSnapshotPayload:
        with self._lock:
            return {
                "cars": [c.to_dict() for c in self._cars],
                "activeCarId": self._active_car_id,
                **self._speed_cfg.to_dict(),
                "language": self._language,
                "speedUnit": self._speed_unit,
                "sensorsByMac": {sid: s.to_dict() for sid, s in self._sensors.items()},
            }

    # -- car operations --------------------------------------------------------

    def get_cars(self) -> CarsPayload:
        with self._lock:
            return {
                "cars": [c.to_dict() for c in self._cars],
                "activeCarId": self._active_car_id,
            }

    def active_car_aspects(self) -> dict[str, float] | None:
        """Return the active car's aspects as a flat analysis-settings dict."""
        with self._lock:
            car = self._find_car(self._active_car_id)
            return dict(car.aspects) if car else None

    def active_car_snapshot(self) -> CarConfigPayload | None:
        """Return the active car profile as a plain dict snapshot."""
        with self._lock:
            car = self._find_car(self._active_car_id)
            return car.to_dict() if car else None

    def _find_car(self, car_id: str | None) -> CarConfig | None:
        if not car_id:
            return None
        return next((c for c in self._cars if c.id == car_id), None)

    def set_active_car(self, car_id: str) -> CarsPayload:
        with self._lock:
            car = self._find_car(car_id)
            if car is None:
                raise ValueError(f"Unknown car id: {car_id}")
            old_active = self._active_car_id
            self._active_car_id = car_id
            try:
                self._persist()
            except PersistenceError:
                self._active_car_id = old_active
                raise
            return self.get_cars()

    def add_car(self, car_data: CarConfigUpdatePayload) -> CarsPayload:
        with self._lock:
            payload: dict[str, object] = dict(car_data)
            payload["id"] = new_car_id()
            car = CarConfig.from_dict(payload)
            self._cars.append(car)
            try:
                self._persist()
            except PersistenceError:
                self._cars.pop()  # rollback in-memory append
                raise
            return self.get_cars()

    def update_car(self, car_id: str, car_data: CarConfigUpdatePayload) -> CarsPayload:
        with self._lock:
            car = self._find_car(car_id)
            if car is None:
                raise ValueError(f"Unknown car id: {car_id}")
            # Snapshot for rollback
            old_name, old_type = car.name, car.type
            old_aspects = dict(car.aspects)
            old_variant = car.variant
            if "name" in car_data:
                raw_name = car_data["name"]
                if isinstance(raw_name, str):
                    name = _clamp_str(raw_name, 64)
                    if name:
                        car.name = name
            if "type" in car_data:
                raw_type = car_data["type"]
                if isinstance(raw_type, str):
                    car_type = _clamp_str(raw_type, 32)
                    if car_type:
                        car.type = car_type
            if "aspects" in car_data and isinstance(car_data["aspects"], dict):
                car.aspects.update(sanitize_aspects(car_data["aspects"]))
            if "variant" in car_data:
                raw = car_data["variant"]
                car.variant = _clamp_str(raw, 64) or None if isinstance(raw, str) and raw else None
            try:
                self._persist()
            except PersistenceError:
                car.name, car.type = old_name, old_type
                car.aspects.clear()
                car.aspects.update(old_aspects)
                car.variant = old_variant
                raise
            return self.get_cars()

    def update_active_car_aspects(
        self,
        aspects: AnalysisSettingsPayload,
    ) -> AnalysisSettingsPayload:
        with self._lock:
            car = self._find_car(self._active_car_id)
            if car is None:
                raise ValueError("No active car configured")
            old_aspects = dict(car.aspects)
            car.aspects.update(sanitize_aspects(aspects))
            try:
                self._persist()
            except PersistenceError:
                car.aspects.clear()
                car.aspects.update(old_aspects)
                raise
            return dict(car.aspects)

    def delete_car(self, car_id: str) -> CarsPayload:
        with self._lock:
            car = self._find_car(car_id)
            if car is None:
                raise ValueError(f"Unknown car id: {car_id}")
            if len(self._cars) <= 1:
                raise ValueError("Cannot delete the last car")
            old_cars = list(self._cars)
            old_active = self._active_car_id
            self._cars = [c for c in self._cars if c.id != car_id]
            if self._active_car_id == car_id:
                self._active_car_id = self._cars[0].id if self._cars else None
            try:
                self._persist()
            except PersistenceError:
                self._cars = old_cars
                self._active_car_id = old_active
                raise
            return self.get_cars()

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
                existing = SensorConfig(sensor_id=sensor_id, name=sensor_id, location="")
            old_name, old_location = existing.name, existing.location
            if "name" in data:
                name = _clamp_str(data["name"], 64)
                existing.name = name or sensor_id
            if "location" in data:
                existing.location = _clamp_str(data["location"], 64)
            self._sensors[sensor_id] = existing
            try:
                self._persist()
            except PersistenceError:
                if is_new:
                    self._sensors.pop(sensor_id, None)
                else:
                    existing.name, existing.location = old_name, old_location
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
