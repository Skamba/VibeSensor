from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from threading import RLock
from typing import Any

from .analysis_settings import DEFAULT_ANALYSIS_SETTINGS

LOGGER = logging.getLogger(__name__)

VALID_SPEED_SOURCES = ("gps", "obd2", "manual")

DEFAULT_CAR_ASPECTS: dict[str, float] = dict(DEFAULT_ANALYSIS_SETTINGS)

DEFAULT_CAR: dict[str, Any] = {
    "id": "",
    "name": "Default Car",
    "type": "sedan",
    "aspects": dict(DEFAULT_CAR_ASPECTS),
}


def _new_car_id() -> str:
    return str(uuid.uuid4())


def _parse_manual_speed(value: Any) -> float | None:
    """Return a positive float speed or None."""
    if isinstance(value, (int, float)) and float(value) > 0:
        return float(value)
    return None


def _sanitize_aspects(raw: dict[str, Any]) -> dict[str, float]:
    """Sanitize car aspects using the same rules as AnalysisSettingsStore."""
    positive_required = {
        "tire_width_mm",
        "tire_aspect_pct",
        "rim_in",
        "final_drive_ratio",
        "current_gear_ratio",
        "wheel_bandwidth_pct",
        "driveshaft_bandwidth_pct",
        "engine_bandwidth_pct",
        "max_band_half_width_pct",
    }
    non_negative = {
        "speed_uncertainty_pct",
        "tire_diameter_uncertainty_pct",
        "final_drive_uncertainty_pct",
        "gear_uncertainty_pct",
        "min_abs_band_hz",
    }
    out: dict[str, float] = {}
    for key in DEFAULT_CAR_ASPECTS:
        val = raw.get(key)
        if val is None:
            continue
        try:
            value = float(val)
        except (TypeError, ValueError):
            continue
        if key in positive_required and value <= 0:
            continue
        if key in non_negative and value < 0:
            continue
        out[key] = value
    return out


def _validate_car(car: dict[str, Any]) -> dict[str, Any]:
    car_id = str(car.get("id") or _new_car_id())
    name = str(car.get("name") or "Unnamed Car").strip()[:64]
    car_type = str(car.get("type") or "sedan").strip()[:32]
    raw_aspects = car.get("aspects") or {}
    aspects = dict(DEFAULT_CAR_ASPECTS)
    if isinstance(raw_aspects, dict):
        aspects.update(_sanitize_aspects(raw_aspects))
    return {
        "id": car_id,
        "name": name or "Unnamed Car",
        "type": car_type or "sedan",
        "aspects": aspects,
    }


def _validate_sensor(mac: str, raw: dict[str, Any]) -> dict[str, Any]:
    name = str(raw.get("name") or mac).strip()[:64]
    location = str(raw.get("location") or "").strip()[:64]
    return {"name": name or mac, "location": location}


