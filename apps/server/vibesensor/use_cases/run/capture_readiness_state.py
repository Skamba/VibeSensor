"""Rolling state accumulation for live capture-readiness evaluation."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from vibesensor.domain import CaptureReadinessPolicy
from vibesensor.shared.constants.type_checks import NUMERIC_TYPES
from vibesensor.shared.ports import TrackedClient
from vibesensor.use_cases.run.capture_readiness_observation import (
    CaptureReadinessObservation,
    SpeedStatusSnapshotView,
)

__all__ = [
    "CaptureReadinessState",
    "CaptureReadinessStateSnapshot",
    "ClientCounterSnapshot",
    "IntegrityState",
    "SpeedObservation",
]


@dataclass(frozen=True, slots=True)
class SpeedObservation:
    observed_at_mono_s: float
    speed_kmh: float


@dataclass(frozen=True, slots=True)
class ClientCounterSnapshot:
    frames_dropped: int
    queue_overflow_drops: int
    server_queue_drops: int
    parse_errors: int


@dataclass(frozen=True, slots=True)
class IntegrityState:
    active: bool
    frames_dropped: int
    queue_overflow_drops: int
    server_queue_drops: int
    parse_errors: int
    quiet_period_remaining_s: float | None


@dataclass(frozen=True, slots=True)
class CaptureReadinessStateSnapshot:
    integrity: IntegrityState
    speed_history: tuple[SpeedObservation, ...]


class CaptureReadinessState:
    """Keep only the rolling state needed to interpret readiness."""

    def __init__(self, *, policy: CaptureReadinessPolicy | None = None) -> None:
        self._policy = policy or CaptureReadinessPolicy()
        self._speed_history: deque[SpeedObservation] = deque()
        self._last_client_counters: dict[str, ClientCounterSnapshot] = {}
        self._last_integrity_issue_mono_s: float | None = None
        self._last_integrity_totals = ClientCounterSnapshot(
            frames_dropped=0,
            queue_overflow_drops=0,
            server_queue_drops=0,
            parse_errors=0,
        )

    def observe(
        self,
        observation: CaptureReadinessObservation,
    ) -> CaptureReadinessStateSnapshot:
        return CaptureReadinessStateSnapshot(
            integrity=self._update_integrity_window(
                active_clients=observation.active_clients,
                now_mono=observation.observed_at_mono_s,
            ),
            speed_history=self._refresh_speed_history(observation),
        )

    def _update_integrity_window(
        self,
        *,
        active_clients: tuple[TrackedClient, ...],
        now_mono: float,
    ) -> IntegrityState:
        active_ids = {client.client_id for client in active_clients}
        for client_id in tuple(self._last_client_counters):
            if client_id not in active_ids:
                self._last_client_counters.pop(client_id, None)

        deltas = ClientCounterSnapshot(
            frames_dropped=0,
            queue_overflow_drops=0,
            server_queue_drops=0,
            parse_errors=0,
        )
        for client in active_clients:
            current = _client_counter_snapshot(client)
            previous = self._last_client_counters.get(client.client_id)
            if previous is not None:
                deltas = ClientCounterSnapshot(
                    frames_dropped=deltas.frames_dropped
                    + max(0, current.frames_dropped - previous.frames_dropped),
                    queue_overflow_drops=deltas.queue_overflow_drops
                    + max(0, current.queue_overflow_drops - previous.queue_overflow_drops),
                    server_queue_drops=deltas.server_queue_drops
                    + max(0, current.server_queue_drops - previous.server_queue_drops),
                    parse_errors=deltas.parse_errors
                    + max(0, current.parse_errors - previous.parse_errors),
                )
            self._last_client_counters[client.client_id] = current

        if any(
            (
                deltas.frames_dropped,
                deltas.queue_overflow_drops,
                deltas.server_queue_drops,
                deltas.parse_errors,
            )
        ):
            self._last_integrity_issue_mono_s = now_mono
            self._last_integrity_totals = deltas

        quiet_period_remaining_s: float | None = None
        integrity_active = False
        if self._last_integrity_issue_mono_s is not None:
            quiet_elapsed_s = now_mono - self._last_integrity_issue_mono_s
            if quiet_elapsed_s < self._policy.integrity_quiet_period_s:
                integrity_active = True
                quiet_period_remaining_s = round(
                    max(0.0, self._policy.integrity_quiet_period_s - quiet_elapsed_s),
                    1,
                )

        return IntegrityState(
            active=integrity_active,
            frames_dropped=self._last_integrity_totals.frames_dropped,
            queue_overflow_drops=self._last_integrity_totals.queue_overflow_drops,
            server_queue_drops=self._last_integrity_totals.server_queue_drops,
            parse_errors=self._last_integrity_totals.parse_errors,
            quiet_period_remaining_s=quiet_period_remaining_s,
        )

    def _refresh_speed_history(
        self,
        observation: CaptureReadinessObservation,
    ) -> tuple[SpeedObservation, ...]:
        speed_kmh = _speed_history_sample(
            policy=self._policy,
            speed_status=observation.speed_status,
        )
        if speed_kmh is None:
            self._speed_history.clear()
            return ()

        now_mono = observation.observed_at_mono_s
        if self._speed_history and math.isclose(
            self._speed_history[-1].observed_at_mono_s,
            now_mono,
            abs_tol=0.001,
        ):
            self._speed_history[-1] = SpeedObservation(
                observed_at_mono_s=now_mono,
                speed_kmh=speed_kmh,
            )
        else:
            self._speed_history.append(
                SpeedObservation(
                    observed_at_mono_s=now_mono,
                    speed_kmh=speed_kmh,
                )
            )
        while self._speed_history and (
            now_mono - self._speed_history[0].observed_at_mono_s > self._policy.stable_speed_dwell_s
        ):
            self._speed_history.popleft()
        return tuple(self._speed_history)


def _client_counter_snapshot(client: TrackedClient) -> ClientCounterSnapshot:
    return ClientCounterSnapshot(
        frames_dropped=int(getattr(client, "frames_dropped", 0)),
        queue_overflow_drops=int(getattr(client, "queue_overflow_drops", 0)),
        server_queue_drops=int(getattr(client, "server_queue_drops", 0)),
        parse_errors=int(getattr(client, "parse_errors", 0)),
    )


def _speed_history_sample(
    *,
    policy: CaptureReadinessPolicy,
    speed_status: SpeedStatusSnapshotView | None,
) -> float | None:
    if speed_status is None:
        return None
    speed_source = str(speed_status.speed_source)
    speed_kmh = speed_status.effective_speed_kmh
    if (
        speed_source not in policy.live_speed_sources
        or speed_status.fallback_active
        or speed_status.last_update_age_s is None
        or speed_status.last_update_age_s > policy.max_speed_age_s
        or not _is_finite_number(speed_kmh)
        or speed_kmh is None
        or speed_kmh < policy.min_ready_speed_kmh
    ):
        return None
    return float(speed_kmh)


def _is_finite_number(value: object) -> bool:
    return isinstance(value, NUMERIC_TYPES) and not isinstance(value, bool) and math.isfinite(value)
