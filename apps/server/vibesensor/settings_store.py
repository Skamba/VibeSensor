from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .domain_models import (
    DEFAULT_CAR_ASPECTS,
    CarConfig,
    SensorConfig,
    SpeedSourceConfig,
    _new_car_id,
    _sanitize_aspects,
    normalize_sensor_id,
)

if TYPE_CHECKING:
    from .history_db import HistoryDB

LOGGER = logging.getLogger(__name__)


class SettingsStore:
    """Holds the full app settings: cars, speed source, and sensors.

    Persistence is backed by a :class:`HistoryDB` instance (SQLite).
    When no *db* is provided the store operates in memory only (useful for tests).
    """

    def __init__(self, db: HistoryDB | None = None) -> None:
        from threading import RLock

        self._lock = RLock()
        self._db = db

        default_car = CarConfig.default()
        self._cars: list[CarConfig] = [default_car]
        self._active_car_id: str = default_car.id
        self._speed_cfg = SpeedSourceConfig.default()
        self._language: str = "en"
        self._speed_unit: str = "kmh"
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
            if not self._cars:
                default_car = CarConfig.default()
                self._cars = [default_car]

            active_id = str(raw.get("activeCarId") or "")
            car_ids = {c.id for c in self._cars}
            self._active_car_id = active_id if active_id in car_ids else self._cars[0].id

            # Speed source
            self._speed_cfg = SpeedSourceConfig.from_dict(
                {
                    "speedSource": raw.get("speedSource"),
                    "manualSpeedKph": raw.get("manualSpeedKph"),
                }
            )
            language = str(raw.get("language") or "en").strip().lower()
            self._language = language if language in {"en", "nl"} else "en"

            speed_unit = str(raw.get("speedUnit") or "kmh").strip().lower()
            self._speed_unit = speed_unit if speed_unit in {"kmh", "mps"} else "kmh"

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
            self._db.set_settings_snapshot(payload)
        except Exception:
            LOGGER.warning("Failed to persist settings to SQLite", exc_info=True)

    # -- full snapshot ---------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
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

    def get_cars(self) -> dict[str, Any]:
        with self._lock:
            return {
                "cars": [c.to_dict() for c in self._cars],
                "activeCarId": self._active_car_id,
            }

    def active_car_aspects(self) -> dict[str, float]:
        """Return the active car's aspects as a flat analysis-settings dict."""
        with self._lock:
            car = self._find_car(self._active_car_id)
            return dict(car.aspects) if car else dict(DEFAULT_CAR_ASPECTS)

    def _find_car(self, car_id: str) -> CarConfig | None:
        for c in self._cars:
            if c.id == car_id:
                return c
        return None

    def set_active_car(self, car_id: str) -> dict[str, Any]:
        with self._lock:
            car = self._find_car(car_id)
            if car is None:
                raise ValueError(f"Unknown car id: {car_id}")
            self._active_car_id = car_id
            self._persist()
            return self.get_cars()

    def add_car(self, car_data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            car_data["id"] = _new_car_id()
            car = CarConfig.from_dict(car_data)
            self._cars.append(car)
            self._persist()
            return self.get_cars()

    def update_car(self, car_id: str, car_data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            car = self._find_car(car_id)
            if car is None:
                raise ValueError(f"Unknown car id: {car_id}")
            if "name" in car_data:
                name = str(car_data["name"]).strip()[:64]
                if name:
                    car.name = name
            if "type" in car_data:
                car_type = str(car_data["type"]).strip()[:32]
                if car_type:
                    car.type = car_type
            if "aspects" in car_data and isinstance(car_data["aspects"], dict):
                car.aspects.update(_sanitize_aspects(car_data["aspects"]))
            self._persist()
            return self.get_cars()

    def update_active_car_aspects(self, aspects: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            car = self._find_car(self._active_car_id)
            if car is None:
                raise ValueError("No active car configured")
            car.aspects.update(_sanitize_aspects(aspects))
            self._persist()
            return dict(car.aspects)

    def delete_car(self, car_id: str) -> dict[str, Any]:
        with self._lock:
            if len(self._cars) <= 1:
                raise ValueError("Cannot delete the last car")
            car = self._find_car(car_id)
            if car is None:
                raise ValueError(f"Unknown car id: {car_id}")
            self._cars = [c for c in self._cars if c.id != car_id]
            if self._active_car_id == car_id:
                self._active_car_id = self._cars[0].id
            self._persist()
            return self.get_cars()

    # -- speed source ----------------------------------------------------------

    def get_speed_source(self) -> dict[str, Any]:
        with self._lock:
            return self._speed_cfg.to_dict()

    def update_speed_source(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._speed_cfg.apply_update(data)
            self._persist()
            return self._speed_cfg.to_dict()

    # -- sensors ---------------------------------------------------------------

    def get_sensors(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {sid: s.to_dict() for sid, s in self._sensors.items()}

    def set_sensor(self, mac: str, data: dict[str, Any]) -> dict[str, Any]:
        sensor_id = normalize_sensor_id(mac)
        with self._lock:
            existing = self._sensors.get(sensor_id)
            if existing is None:
                existing = SensorConfig(sensor_id=sensor_id, name=sensor_id, location="")
            if "name" in data:
                name = str(data["name"]).strip()[:64]
                existing.name = name if name else sensor_id
            if "location" in data:
                existing.location = str(data["location"]).strip()[:64]
            self._sensors[sensor_id] = existing
            self._persist()
            return {sensor_id: existing.to_dict()}

    def remove_sensor(self, mac: str) -> bool:
        sensor_id = normalize_sensor_id(mac)
        with self._lock:
            removed = self._sensors.pop(sensor_id, None) is not None
            if removed:
                self._persist()
            return removed

    @property
    def language(self) -> str:
        with self._lock:
            return self._language

    def set_language(self, value: str) -> str:
        language = str(value).strip().lower()
        if language not in {"en", "nl"}:
            raise ValueError("language must be 'en' or 'nl'")
        with self._lock:
            self._language = language
            self._persist()
            return self._language

    @property
    def speed_unit(self) -> str:
        with self._lock:
            return self._speed_unit

    def set_speed_unit(self, value: str) -> str:
        unit = str(value).strip().lower()
        if unit not in {"kmh", "mps"}:
            raise ValueError("speed_unit must be 'kmh' or 'mps'")
        with self._lock:
            self._speed_unit = unit
            self._persist()
            return self._speed_unit
