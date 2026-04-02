"""Stateful pre-record capture readiness evaluation."""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from vibesensor.domain import CaptureReadiness, CaptureReadinessCheck, RunContextSnapshot
from vibesensor.shared.constants.analysis import STEADY_SPEED_RANGE_KMH, STEADY_SPEED_STDDEV_KMH
from vibesensor.shared.constants.type_checks import NUMERIC_TYPES
from vibesensor.shared.order_reference_settings import order_reference_spec_from_snapshot
from vibesensor.shared.ports import ClientTracker, TrackedClient

_MIN_READY_SPEED_KMH = 20.0
_MAX_SPEED_AGE_S = 2.0
_MAX_OBD_RPM_AGE_S = 1.0
_STABLE_SPEED_DWELL_S = 8.0
_INTEGRITY_QUIET_PERIOD_S = 10.0
_LOW_SENSOR_COUNT_WARN_THRESHOLD = 3
_LIVE_SPEED_SOURCES = {"gps", "obd2"}

type CaptureReadinessCheckTuple = tuple[CaptureReadinessCheck, ...]


class _SpeedStatusSnapshotView(Protocol):
    @property
    def last_update_age_s(self) -> float | None: ...

    @property
    def effective_speed_kmh(self) -> float | None: ...

    @property
    def fallback_active(self) -> bool: ...

    @property
    def speed_source(self) -> str: ...


class _ObdStatusSnapshotView(Protocol):
    @property
    def last_rpm(self) -> float | None: ...

    @property
    def rpm_sample_age_s(self) -> float | None: ...


@runtime_checkable
class _SpeedStatusProvider(Protocol):
    def status_snapshot(self) -> _SpeedStatusSnapshotView: ...


@runtime_checkable
class _ObdStatusProvider(Protocol):
    def obd_status(self) -> _ObdStatusSnapshotView: ...


@dataclass(slots=True)
class _SpeedObservation:
    observed_at_mono_s: float
    speed_kmh: float


@dataclass(slots=True)
class _ClientCounterSnapshot:
    frames_dropped: int
    queue_overflow_drops: int
    server_queue_drops: int
    parse_errors: int


@dataclass(slots=True)
class _IntegrityState:
    active: bool
    frames_dropped: int
    queue_overflow_drops: int
    server_queue_drops: int
    parse_errors: int
    quiet_period_remaining_s: float | None


