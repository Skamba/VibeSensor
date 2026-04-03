"""Boundary observation gathering for live capture-readiness evaluation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from vibesensor.domain import RunContextSnapshot
from vibesensor.shared.ports import ClientTracker, TrackedClient

__all__ = [
    "CaptureReadinessObservation",
    "CaptureReadinessObdObservation",
    "CaptureReadinessSensorObservation",
    "CaptureReadinessSpeedObservation",
    "observe_capture_readiness",
]


class SpeedStatusSnapshotView(Protocol):
    @property
    def last_update_age_s(self) -> float | None: ...

    @property
    def effective_speed_kmh(self) -> float | None: ...

    @property
    def fallback_active(self) -> bool: ...

    @property
    def speed_source(self) -> str: ...


class ObdStatusSnapshotView(Protocol):
    @property
    def last_rpm(self) -> float | None: ...

    @property
    def rpm_sample_age_s(self) -> float | None: ...


@runtime_checkable
class _SpeedStatusProvider(Protocol):
    def status_snapshot(self) -> SpeedStatusSnapshotView: ...


@runtime_checkable
class _ObdStatusProvider(Protocol):
    def obd_status(self) -> ObdStatusSnapshotView: ...


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
    registry: ClientTracker,
    run_context: RunContextSnapshot,
    speed_provider: object,
    now_mono: float | None = None,
) -> CaptureReadinessObservation:
    observed_at_mono_s = time.monotonic() if now_mono is None else now_mono
    active_sensors = _active_sensors(registry)
    return CaptureReadinessObservation(
        observed_at_mono_s=observed_at_mono_s,
        active_sensors=active_sensors,
        run_context=run_context,
        speed=_speed_observation(speed_provider),
        obd=_obd_observation(speed_provider),
    )


def _active_sensors(registry: ClientTracker) -> tuple[CaptureReadinessSensorObservation, ...]:
    active_sensors: list[CaptureReadinessSensorObservation] = []
    for client_id in registry.active_client_ids():
        client = registry.get(client_id)
        if client is not None:
            active_sensors.append(_sensor_observation(client))
    return tuple(active_sensors)


def _sensor_observation(client: TrackedClient) -> CaptureReadinessSensorObservation:
    return CaptureReadinessSensorObservation(
        client_id=client.client_id,
        location_code=str(client.location_code),
        frames_dropped=int(getattr(client, "frames_dropped", 0)),
        queue_overflow_drops=int(getattr(client, "queue_overflow_drops", 0)),
        server_queue_drops=int(getattr(client, "server_queue_drops", 0)),
        parse_errors=int(getattr(client, "parse_errors", 0)),
    )


def _speed_observation(speed_provider: object) -> CaptureReadinessSpeedObservation | None:
    if isinstance(speed_provider, _SpeedStatusProvider):
        speed_status = speed_provider.status_snapshot()
        return CaptureReadinessSpeedObservation(
            source=str(speed_status.speed_source),
            speed_kmh=speed_status.effective_speed_kmh,
            age_s=speed_status.last_update_age_s,
            fallback_active=speed_status.fallback_active,
        )
    return None


def _obd_observation(speed_provider: object) -> CaptureReadinessObdObservation | None:
    if isinstance(speed_provider, _ObdStatusProvider):
        obd_status = speed_provider.obd_status()
        return CaptureReadinessObdObservation(
            rpm=obd_status.last_rpm,
            rpm_age_s=obd_status.rpm_sample_age_s,
        )
    return None
