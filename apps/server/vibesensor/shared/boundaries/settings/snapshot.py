"""msgspec-backed boundary codec for persisted settings snapshots."""

from __future__ import annotations

import logging

import msgspec

from vibesensor.domain import SpeedSourceKind
from vibesensor.shared.types.car_config import CarConfigPayload
from vibesensor.shared.types.settings_snapshot import SettingsSnapshotPayload
from vibesensor.shared.types.settings_types import (
    LanguageCode,
    SpeedUnitCode,
    analysis_settings_payload_from_mapping,
)

__all__ = [
    "CarConfigRecord",
    "SettingsSnapshotRecord",
    "settings_snapshot_from_json",
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

    record = msgspec.convert(snapshot, type=SettingsSnapshotRecord, strict=True)
    return msgspec.json.encode(record).decode("utf-8")


def settings_snapshot_from_json(raw: str | bytes | None) -> SettingsSnapshotPayload | None:
    """Decode persisted settings snapshot JSON into the canonical payload shape."""

    if not raw:
        return None
    try:
        record = msgspec.json.decode(raw, type=SettingsSnapshotRecord)
    except (msgspec.DecodeError, msgspec.ValidationError):
        LOGGER.warning(
            "Skipping invalid JSON payload while reading settings_snapshot",
            exc_info=True,
        )
        return None
    return _settings_snapshot_payload_from_record(record)


def _settings_snapshot_payload_from_record(
    record: SettingsSnapshotRecord,
) -> SettingsSnapshotPayload:
    cars: list[CarConfigPayload] = []
    for car in record.cars:
        car_payload: CarConfigPayload = {
            "id": car.id,
            "name": car.name,
            "type": car.type,
            "aspects": analysis_settings_payload_from_mapping(car.aspects),
        }
        if car.variant:
            car_payload["variant"] = car.variant
        cars.append(car_payload)

    snapshot_payload: SettingsSnapshotPayload = {
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
        snapshot_payload["obdDeviceMac"] = record.obdDeviceMac
    if record.obdDeviceName is not None:
        snapshot_payload["obdDeviceName"] = record.obdDeviceName
    return snapshot_payload
