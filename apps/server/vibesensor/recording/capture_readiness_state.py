"""Rolling state accumulation for live capture-readiness evaluation."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from vibesensor.common.type_checks import NUMERIC_TYPES
from vibesensor.domain.capture_readiness import CaptureReadinessPolicy
from vibesensor.recording.capture_readiness_observation import (
    CaptureReadinessObservation,
    CaptureReadinessSensorObservation,
)

__all__ = [
    "build_capture_readiness_state_input",
    "CaptureReadinessState",
    "CaptureReadinessStateConfig",
    "CaptureReadinessStateInput",
    "CaptureReadinessStateSnapshot",
    "IntegrityState",
    "SpeedObservation",
]


@dataclass(frozen=True, slots=True)
class SpeedObservation:
    observed_at_mono_s: float
    speed_kmh: float


@dataclass(frozen=True, slots=True)
class CaptureReadinessStateConfig:
    integrity_window_s: float
    stable_speed_dwell_s: float


@dataclass(frozen=True, slots=True)
class IntegrityState:
    """The live sensors' frame counts over the last integrity window."""

    frames_received: int = 0
    frames_dropped: int = 0
    queue_overflow_drops: int = 0
    server_queue_drops: int = 0
    parse_errors: int = 0

    @property
    def any_events(self) -> bool:
        return any(
            (
                self.frames_dropped,
                self.queue_overflow_drops,
                self.server_queue_drops,
                self.parse_errors,
            )
        )

    @property
    def loss_ratio(self) -> float:
        """Share of the window's frames lost.

        Sequence gaps count every frame that never arrived, whatever dropped it
        (the sensor's full send queue, the server's ingest queue, a datagram
        that did not parse), so they alone measure the loss.
        """
        expected = self.frames_received + self.frames_dropped
        return self.frames_dropped / expected if expected > 0 else 0.0


@dataclass(frozen=True, slots=True)
class CaptureReadinessStateSnapshot:
    integrity: IntegrityState
    speed_history: tuple[SpeedObservation, ...]


@dataclass(frozen=True, slots=True)
class CaptureReadinessStateInput:
    observed_at_mono_s: float
    active_sensors: tuple[CaptureReadinessSensorObservation, ...]
    speed_sample_kmh: float | None


def build_capture_readiness_state_input(
    *,
    policy: CaptureReadinessPolicy,
    observation: CaptureReadinessObservation,
) -> CaptureReadinessStateInput:
    """Project one observation into the canonical rolling-state input shape."""

    return CaptureReadinessStateInput(
        observed_at_mono_s=observation.observed_at_mono_s,
        active_sensors=observation.active_sensors,
        speed_sample_kmh=_state_speed_sample_kmh(policy=policy, observation=observation),
    )


def _state_speed_sample_kmh(
    *,
    policy: CaptureReadinessPolicy,
    observation: CaptureReadinessObservation,
) -> float | None:
    speed = observation.speed
    if speed is None:
        return None
    if (
        speed.source not in policy.live_speed_sources
        or speed.fallback_active
        or speed.age_s is None
        or speed.age_s > policy.max_speed_age_s
        or not _is_finite_number(speed.speed_kmh)
        or speed.speed_kmh is None
        or speed.speed_kmh < policy.min_ready_speed_kmh
    ):
        return None
    return float(speed.speed_kmh)


class CaptureReadinessState:
    """Keep only the rolling state needed to interpret readiness."""

    def __init__(self, *, config: CaptureReadinessStateConfig) -> None:
        self._config = config
        self._speed_history: deque[SpeedObservation] = deque()
        self._last_client_counters: dict[str, CaptureReadinessSensorObservation] = {}
        self._integrity_events: deque[tuple[float, IntegrityState]] = deque()

    def observe(self, state_input: CaptureReadinessStateInput) -> CaptureReadinessStateSnapshot:
        return CaptureReadinessStateSnapshot(
            integrity=self._update_integrity_window(
                active_sensors=state_input.active_sensors,
                now_mono=state_input.observed_at_mono_s,
            ),
            speed_history=self._refresh_speed_history(state_input),
        )

    def _update_integrity_window(
        self,
        *,
        active_sensors: tuple[CaptureReadinessSensorObservation, ...],
        now_mono: float,
    ) -> IntegrityState:
        """Sum the live sensors' counter increments over the last integrity window."""
        active_ids = {sensor.client_id for sensor in active_sensors}
        for client_id in tuple(self._last_client_counters):
            if client_id not in active_ids:
                self._last_client_counters.pop(client_id, None)

        delta = IntegrityState()
        for sensor in active_sensors:
            previous = self._last_client_counters.get(sensor.client_id)
            if previous is not None:
                delta = IntegrityState(
                    frames_received=delta.frames_received
                    + max(0, sensor.frames_received - previous.frames_received),
                    frames_dropped=delta.frames_dropped
                    + max(0, sensor.frames_dropped - previous.frames_dropped),
                    queue_overflow_drops=delta.queue_overflow_drops
                    + max(0, sensor.queue_overflow_drops - previous.queue_overflow_drops),
                    server_queue_drops=delta.server_queue_drops
                    + max(0, sensor.server_queue_drops - previous.server_queue_drops),
                    parse_errors=delta.parse_errors
                    + max(0, sensor.parse_errors - previous.parse_errors),
                )
            self._last_client_counters[sensor.client_id] = sensor

        events = self._integrity_events
        events.append((now_mono, delta))
        while events and now_mono - events[0][0] >= self._config.integrity_window_s:
            events.popleft()
        return IntegrityState(
            frames_received=sum(event.frames_received for _, event in events),
            frames_dropped=sum(event.frames_dropped for _, event in events),
            queue_overflow_drops=sum(event.queue_overflow_drops for _, event in events),
            server_queue_drops=sum(event.server_queue_drops for _, event in events),
            parse_errors=sum(event.parse_errors for _, event in events),
        )

    def _refresh_speed_history(
        self,
        state_input: CaptureReadinessStateInput,
    ) -> tuple[SpeedObservation, ...]:
        speed_kmh = state_input.speed_sample_kmh
        if speed_kmh is None:
            self._speed_history.clear()
            return ()

        now_mono = state_input.observed_at_mono_s
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
            now_mono - self._speed_history[0].observed_at_mono_s > self._config.stable_speed_dwell_s
        ):
            self._speed_history.popleft()
        return tuple(self._speed_history)


def _is_finite_number(value: object) -> bool:
    return isinstance(value, NUMERIC_TYPES) and not isinstance(value, bool) and math.isfinite(value)
