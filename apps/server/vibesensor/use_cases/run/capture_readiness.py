"""Stateful tracking wrapper around capture-readiness observation and policy."""

from __future__ import annotations

import math
from collections import deque

from vibesensor.domain import CaptureReadiness, CaptureReadinessPolicy
from vibesensor.shared.ports import TrackedClient
from vibesensor.use_cases.run.capture_readiness_observation import CaptureReadinessObservation
from vibesensor.use_cases.run.capture_readiness_policy import (
    ClientCounterSnapshot,
    IntegrityState,
    SpeedObservation,
    evaluate_capture_readiness,
    speed_history_sample,
)

__all__ = ["CaptureReadinessTracker"]


class CaptureReadinessTracker:
    """Keep only the rolling state required by readiness dwell/integrity windows."""

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

    def evaluate(self, observation: CaptureReadinessObservation) -> CaptureReadiness:
        integrity = self._update_integrity_window(
            active_clients=observation.active_clients,
            now_mono=observation.observed_at_mono_s,
        )
        speed_history = self._refresh_speed_history(observation)
        return evaluate_capture_readiness(
            policy=self._policy,
            observation=observation,
            integrity=integrity,
            speed_history=speed_history,
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
        speed_kmh = speed_history_sample(
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
