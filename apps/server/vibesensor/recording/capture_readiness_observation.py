"""Boundary observation gathering for live capture-readiness evaluation."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.domain.run_context import RunContextSnapshot
from vibesensor.settings.sensor_config import SensorConfigPayload
from vibesensor.settings.sensor_metadata import resolve_sensor_presentation

if TYPE_CHECKING:
    from vibesensor.ingest.registry import ClientRecord, ClientRegistry
    from vibesensor.settings.sensor_settings import SensorSettingsService
    from vibesensor.speed.source_coordinator import SpeedSourceObservationService

__all__ = [
    "CaptureReadinessObservation",
    "CaptureReadinessObdObservation",
    "CaptureReadinessSensorObservation",
    "CaptureReadinessSpeedObservation",
    "observe_capture_readiness",
]


@dataclass(frozen=True, slots=True)
class CaptureReadinessSensorObservation:
    client_id: str
    location_code: str
    frames_dropped: int
    queue_overflow_drops: int
    server_queue_drops: int
    parse_errors: int


@dataclass(frozen=True, slots=True)
class CaptureReadinessSpeedObservation:
    source: str
    speed_kmh: float | None
    age_s: float | None
    fallback_active: bool


@dataclass(frozen=True, slots=True)
class CaptureReadinessObdObservation:
    rpm: float | None
    rpm_age_s: float | None


@dataclass(frozen=True, slots=True)
class CaptureReadinessObservation:
    observed_at_mono_s: float
    active_sensors: tuple[CaptureReadinessSensorObservation, ...]
    run_context: RunContextSnapshot
    speed: CaptureReadinessSpeedObservation | None
    obd: CaptureReadinessObdObservation | None


def observe_capture_readiness(
    *,
    registry: ClientRegistry,
    run_context: RunContextSnapshot,
    speed_provider: SpeedSourceObservationService,
    sensor_metadata_reader: SensorSettingsService | None = None,
    now_mono: float | None = None,
) -> CaptureReadinessObservation:
    observed_at_mono_s = time.monotonic() if now_mono is None else now_mono
    sensors_by_mac = sensor_metadata_reader.get_sensors() if sensor_metadata_reader else {}
    active_sensors = _active_sensors(registry, sensors_by_mac=sensors_by_mac)
    return CaptureReadinessObservation(
        observed_at_mono_s=observed_at_mono_s,
        active_sensors=active_sensors,
        run_context=run_context,
        speed=_speed_observation(speed_provider),
        obd=_obd_observation(speed_provider),
    )


def _active_sensors(
    registry: ClientRegistry,
    *,
    sensors_by_mac: Mapping[str, SensorConfigPayload],
) -> tuple[CaptureReadinessSensorObservation, ...]:
    active_sensors: list[CaptureReadinessSensorObservation] = []
    for client_id in registry.active_client_ids():
        client = registry.get(client_id)
        if client is not None:
            active_sensors.append(_sensor_observation(client, sensors_by_mac=sensors_by_mac))
    return tuple(active_sensors)


def _sensor_observation(
    client: ClientRecord,
    *,
    sensors_by_mac: Mapping[str, SensorConfigPayload],
) -> CaptureReadinessSensorObservation:
    _, location_code = resolve_sensor_presentation(
        sensor_id=client.client_id,
        sensors_by_mac=sensors_by_mac,
        fallback_name=str(getattr(client, "name", "") or ""),
        fallback_location_code=str(client.location_code),
    )
    return CaptureReadinessSensorObservation(
        client_id=client.client_id,
        location_code=location_code,
        frames_dropped=int(getattr(client, "frames_dropped", 0)),
        queue_overflow_drops=int(getattr(client, "queue_overflow_drops", 0)),
        server_queue_drops=int(getattr(client, "server_queue_drops", 0)),
        parse_errors=int(getattr(client, "parse_errors", 0)),
    )


def _speed_observation(
    speed_provider: SpeedSourceObservationService,
) -> CaptureReadinessSpeedObservation:
    speed_status = speed_provider.status_snapshot()
    return CaptureReadinessSpeedObservation(
        source=str(speed_status.speed_source),
        speed_kmh=speed_status.effective_speed_kmh,
        age_s=speed_status.last_update_age_s,
        fallback_active=speed_status.fallback_active,
    )


def _obd_observation(
    speed_provider: SpeedSourceObservationService,
) -> CaptureReadinessObdObservation:
    obd_status = speed_provider.obd_status()
    return CaptureReadinessObdObservation(
        rpm=obd_status.last_rpm,
        rpm_age_s=obd_status.rpm_sample_age_s,
    )
