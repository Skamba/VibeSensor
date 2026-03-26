"""Sensor metadata CRUD extracted into an explicit collaborator."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from threading import RLock

from vibesensor.domain import Sensor, SensorPlacement, normalize_sensor_id
from vibesensor.infra.config.car_settings import _clamp_str, _UpdateWithRollback
from vibesensor.infra.config.settings_transaction import log_settings_change
from vibesensor.infra.location_assignment_validator import (
    AssignedLocation,
    LocationAssignmentValidator,
)
from vibesensor.shared.types.sensor_config import (
    SensorConfig,
    SensorConfigUpdatePayload,
    SensorsByMacPayload,
)

LOGGER = logging.getLogger(__name__)
_LOCATION_VALIDATOR = LocationAssignmentValidator()


@dataclass(slots=True)
class SensorSettingsState:
    """Mutable sensor-settings state owned by ``SettingsStore``."""

    sensors: dict[str, SensorConfig] = field(default_factory=dict)


class SensorSettingsService:
    """Explicit sensor CRUD collaborator used by ``SettingsStore``."""

    __slots__ = ("_lock", "_state", "_update_with_rollback")

    def __init__(
        self,
        *,
        lock: RLock,
        state: SensorSettingsState,
        update_with_rollback: _UpdateWithRollback,
    ) -> None:
        self._lock = lock
        self._state = state
        self._update_with_rollback = update_with_rollback

    def sensors_payload_unlocked(self) -> SensorsByMacPayload:
        return {sensor_id: cfg.to_dict() for sensor_id, cfg in self._state.sensors.items()}

    def sensor_configs_snapshot_unlocked(self) -> dict[str, SensorConfig]:
        return {
            sensor_id: SensorConfig.from_dict(sensor_id, cfg.to_dict())
            for sensor_id, cfg in self._state.sensors.items()
        }

    def get_sensors(self) -> SensorsByMacPayload:
        with self._lock:
            return self.sensors_payload_unlocked()

    def sensors(self) -> list[Sensor]:
        with self._lock:
            return [
                Sensor(
                    sensor_id=cfg.sensor_id,
                    name=cfg.name,
                    placement=(
                        SensorPlacement.from_code(cfg.location_code) if cfg.location_code else None
                    ),
                )
                for cfg in self._state.sensors.values()
            ]

    def set_sensor(self, mac: str, data: SensorConfigUpdatePayload) -> SensorsByMacPayload:
        sensor_id = normalize_sensor_id(mac)

        def _apply(_previous: dict[str, SensorConfig]) -> bool:
            existing = self._state.sensors.get(sensor_id)
            if existing is None:
                updated = SensorConfig(sensor_id=sensor_id, name=sensor_id, location_code="")
            else:
                updated = SensorConfig.from_dict(sensor_id, existing.to_dict())
            if "name" in data:
                name = _clamp_str(data["name"], 64)
                updated.name = name or sensor_id
            if "location_code" in data:
                location_code = _clamp_str(data["location_code"], 64)
                _LOCATION_VALIDATOR.validate_assignment(
                    owner_id=sensor_id,
                    location_code=location_code,
                    assigned_locations=(
                        AssignedLocation(
                            owner_id=other_id,
                            owner_name=other.name or other.sensor_id,
                            location_code=other.location_code,
                        )
                        for other_id, other in self._state.sensors.items()
                    ),
                )
                updated.location_code = location_code
            self._state.sensors[sensor_id] = updated
            return True

        return self._update_with_rollback(
            snapshot=self.sensor_configs_snapshot_unlocked,
            apply=_apply,
            restore=lambda previous: setattr(self._state, "sensors", previous),
            audit_log=lambda previous: log_settings_change(
                LOGGER,
                action="set_sensor",
                before=(
                    previous_sensor.to_dict()
                    if (previous_sensor := previous.get(sensor_id)) is not None
                    else None
                ),
                after=self._state.sensors[sensor_id].to_dict(),
                sensor_id=sensor_id,
            ),
            result=lambda: {sensor_id: self._state.sensors[sensor_id].to_dict()},
        )

    def remove_sensor(self, mac: str) -> bool:
        sensor_id = normalize_sensor_id(mac)
        removed = False

        def _apply(_previous: dict[str, SensorConfig]) -> bool:
            nonlocal removed
            removed = self._state.sensors.pop(sensor_id, None) is not None
            return removed

        return self._update_with_rollback(
            snapshot=self.sensor_configs_snapshot_unlocked,
            apply=_apply,
            restore=lambda previous: setattr(self._state, "sensors", previous),
            audit_log=lambda previous: log_settings_change(
                LOGGER,
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
