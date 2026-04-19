"""msgspec-backed boundary codec for persisted settings snapshots."""

from __future__ import annotations

import logging
from collections.abc import Mapping

import msgspec

from vibesensor.domain import SpeedSourceKind, normalize_sensor_id
from vibesensor.shared.types.car_config import (
    CarConfigPayload,
    car_from_persistence_dict,
    car_to_persistence_dict,
)
from vibesensor.shared.types.sensor_config import SensorConfig
from vibesensor.shared.types.settings_snapshot import SettingsSnapshotPayload
from vibesensor.shared.types.settings_types import LanguageCode, SpeedUnitCode
from vibesensor.shared.types.speed_source_config import SpeedSourceConfig

__all__ = [
    "CarConfigRecord",
    "SettingsSnapshotRecord",
    "coerce_language_code",
    "coerce_speed_unit_code",
    "settings_snapshot_from_json",
    "settings_snapshot_from_payload",
    "settings_snapshot_to_json",
    "validated_language_code",
    "validated_speed_unit_code",
]

LOGGER = logging.getLogger(__name__)


class SensorConfigRecord(msgspec.Struct, kw_only=True, frozen=True):
    name: str = ""
    location_code: str = ""


class CarConfigRecord(msgspec.Struct, kw_only=True, frozen=True):
    id: str = ""
    name: str = ""
    type: str = "sedan"
    aspects: dict[str, float] = msgspec.field(default_factory=dict)
    variant: str | None = None


class SettingsSnapshotRecord(msgspec.Struct, kw_only=True, frozen=True):
    cars: list[CarConfigRecord] = msgspec.field(default_factory=list)
    activeCarId: str | None = None
    speedSource: SpeedSourceKind = SpeedSourceKind.GPS
    manualSpeedKph: float | None = None
    staleTimeoutS: float = 10.0
    obdDeviceMac: str | None = None
    obdDeviceName: str | None = None
    language: LanguageCode = "en"
    speedUnit: SpeedUnitCode = "kmh"
    sensorsByMac: dict[str, SensorConfigRecord] = msgspec.field(default_factory=dict)


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


def settings_snapshot_to_json(snapshot: SettingsSnapshotPayload) -> str:
    """Encode the canonical settings snapshot payload as persisted JSON text."""

    return msgspec.json.encode(_settings_snapshot_record_from_payload(snapshot)).decode("utf-8")


def settings_snapshot_from_json(raw: str | bytes | None) -> SettingsSnapshotPayload | None:
    """Decode persisted settings snapshot JSON into the canonical payload shape."""

    if not raw:
        return None
    try:
        record = msgspec.json.decode(raw, type=SettingsSnapshotRecord)
    except msgspec.ValidationError:
        try:
            decoded = msgspec.json.decode(raw)
        except msgspec.DecodeError:
            LOGGER.warning(
                "Skipping invalid JSON payload while reading settings_snapshot",
                exc_info=True,
            )
            return None
        if not isinstance(decoded, Mapping):
            return None
        record = _settings_snapshot_record_from_object(decoded)
    except msgspec.DecodeError:
        LOGGER.warning(
            "Skipping invalid JSON payload while reading settings_snapshot",
            exc_info=True,
        )
        return None
    return _settings_snapshot_payload_from_record(record)


def settings_snapshot_from_payload(payload: Mapping[str, object]) -> SettingsSnapshotPayload:
    """Normalize raw persisted settings JSON into the canonical snapshot payload."""

    return _settings_snapshot_payload_from_record(_settings_snapshot_record_from_object(payload))


def _settings_snapshot_record_from_payload(
    payload: Mapping[str, object],
) -> SettingsSnapshotRecord:
    return _settings_snapshot_record_from_object(payload)


def _settings_snapshot_record_from_object(payload: Mapping[str, object]) -> SettingsSnapshotRecord:
    raw_cars = payload.get("cars")
    cars: list[CarConfigRecord] = []
    if isinstance(raw_cars, list):
        for car in raw_cars:
            if not isinstance(car, Mapping):
                continue
            car_payload = car_to_persistence_dict(
                car_from_persistence_dict({str(key): value for key, value in car.items()}),
            )
            cars.append(
                CarConfigRecord(
                    id=car_payload["id"],
                    name=car_payload["name"],
                    type=car_payload["type"],
                    aspects=dict(car_payload["aspects"]),
                    variant=car_payload.get("variant"),
                )
            )

    active_car_id_raw = str(payload.get("activeCarId") or "")
    car_ids = {car.id for car in cars}
    active_car_id = active_car_id_raw if active_car_id_raw in car_ids else None

    speed_cfg = SpeedSourceConfig.from_dict(
        {
            "speedSource": payload.get("speedSource"),
            "manualSpeedKph": payload.get("manualSpeedKph"),
            "staleTimeoutS": payload.get("staleTimeoutS"),
            "obdDeviceMac": payload.get("obdDeviceMac"),
            "obdDeviceName": payload.get("obdDeviceName"),
        },
    )

    raw_sensors = payload.get("sensorsByMac")
    sensors_by_mac: dict[str, SensorConfigRecord] = {}
    if isinstance(raw_sensors, Mapping):
        for mac, value in raw_sensors.items():
            if not isinstance(value, Mapping):
                continue
            try:
                sensor_id = normalize_sensor_id(str(mac))
            except ValueError:
                continue
            sensor_payload = SensorConfig.from_dict(
                sensor_id,
                {str(key): field_value for key, field_value in value.items()},
            ).to_dict()
            sensors_by_mac[sensor_id] = SensorConfigRecord(
                name=sensor_payload["name"],
                location_code=sensor_payload["location_code"],
            )

    return SettingsSnapshotRecord(
        cars=cars,
        activeCarId=active_car_id,
        speedSource=speed_cfg.speed_source,
        manualSpeedKph=speed_cfg.manual_speed_kph,
        staleTimeoutS=speed_cfg.stale_timeout_s,
        obdDeviceMac=speed_cfg.obd_device_mac,
        obdDeviceName=speed_cfg.obd_device_name,
        language=coerce_language_code(payload.get("language")),
        speedUnit=coerce_speed_unit_code(payload.get("speedUnit")),
        sensorsByMac=sensors_by_mac,
    )


def _settings_snapshot_payload_from_record(
    record: SettingsSnapshotRecord,
) -> SettingsSnapshotPayload:
    cars: list[CarConfigPayload] = []
    for car in record.cars:
        payload: CarConfigPayload = {
            "id": car.id,
            "name": car.name,
            "type": car.type,
            "aspects": dict(car.aspects),
        }
        if car.variant:
            payload["variant"] = car.variant
        cars.append(payload)

    payload: SettingsSnapshotPayload = {
        "cars": cars,
        "activeCarId": record.activeCarId,
        "speedSource": record.speedSource,
        "manualSpeedKph": record.manualSpeedKph,
        "staleTimeoutS": record.staleTimeoutS,
        "language": record.language,
        "speedUnit": record.speedUnit,
        "sensorsByMac": {
            sensor_id: {"name": config.name, "location_code": config.location_code}
            for sensor_id, config in record.sensorsByMac.items()
        },
    }
    if record.obdDeviceMac is not None:
        payload["obdDeviceMac"] = record.obdDeviceMac
    if record.obdDeviceName is not None:
        payload["obdDeviceName"] = record.obdDeviceName
    return payload
