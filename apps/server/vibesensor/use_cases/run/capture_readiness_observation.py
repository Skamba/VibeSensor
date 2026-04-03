"""Observation gathering for live capture-readiness evaluation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from vibesensor.domain import RunContextSnapshot
from vibesensor.shared.ports import ClientTracker, TrackedClient

__all__ = [
    "CaptureReadinessObservation",
    "ObdStatusSnapshotView",
    "SpeedStatusSnapshotView",
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
class CaptureReadinessObservation:
    observed_at_mono_s: float
    active_clients: tuple[TrackedClient, ...]
    run_context: RunContextSnapshot
    speed_status: SpeedStatusSnapshotView | None
    obd_status: ObdStatusSnapshotView | None


def observe_capture_readiness(
    *,
    registry: ClientTracker,
    run_context: RunContextSnapshot,
    speed_provider: object,
    now_mono: float | None = None,
) -> CaptureReadinessObservation:
    observed_at_mono_s = time.monotonic() if now_mono is None else now_mono
    active_clients = _active_clients(registry)
    return CaptureReadinessObservation(
        observed_at_mono_s=observed_at_mono_s,
        active_clients=active_clients,
        run_context=run_context,
        speed_status=_speed_status(speed_provider),
        obd_status=_obd_status(speed_provider),
    )


def _active_clients(registry: ClientTracker) -> tuple[TrackedClient, ...]:
    active_clients: list[TrackedClient] = []
    for client_id in registry.active_client_ids():
        client = registry.get(client_id)
        if client is not None:
            active_clients.append(client)
    return tuple(active_clients)


def _speed_status(speed_provider: object) -> SpeedStatusSnapshotView | None:
    if isinstance(speed_provider, _SpeedStatusProvider):
        return speed_provider.status_snapshot()
    return None


def _obd_status(speed_provider: object) -> ObdStatusSnapshotView | None:
    if isinstance(speed_provider, _ObdStatusProvider):
        return speed_provider.obd_status()
    return None
