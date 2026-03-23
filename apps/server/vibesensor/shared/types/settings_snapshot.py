"""Shared persisted settings-snapshot contracts."""

from __future__ import annotations

from vibesensor.shared.types.car_config import CarConfigPayload
from vibesensor.shared.types.sensor_config import SensorsByMacPayload
from vibesensor.shared.types.settings_types import LanguageCode, SpeedUnitCode
from vibesensor.shared.types.speed_source_config import SpeedSourcePayload

__all__ = ["SettingsSnapshotPayload"]


class SettingsSnapshotPayload(SpeedSourcePayload):
    cars: list[CarConfigPayload]
    activeCarId: str | None
    language: LanguageCode
    speedUnit: SpeedUnitCode
    sensorsByMac: SensorsByMacPayload
