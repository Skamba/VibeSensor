"""Boundary decoder for persisted settings snapshot payloads."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import Car, normalize_sensor_id
from vibesensor.shared.types.car_config import CarConfigPayload, car_to_persistence_dict
from vibesensor.shared.types.sensor_config import SensorConfig, SensorsByMacPayload
from vibesensor.shared.types.settings_snapshot import SettingsSnapshotPayload
from vibesensor.shared.types.settings_types import LanguageCode, SpeedUnitCode
from vibesensor.shared.types.speed_source_config import SpeedSourceConfig


def _normalize_choice(value: object, default: str) -> str:
    return str(value or default).strip().lower()


def coerce_language_code(value: object) -> LanguageCode:
    """Normalize a persisted language-like value into a supported language code."""
    language = _normalize_choice(value, "en")
    return "nl" if language.startswith("nl") else "en"


def coerce_speed_unit_code(value: object) -> SpeedUnitCode:
    """Normalize a persisted speed-unit-like value into a supported unit code."""
    unit = _normalize_choice(value, "kmh")
    return "mps" if unit == "mps" else "kmh"


def validated_language_code(value: object) -> LanguageCode | None:
    normalized = _normalize_choice(value, "")
    if normalized == "en":
        return "en"
    if normalized == "nl":
        return "nl"
    return None


def validated_speed_unit_code(value: object) -> SpeedUnitCode | None:
    normalized = _normalize_choice(value, "")
    if normalized == "kmh":
        return "kmh"
    if normalized == "mps":
        return "mps"
    return None


def settings_snapshot_from_payload(payload: Mapping[str, object]) -> SettingsSnapshotPayload:
    """Normalize raw persisted settings JSON into the canonical snapshot payload."""
    raw_cars = payload.get("cars")
    cars: list[CarConfigPayload] = []
    if isinstance(raw_cars, list):
        for car in raw_cars:
            if not isinstance(car, Mapping):
                continue
            car_payload = {str(key): value for key, value in car.items()}
            cars.append(car_to_persistence_dict(Car.from_persisted_dict(car_payload)))

    active_car_id_raw = str(payload.get("activeCarId") or "")
    car_ids = {car["id"] for car in cars}
    active_car_id = active_car_id_raw if active_car_id_raw in car_ids else None

    speed_cfg = SpeedSourceConfig.from_dict(
        {
            "speedSource": payload.get("speedSource"),
            "manualSpeedKph": payload.get("manualSpeedKph"),
            "staleTimeoutS": payload.get("staleTimeoutS"),
        },
    )

    raw_sensors = payload.get("sensorsByMac")
    sensors_by_mac: SensorsByMacPayload = {}
    if isinstance(raw_sensors, Mapping):
        for mac, value in raw_sensors.items():
            if not isinstance(value, Mapping):
                continue
            try:
                sensor_id = normalize_sensor_id(str(mac))
            except ValueError:
                continue
            sensor_payload = {str(key): field_value for key, field_value in value.items()}
            sensors_by_mac[sensor_id] = SensorConfig.from_dict(sensor_id, sensor_payload).to_dict()

    return {
        "cars": cars,
        "activeCarId": active_car_id,
        **speed_cfg.to_dict(),
        "language": coerce_language_code(payload.get("language")),
        "speedUnit": coerce_speed_unit_code(payload.get("speedUnit")),
        "sensorsByMac": sensors_by_mac,
    }