class SettingsStore:
    """Holds the full app settings: cars, speed source, and sensors."""

    def __init__(self, persist_path: Path | None = None) -> None:
        self._lock = RLock()
        self._persist_path = persist_path

        default_car = _validate_car({"id": _new_car_id(), **DEFAULT_CAR})
        self._cars: list[dict[str, Any]] = [default_car]
        self._active_car_id: str = default_car["id"]
        self._speed_source: str = "gps"
        self._manual_speed_kph: float | None = None
        self._obd2_config: dict[str, Any] = {}
        self._sensors_by_mac: dict[str, dict[str, Any]] = {}

        self._load()

    # -- persistence -----------------------------------------------------------

    def _load(self) -> None:
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            LOGGER.warning("Could not load settings from %s: %s", self._persist_path, exc)
            return
        if not isinstance(raw, dict):
            return

        with self._lock:
            # Cars
            raw_cars = raw.get("cars")
            if isinstance(raw_cars, list) and raw_cars:
                self._cars = [_validate_car(c) for c in raw_cars if isinstance(c, dict)]
            if not self._cars:
                default_car = _validate_car({"id": _new_car_id(), **DEFAULT_CAR})
                self._cars = [default_car]

            active_id = str(raw.get("activeCarId") or "")
            car_ids = {c["id"] for c in self._cars}
            self._active_car_id = active_id if active_id in car_ids else self._cars[0]["id"]

            # Speed source
            src = str(raw.get("speedSource") or "gps")
            self._speed_source = src if src in VALID_SPEED_SOURCES else "gps"
            self._manual_speed_kph = _parse_manual_speed(raw.get("manualSpeedKph"))
            obd2 = raw.get("obd2Config")
            self._obd2_config = obd2 if isinstance(obd2, dict) else {}

            # Sensors
            sensors = raw.get("sensorsByMac")
            if isinstance(sensors, dict):
                self._sensors_by_mac = {
                    str(mac): _validate_sensor(str(mac), v)
                    for mac, v in sensors.items()
                    if isinstance(v, dict)
                }

    def _persist(self) -> None:
        if not self._persist_path:
            return
        payload = self.snapshot()
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._persist_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self._persist_path)

    # -- full snapshot ---------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "cars": [dict(c, aspects=dict(c["aspects"])) for c in self._cars],
                "activeCarId": self._active_car_id,
                "speedSource": self._speed_source,
                "manualSpeedKph": self._manual_speed_kph,
                "obd2Config": dict(self._obd2_config),
                "sensorsByMac": {mac: dict(s) for mac, s in self._sensors_by_mac.items()},
            }

    # -- car operations --------------------------------------------------------

    def get_cars(self) -> dict[str, Any]:
        with self._lock:
            return {
                "cars": [dict(c, aspects=dict(c["aspects"])) for c in self._cars],
                "activeCarId": self._active_car_id,
            }

    def active_car_aspects(self) -> dict[str, float]:
        """Return the active car's aspects as a flat analysis-settings dict."""
        with self._lock:
            car = self._find_car(self._active_car_id)
            return dict(car["aspects"]) if car else dict(DEFAULT_CAR_ASPECTS)

    def _find_car(self, car_id: str) -> dict[str, Any] | None:
        for c in self._cars:
            if c["id"] == car_id:
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
            car = _validate_car(car_data)
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
                    car["name"] = name
            if "type" in car_data:
                car_type = str(car_data["type"]).strip()[:32]
                if car_type:
                    car["type"] = car_type
            if "aspects" in car_data and isinstance(car_data["aspects"], dict):
                car["aspects"].update(_sanitize_aspects(car_data["aspects"]))
            self._persist()
            return self.get_cars()

    def delete_car(self, car_id: str) -> dict[str, Any]:
        with self._lock:
            if len(self._cars) <= 1:
                raise ValueError("Cannot delete the last car")
            car = self._find_car(car_id)
            if car is None:
                raise ValueError(f"Unknown car id: {car_id}")
            self._cars = [c for c in self._cars if c["id"] != car_id]
            if self._active_car_id == car_id:
                self._active_car_id = self._cars[0]["id"]
            self._persist()
            return self.get_cars()

    # -- speed source ----------------------------------------------------------

    def get_speed_source(self) -> dict[str, Any]:
        with self._lock:
            return {
                "speedSource": self._speed_source,
                "manualSpeedKph": self._manual_speed_kph,
                "obd2Config": dict(self._obd2_config),
            }

    def update_speed_source(self, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            src = data.get("speedSource")
            if isinstance(src, str) and src in VALID_SPEED_SOURCES:
                self._speed_source = src
            manual = data.get("manualSpeedKph")
            if manual is None:
                self._manual_speed_kph = None
            else:
                self._manual_speed_kph = _parse_manual_speed(manual)
            obd2 = data.get("obd2Config")
            if isinstance(obd2, dict):
                self._obd2_config = obd2
            self._persist()
            return self.get_speed_source()

    @property
    def speed_source(self) -> str:
        with self._lock:
            return self._speed_source

    @property
    def manual_speed_kph(self) -> float | None:
        with self._lock:
            return self._manual_speed_kph

    # -- sensors ---------------------------------------------------------------

    def get_sensors(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {mac: dict(s) for mac, s in self._sensors_by_mac.items()}

    def set_sensor(self, mac: str, data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            existing = self._sensors_by_mac.get(mac, {"name": mac, "location": ""})
            if "name" in data:
                name = str(data["name"]).strip()[:64]
                existing["name"] = name if name else mac
            if "location" in data:
                existing["location"] = str(data["location"]).strip()[:64]
            self._sensors_by_mac[mac] = existing
            self._persist()
            return {mac: dict(existing)}

    def remove_sensor(self, mac: str) -> bool:
        with self._lock:
            removed = self._sensors_by_mac.pop(mac, None) is not None
            if removed:
                self._persist()
            return removed

    def sensor_name(self, mac: str) -> str:
        """Return the user-set sensor name, or the MAC itself."""
        with self._lock:
            entry = self._sensors_by_mac.get(mac)
            return entry["name"] if entry else mac

    def sensor_location(self, mac: str) -> str:
        """Return the sensor's assigned location code, or empty string."""
        with self._lock:
            entry = self._sensors_by_mac.get(mac)
            return entry["location"] if entry else ""

    def ensure_sensor(self, mac: str) -> None:
        """Create a sensor entry with defaults if it doesn't exist."""
        with self._lock:
            if mac not in self._sensors_by_mac:
                self._sensors_by_mac[mac] = {"name": mac, "location": ""}
