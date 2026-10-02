"""Shared persisted settings-snapshot contracts."""

from __future__ import annotations

from vibesensor.settings.car_config import CarConfigPayload
from vibesensor.settings.sensor_config import SensorsByMacPayload
from vibesensor.settings.settings_types import LanguageCode, SpeedUnitCode
from vibesensor.speed.speed_source_config import SpeedSourcePayload

__all__ = ["SettingsSnapshotPayload"]


class SettingsSnapshotPayload(SpeedSourcePayload):
    cars: list[CarConfigPayload]
    activeCarId: str | None
    language: LanguageCode
    speedUnit: SpeedUnitCode
    sensorsByMac: SensorsByMacPayload
