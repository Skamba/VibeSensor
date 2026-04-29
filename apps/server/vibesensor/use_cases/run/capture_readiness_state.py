"""Rolling state accumulation for live capture-readiness evaluation."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from vibesensor.domain import CaptureReadinessPolicy
from vibesensor.shared.constants.type_checks import NUMERIC_TYPES
from vibesensor.use_cases.run.capture_readiness_observation import (
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
    integrity_quiet_period_s: float
    stable_speed_dwell_s: float


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
        self._last_integrity_issue_mono_s: float | None = None
        self._last_integrity_totals = CaptureReadinessSensorObservation(
            client_id="",
            location_code="",
            frames_dropped=0,
            queue_overflow_drops=0,
            server_queue_drops=0,
            parse_errors=0,
        )

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
        active_ids = {sensor.client_id for sensor in active_sensors}
        for client_id in tuple(self._last_client_counters):
            if client_id not in active_ids:
                self._last_client_counters.pop(client_id, None)

        deltas = CaptureReadinessSensorObservation(
            client_id="",
            location_code="",
            frames_dropped=0,
            queue_overflow_drops=0,
            server_queue_drops=0,
            parse_errors=0,
        )
        for sensor in active_sensors:
            previous = self._last_client_counters.get(sensor.client_id)
            if previous is not None:
                deltas = CaptureReadinessSensorObservation(
                    client_id="",
                    location_code="",
                    frames_dropped=deltas.frames_dropped
                    + max(0, sensor.frames_dropped - previous.frames_dropped),
                    queue_overflow_drops=deltas.queue_overflow_drops
                    + max(0, sensor.queue_overflow_drops - previous.queue_overflow_drops),
                    server_queue_drops=deltas.server_queue_drops
                    + max(0, sensor.server_queue_drops - previous.server_queue_drops),
                    parse_errors=deltas.parse_errors
                    + max(0, sensor.parse_errors - previous.parse_errors),
                )
            self._last_client_counters[sensor.client_id] = sensor

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
            if quiet_elapsed_s < self._config.integrity_quiet_period_s:
                integrity_active = True
                quiet_period_remaining_s = round(
                    max(0.0, self._config.integrity_quiet_period_s - quiet_elapsed_s),
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