class CaptureReadinessTracker:
    """Keeps short-lived runtime state for readiness dwell and integrity windows."""

    def __init__(self) -> None:
        self._speed_history: deque[_SpeedObservation] = deque()
        self._last_client_counters: dict[str, _ClientCounterSnapshot] = {}
        self._last_integrity_issue_mono_s: float | None = None
        self._last_integrity_totals = _ClientCounterSnapshot(
            frames_dropped=0,
            queue_overflow_drops=0,
            server_queue_drops=0,
            parse_errors=0,
        )

    def evaluate(
        self,
        *,
        registry: ClientTracker,
        run_context: RunContextSnapshot,
        speed_provider: object,
        now_mono: float | None = None,
    ) -> CaptureReadiness:
        now = time.monotonic() if now_mono is None else now_mono
        active_clients = self._active_clients(registry)
        speed_status = self._speed_status(speed_provider)
        obd_status = self._obd_status(speed_provider)
        integrity = self._update_integrity_window(active_clients, now)

        checks: CaptureReadinessCheckTuple = (
            self._sensors_check(active_clients, integrity),
            self._reference_check(run_context, speed_status, obd_status),
            self._speed_check(speed_status, now),
        )
        is_ready = not any(check.failed for check in checks)
        overall_check = self._overall_check(checks, is_ready)
        return CaptureReadiness(
            is_ready=is_ready,
            checks=(*checks, overall_check),
        )

    def _active_clients(self, registry: ClientTracker) -> tuple[TrackedClient, ...]:
        active_clients: list[TrackedClient] = []
        for client_id in registry.active_client_ids():
            client = registry.get(client_id)
            if client is not None:
                active_clients.append(client)
        return tuple(active_clients)

    def _update_integrity_window(
        self,
        active_clients: tuple[TrackedClient, ...],
        now_mono: float,
    ) -> _IntegrityState:
        active_ids = {client.client_id for client in active_clients}
        for client_id in tuple(self._last_client_counters):
            if client_id not in active_ids:
                self._last_client_counters.pop(client_id, None)

        deltas = _ClientCounterSnapshot(
            frames_dropped=0,
            queue_overflow_drops=0,
            server_queue_drops=0,
            parse_errors=0,
        )
        for client in active_clients:
            current = _client_counter_snapshot(client)
            previous = self._last_client_counters.get(client.client_id)
            if previous is not None:
                deltas.frames_dropped += max(0, current.frames_dropped - previous.frames_dropped)
                deltas.queue_overflow_drops += max(
                    0,
                    current.queue_overflow_drops - previous.queue_overflow_drops,
                )
                deltas.server_queue_drops += max(
                    0,
                    current.server_queue_drops - previous.server_queue_drops,
                )
                deltas.parse_errors += max(0, current.parse_errors - previous.parse_errors)
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
            if quiet_elapsed_s < _INTEGRITY_QUIET_PERIOD_S:
                integrity_active = True
                quiet_period_remaining_s = round(
                    max(0.0, _INTEGRITY_QUIET_PERIOD_S - quiet_elapsed_s),
                    1,
                )

        return _IntegrityState(
            active=integrity_active,
            frames_dropped=self._last_integrity_totals.frames_dropped,
            queue_overflow_drops=self._last_integrity_totals.queue_overflow_drops,
            server_queue_drops=self._last_integrity_totals.server_queue_drops,
            parse_errors=self._last_integrity_totals.parse_errors,
            quiet_period_remaining_s=quiet_period_remaining_s,
        )

    def _sensors_check(
        self,
        active_clients: tuple[TrackedClient, ...],
        integrity: _IntegrityState,
    ) -> CaptureReadinessCheck:
        live_sensor_count = len(active_clients)
        if live_sensor_count == 0:
            return CaptureReadinessCheck(
                check_key="sensors_ready",
                state="fail",
                reason_key="no_live_sensors",
                details=(("live_sensor_count", 0),),
            )

        unassigned_count = sum(1 for client in active_clients if not client.location_code.strip())
        if unassigned_count > 0:
            return CaptureReadinessCheck(
                check_key="sensors_ready",
                state="fail",
                reason_key="sensor_locations_missing",
                details=(
                    ("live_sensor_count", live_sensor_count),
                    ("unassigned_sensor_count", unassigned_count),
                ),
            )

        if integrity.active:
            details: list[tuple[str, int | float | str]] = [
                ("live_sensor_count", live_sensor_count),
            ]
            for key, value in (
                ("frames_dropped", integrity.frames_dropped),
                ("queue_overflow_drops", integrity.queue_overflow_drops),
                ("server_queue_drops", integrity.server_queue_drops),
                ("parse_errors", integrity.parse_errors),
            ):
                if value > 0:
                    details.append((key, value))
            if integrity.quiet_period_remaining_s is not None:
                details.append(
                    ("quiet_period_remaining_s", integrity.quiet_period_remaining_s),
                )
            return CaptureReadinessCheck(
                check_key="sensors_ready",
                state="fail",
                reason_key="recent_integrity_events",
                details=tuple(details),
            )

        if live_sensor_count < _LOW_SENSOR_COUNT_WARN_THRESHOLD:
            return CaptureReadinessCheck(
                check_key="sensors_ready",
                state="warn",
                reason_key="limited_sensor_coverage",
                details=(("live_sensor_count", live_sensor_count),),
            )

        return CaptureReadinessCheck(
            check_key="sensors_ready",
            state="pass",
            reason_key="sensors_ready",
            details=(("live_sensor_count", live_sensor_count),),
        )

    def _reference_check(
        self,
        run_context: RunContextSnapshot,
        speed_status: _SpeedStatusSnapshotView | None,
        obd_status: _ObdStatusSnapshotView | None,
    ) -> CaptureReadinessCheck:
        if not run_context.has_car_context:
            return CaptureReadinessCheck(
                check_key="reference_ready",
                state="fail",
                reason_key="active_car_missing",
            )

        order_reference = order_reference_spec_from_snapshot(run_context.analysis_settings)
        if order_reference is None or not order_reference.is_complete:
            return CaptureReadinessCheck(
                check_key="reference_ready",
                state="fail",
                reason_key="order_reference_incomplete",
            )

        if speed_status is None:
            return CaptureReadinessCheck(
                check_key="reference_ready",
                state="fail",
                reason_key="speed_source_missing",
            )

        speed_source = str(speed_status.speed_source)
        if speed_source not in _LIVE_SPEED_SOURCES:
            return CaptureReadinessCheck(
                check_key="reference_ready",
                state="fail",
                reason_key="speed_source_not_live",
                details=(("speed_source", speed_source),),
            )

        if speed_status.fallback_active:
            return CaptureReadinessCheck(
                check_key="reference_ready",
                state="fail",
                reason_key="speed_source_fallback_active",
                details=(("speed_source", speed_source),),
            )

        last_update_age_s = speed_status.last_update_age_s
        if last_update_age_s is None or last_update_age_s > _MAX_SPEED_AGE_S:
            return CaptureReadinessCheck(
                check_key="reference_ready",
                state="fail",
                reason_key="speed_sample_stale",
                details=(
                    ("speed_source", speed_source),
                    ("last_update_age_s", round(last_update_age_s or 0.0, 2)),
                ),
            )

        effective_speed_kmh = speed_status.effective_speed_kmh
        if (
            not _is_finite_number(effective_speed_kmh)
            or effective_speed_kmh is None
            or effective_speed_kmh <= 0.0
        ):
            return CaptureReadinessCheck(
                check_key="reference_ready",
                state="fail",
                reason_key="speed_sample_missing",
                details=(("speed_source", speed_source),),
            )

        if speed_source == "obd2":
            if order_reference is None or not order_reference.supports_engine_reference:
                return CaptureReadinessCheck(
                    check_key="reference_ready",
                    state="fail",
                    reason_key="order_reference_incomplete",
                    details=(("speed_source", speed_source),),
                )
            if obd_status is None or not _is_finite_number(obd_status.last_rpm):
                return CaptureReadinessCheck(
                    check_key="reference_ready",
                    state="fail",
                    reason_key="obd_rpm_missing",
                    details=(("speed_source", speed_source),),
                )
            rpm_age_s = obd_status.rpm_sample_age_s
            if rpm_age_s is None or rpm_age_s > _MAX_OBD_RPM_AGE_S:
                return CaptureReadinessCheck(
                    check_key="reference_ready",
                    state="fail",
                    reason_key="obd_rpm_stale",
                    details=(
                        ("speed_source", speed_source),
                        ("rpm_sample_age_s", round(rpm_age_s or 0.0, 2)),
                    ),
                )

        return CaptureReadinessCheck(
            check_key="reference_ready",
            state="pass",
            reason_key="reference_ready",
            details=(
                ("speed_source", speed_source),
                ("speed_kmh", round(speed_status.effective_speed_kmh or 0.0, 2)),
                ("last_update_age_s", round(last_update_age_s or 0.0, 2)),
            ),
        )

    def _speed_check(
        self,
        speed_status: _SpeedStatusSnapshotView | None,
        now_mono: float,
    ) -> CaptureReadinessCheck:
        if speed_status is None:
            self._speed_history.clear()
            return CaptureReadinessCheck(
                check_key="speed_stable",
                state="fail",
                reason_key="speed_sample_missing",
            )

        speed_source = str(speed_status.speed_source)
        speed_kmh = speed_status.effective_speed_kmh
        if (
            speed_source not in _LIVE_SPEED_SOURCES
            or speed_status.fallback_active
            or speed_status.last_update_age_s is None
            or speed_status.last_update_age_s > _MAX_SPEED_AGE_S
            or not _is_finite_number(speed_kmh)
        ):
            self._speed_history.clear()
            return CaptureReadinessCheck(
                check_key="speed_stable",
                state="fail",
                reason_key="speed_sample_missing",
                details=(("speed_source", speed_source),),
            )

        assert speed_kmh is not None
        if speed_kmh < _MIN_READY_SPEED_KMH:
            self._speed_history.clear()
            return CaptureReadinessCheck(
                check_key="speed_stable",
                state="fail",
                reason_key="speed_too_low",
                details=(
                    ("speed_kmh", round(speed_kmh, 2)),
                    ("minimum_speed_kmh", _MIN_READY_SPEED_KMH),
                ),
            )

        history = self._refresh_speed_history(now_mono, speed_kmh)
        if len(history) < 2:
            return CaptureReadinessCheck(
                check_key="speed_stable",
                state="fail",
                reason_key="speed_stabilizing",
                details=(
                    ("speed_kmh", round(speed_kmh, 2)),
                    ("dwell_remaining_s", _STABLE_SPEED_DWELL_S),
                ),
            )

        dwell_observed_s = max(0.0, now_mono - history[0].observed_at_mono_s)
        dwell_remaining_s = max(0.0, _STABLE_SPEED_DWELL_S - dwell_observed_s)
        mean_speed_kmh = sum(observed.speed_kmh for observed in history) / len(history)
        range_kmh = max(observed.speed_kmh for observed in history) - min(
            observed.speed_kmh for observed in history
        )
        stddev_kmh = _stddev(tuple(observed.speed_kmh for observed in history))

        if dwell_observed_s < _STABLE_SPEED_DWELL_S:
            return CaptureReadinessCheck(
                check_key="speed_stable",
                state="fail",
                reason_key="speed_stabilizing",
                details=(
                    ("speed_kmh", round(speed_kmh, 2)),
                    ("dwell_remaining_s", round(dwell_remaining_s, 1)),
                ),
            )

        if range_kmh > STEADY_SPEED_RANGE_KMH or stddev_kmh > STEADY_SPEED_STDDEV_KMH:
            return CaptureReadinessCheck(
                check_key="speed_stable",
                state="fail",
                reason_key="speed_variation_high",
                details=(
                    ("mean_speed_kmh", round(mean_speed_kmh, 2)),
                    ("range_kmh", round(range_kmh, 2)),
                    ("stddev_kmh", round(stddev_kmh, 2)),
                ),
            )

        return CaptureReadinessCheck(
            check_key="speed_stable",
            state="pass",
            reason_key="speed_stable",
            details=(
                ("speed_kmh", round(speed_kmh, 2)),
                ("mean_speed_kmh", round(mean_speed_kmh, 2)),
                ("range_kmh", round(range_kmh, 2)),
                ("dwell_elapsed_s", round(dwell_observed_s, 1)),
            ),
        )

    def _overall_check(
        self,
        checks: CaptureReadinessCheckTuple,
        is_ready: bool,
    ) -> CaptureReadinessCheck:
        if not is_ready:
            blocking_check = next(check for check in checks if check.failed)
            return CaptureReadinessCheck(
                check_key="capture_ready",
                state="fail",
                reason_key="capture_blocked",
                details=(("blocking_check", blocking_check.check_key),),
            )
        if any(check.warning for check in checks):
            warning_check = next(check for check in checks if check.warning)
            return CaptureReadinessCheck(
                check_key="capture_ready",
                state="warn",
                reason_key="ready_with_warnings",
                details=(("warning_check", warning_check.check_key),),
            )
        return CaptureReadinessCheck(
            check_key="capture_ready",
            state="pass",
            reason_key="capture_ready",
        )

    def _refresh_speed_history(
        self,
        now_mono: float,
        speed_kmh: float,
    ) -> tuple[_SpeedObservation, ...]:
        if self._speed_history and math.isclose(
            self._speed_history[-1].observed_at_mono_s,
            now_mono,
            abs_tol=0.001,
        ):
            self._speed_history[-1] = _SpeedObservation(
                observed_at_mono_s=now_mono,
                speed_kmh=speed_kmh,
            )
        else:
            self._speed_history.append(
                _SpeedObservation(
                    observed_at_mono_s=now_mono,
                    speed_kmh=speed_kmh,
                )
            )
        while self._speed_history and (
            now_mono - self._speed_history[0].observed_at_mono_s > _STABLE_SPEED_DWELL_S
        ):
            self._speed_history.popleft()
        return tuple(self._speed_history)

    def _speed_status(self, speed_provider: object) -> _SpeedStatusSnapshotView | None:
        if isinstance(speed_provider, _SpeedStatusProvider):
            return speed_provider.status_snapshot()
        return None

    def _obd_status(self, speed_provider: object) -> _ObdStatusSnapshotView | None:
        if isinstance(speed_provider, _ObdStatusProvider):
            return speed_provider.obd_status()
        return None


def _client_counter_snapshot(client: TrackedClient) -> _ClientCounterSnapshot:
    return _ClientCounterSnapshot(
        frames_dropped=int(getattr(client, "frames_dropped", 0)),
        queue_overflow_drops=int(getattr(client, "queue_overflow_drops", 0)),
        server_queue_drops=int(getattr(client, "server_queue_drops", 0)),
        parse_errors=int(getattr(client, "parse_errors", 0)),
    )


def _stddev(values: tuple[float, ...]) -> float:
    if len(values) < 2:
        return 0.0
    mean_value = sum(values) / len(values)
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def _is_finite_number(value: object) -> bool:
    return isinstance(value, NUMERIC_TYPES) and not isinstance(value, bool) and math.isfinite(value)
