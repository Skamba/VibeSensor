"""Sensor metadata reads and location assignment extracted into an explicit collaborator."""

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
from vibesensor.shared.locations import label_for_code
from vibesensor.shared.types.sensor_config import (
    SensorConfig,
    SensorsByMacPayload,
)

LOGGER = logging.getLogger(__name__)
_LOCATION_VALIDATOR = LocationAssignmentValidator()


@dataclass(slots=True)
class SensorSettingsState:
    """Mutable sensor-settings state shared by focused persisted settings services."""

    sensors: dict[str, SensorConfig] = field(default_factory=dict)


class SensorSettingsService:
    """Persisted sensor-metadata collaborator backed by the shared snapshot coordinator."""

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

    def assign_sensor_location(self, sensor_id: str, location_code: str) -> SensorsByMacPayload:
        normalized_sensor_id = normalize_sensor_id(sensor_id)
        normalized_location = _LOCATION_VALIDATOR.normalize(location_code)
        if normalized_location:
            label = label_for_code(normalized_location)
            if label is None:
                raise ValueError("Unknown location_code")
            name = label
        else:
            name = normalized_sensor_id

        sensor_id = normalized_sensor_id

        def _apply(_previous: dict[str, SensorConfig]) -> bool:
            existing = self._state.sensors.get(sensor_id)
            if existing is None:
                updated = SensorConfig(sensor_id=sensor_id, name=sensor_id, location_code="")
            else:
                updated = SensorConfig.from_dict(sensor_id, existing.to_dict())
            updated.name = _clamp_str(name, 64) or sensor_id
            _LOCATION_VALIDATOR.validate_assignment(
                owner_id=sensor_id,
                location_code=normalized_location,
                assigned_locations=(
                    AssignedLocation(
                        owner_id=other_id,
                        owner_name=other.name or other.sensor_id,
                        location_code=other.location_code,
                    )
                    for other_id, other in self._state.sensors.items()
                ),
            )
            updated.location_code = normalized_location
            self._state.sensors[sensor_id] = updated
            return True

        return self._update_with_rollback(
            snapshot=self.sensor_configs_snapshot_unlocked,
            apply=_apply,
            restore=lambda previous: setattr(self._state, "sensors", previous),
            audit_log=lambda previous: log_settings_change(
                LOGGER,
                action="assign_sensor_location",
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
