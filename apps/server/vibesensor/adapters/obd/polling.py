"""PID polling and cadence helpers for Bluetooth OBD speed monitoring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from vibesensor.adapters.obd.elm327 import (
    Elm327Session,
    ObdTransportError,
    elm_response_has_no_data,
    parse_pid_010c_rpm,
    parse_pid_010d_speed_kmh,
)

__all__ = [
    "ObdPidFailureKind",
    "ObdPidPollResult",
    "ObdPollPlan",
    "ObdPollResult",
    "ObdPollingCadence",
    "ObdPollingSnapshot",
    "execute_poll_plan",
]

_ADAPTIVE_POLL_INTERVALS_S = (0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 0.5, 0.75)
_MIN_REQUEST_TIMEOUT_S = 0.2
_MAX_RPM_REQUEST_TIMEOUT_S = 2.0
_MAX_SPEED_REQUEST_TIMEOUT_S = 0.75
_SPEED_COMPANION_INTERVAL_MULTIPLIER = 4.0
_MIN_SPEED_COMPANION_INTERVAL_S = 0.5
_MAX_SPEED_COMPANION_INTERVAL_S = 1.5
_REQUEST_RTT_EMA_WEIGHT = 0.25
_RPM_INTERVAL_EMA_WEIGHT = 0.25
_STABLE_POLLS_TO_SPEED_UP = 6
_FATAL_TRANSPORT_MARKERS = (
    "closed the rfcomm socket",
    "session is not connected",
    "bad file descriptor",
    "broken pipe",
    "connection reset",
    "host is down",
)

MonotonicFn = Callable[[], float]
PidParser = Callable[[str], float | None]


def _normalized_poll_interval_s(value: float) -> float:
    return max(0.2, float(value))


def _adaptive_interval_steps(max_interval_s: float) -> tuple[float, ...]:
    normalized = _normalized_poll_interval_s(max_interval_s)
    steps = tuple(step for step in _ADAPTIVE_POLL_INTERVALS_S if step <= normalized)
    if not steps:
        return (normalized,)
    if steps[-1] != normalized:
        return (*steps, normalized)
    return steps


def _update_ema(current: float | None, sample: float, *, weight: float) -> float:
    return sample if current is None else ((1.0 - weight) * current) + (weight * sample)


class ObdPidFailureKind(StrEnum):
    """Typed failure categories for individual PID requests."""

    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    FATAL_TRANSPORT = "fatal_transport"
    NO_DATA = "no_data"
    PARSE_ERROR = "parse_error"


@dataclass(frozen=True, slots=True)
class ObdPidPollResult:
    value: float | None
    raw_response: str | None
    error: str | None
    duration_s: float | None
    executed: bool
    started_at_s: float | None = None
    failure_kind: ObdPidFailureKind | None = None

    @classmethod
    def skipped(cls) -> ObdPidPollResult:
        return cls(
            value=None,
            raw_response=None,
            error=None,
            duration_s=None,
            executed=False,
        )

    @property
    def timed_out(self) -> bool:
        return self.failure_kind is ObdPidFailureKind.TIMEOUT

    @property
    def no_data(self) -> bool:
        return self.failure_kind is ObdPidFailureKind.NO_DATA

    @property
    def fatal_transport(self) -> bool:
        return self.failure_kind is ObdPidFailureKind.FATAL_TRANSPORT


@dataclass(frozen=True, slots=True)
class ObdPollResult:
    rpm: ObdPidPollResult
    speed: ObdPidPollResult

    @property
    def raw_response(self) -> str | None:
        raw_parts = [part for part in (self.rpm.raw_response, self.speed.raw_response) if part]
        return " | ".join(raw_parts) if raw_parts else None

    @property
    def connection_lost(self) -> bool:
        return self.rpm.fatal_transport or self.speed.fatal_transport


@dataclass(frozen=True, slots=True)
class ObdPollPlan:
    rpm_due: bool
    speed_due: bool
    rpm_timeout_s: float
    speed_timeout_s: float


@dataclass(frozen=True, slots=True)
class ObdPollingSnapshot:
    rpm_target_interval_ms: int
    rpm_effective_hz: float | None
    request_rtt_ms: float | None
    timeout_count: int
    error_count: int
    poll_mode: str
    backoff_active: bool
    last_raw_response: str | None


def _transport_failure_kind(error: str) -> ObdPidFailureKind:
    lowered = error.lower()
    if "timed out" in lowered:
        return ObdPidFailureKind.TIMEOUT
    if any(marker in lowered for marker in _FATAL_TRANSPORT_MARKERS):
        return ObdPidFailureKind.FATAL_TRANSPORT
    return ObdPidFailureKind.TRANSPORT


def _request_pid(
    session: Elm327Session,
    *,
    command: str,
    timeout_s: float,
    parser: PidParser,
    no_data_message: str,
    parse_error_message: str,
    monotonic: MonotonicFn,
) -> ObdPidPollResult:
    started_at_s = monotonic()
    try:
        raw_response = session.request(command, timeout_s=timeout_s)
    except ObdTransportError as exc:
        duration_s = max(0.0, monotonic() - started_at_s)
        raw_error = str(exc)
        failure_kind = _transport_failure_kind(raw_error)
        error = (
            f"Timed out waiting for PID {command} response"
            if failure_kind is ObdPidFailureKind.TIMEOUT
            else f"PID {command} request failed: {raw_error}"
        )
        return ObdPidPollResult(
            value=None,
            raw_response=None,
            error=error,
            duration_s=duration_s,
            executed=True,
            started_at_s=started_at_s,
            failure_kind=failure_kind,
        )

    duration_s = max(0.0, monotonic() - started_at_s)
    value = parser(raw_response)
    no_data = elm_response_has_no_data(raw_response)
    if value is not None:
        return ObdPidPollResult(
            value=value,
            raw_response=raw_response,
            error=None,
            duration_s=duration_s,
            executed=True,
            started_at_s=started_at_s,
        )

    failure_kind = ObdPidFailureKind.NO_DATA if no_data else ObdPidFailureKind.PARSE_ERROR
    error = (
        no_data_message
        if failure_kind is ObdPidFailureKind.NO_DATA
        else parse_error_message.format(response=raw_response or "<empty>")
    )
    return ObdPidPollResult(
        value=None,
        raw_response=raw_response,
        error=error,
        duration_s=duration_s,
        executed=True,
        started_at_s=started_at_s,
        failure_kind=failure_kind,
    )


def execute_poll_plan(
    session: Elm327Session,
    *,
    plan: ObdPollPlan,
    monotonic: MonotonicFn,
) -> ObdPollResult:
    rpm = (
        _request_pid(
            session,
            command="010C",
            timeout_s=plan.rpm_timeout_s,
            parser=parse_pid_010c_rpm,
            no_data_message="ECU returned no RPM data for PID 010C",
            parse_error_message="Unexpected RPM response for PID 010C: {response}",
            monotonic=monotonic,
        )
        if plan.rpm_due
        else ObdPidPollResult.skipped()
    )
    speed = (
        _request_pid(
            session,
            command="010D",
            timeout_s=plan.speed_timeout_s,
            parser=parse_pid_010d_speed_kmh,
            no_data_message="ECU returned no speed data for PID 010D",
            parse_error_message="Unexpected speed response for PID 010D: {response}",
            monotonic=monotonic,
        )
        if plan.speed_due and not (rpm.executed and rpm.error is not None)
        else ObdPidPollResult.skipped()
    )
    return ObdPollResult(rpm=rpm, speed=speed)


class ObdPollingCadence:
    """Own the adaptive RPM cadence, backoff, and poll metrics."""

    __slots__ = (
        "_adaptive_interval_steps",
        "_avg_request_rtt_s",
        "_effective_rpm_interval_s",
        "_error_count",
        "_last_raw_response",
        "_last_rpm_poll_started_at",
        "_rpm_interval_index",
        "_rpm_next_poll_at",
        "_rpm_stable_poll_count",
        "_speed_degraded",
        "_speed_next_poll_at",
        "_timeout_count",
    )

    def __init__(self, *, max_interval_s: float) -> None:
        self._adaptive_interval_steps = _adaptive_interval_steps(max_interval_s)
        self._avg_request_rtt_s: float | None = None
        self._effective_rpm_interval_s: float | None = None
        self._last_rpm_poll_started_at: float | None = None
        self._rpm_interval_index = 0
        self._rpm_next_poll_at: float | None = None
        self._rpm_stable_poll_count = 0
        self._speed_degraded = False
        self._speed_next_poll_at: float | None = None
        self._timeout_count = 0
        self._error_count = 0
        self._last_raw_response: str | None = None

    def prepare_poll(self, *, now: float) -> ObdPollPlan:
        rpm_due = self._rpm_next_poll_at is None or now >= self._rpm_next_poll_at
        speed_due = self._speed_next_poll_at is None or now >= self._speed_next_poll_at
        return ObdPollPlan(
            rpm_due=rpm_due,
            speed_due=speed_due,
            rpm_timeout_s=self._rpm_request_timeout_s(),
            speed_timeout_s=self._speed_request_timeout_s(),
        )

    def apply_result(self, result: ObdPollResult, *, now: float) -> None:
        self._record_pid_metrics(result.rpm)
        self._record_pid_metrics(result.speed)
        self._record_rpm_cadence(result.rpm)
        self._adapt_rpm_interval(result.rpm)
        current_target_interval_s = self._current_rpm_target_interval_s()
        if result.rpm.executed and result.rpm.started_at_s is not None:
            self._rpm_next_poll_at = result.rpm.started_at_s + current_target_interval_s
        elif self._rpm_next_poll_at is None:
            self._rpm_next_poll_at = now
        if result.speed.executed and result.speed.started_at_s is not None:
            self._speed_next_poll_at = (
                result.speed.started_at_s + self._speed_companion_interval_s()
            )
        elif self._speed_next_poll_at is None:
            self._speed_next_poll_at = now
        if result.speed.value is not None:
            self._speed_degraded = False
        elif result.speed.executed and (result.speed.error is not None or result.speed.no_data):
            self._speed_degraded = True
        self._last_raw_response = result.raw_response

    def next_wait_s(self, *, now: float) -> float:
        due_times = [
            due for due in (self._rpm_next_poll_at, self._speed_next_poll_at) if due is not None
        ]
        if not due_times:
            return 0.0
        return max(0.0, min(due_times) - now)

    def reset(self, *, now: float) -> None:
        self._avg_request_rtt_s = None
        self._effective_rpm_interval_s = None
        self._last_rpm_poll_started_at = None
        self._rpm_interval_index = 0
        self._rpm_next_poll_at = now
        self._rpm_stable_poll_count = 0
        self._speed_degraded = False
        self._speed_next_poll_at = now
        self._timeout_count = 0
        self._error_count = 0
        self._last_raw_response = None

    def snapshot(self) -> ObdPollingSnapshot:
        return ObdPollingSnapshot(
            rpm_target_interval_ms=int(round(self._current_rpm_target_interval_s() * 1000.0)),
            rpm_effective_hz=(
                None
                if self._effective_rpm_interval_s is None or self._effective_rpm_interval_s <= 0
                else round(1.0 / self._effective_rpm_interval_s, 2)
            ),
            request_rtt_ms=(
                None
                if self._avg_request_rtt_s is None
                else round(self._avg_request_rtt_s * 1000.0, 1)
            ),
            timeout_count=self._timeout_count,
            error_count=self._error_count,
            poll_mode=(
                f"{'rpm_only' if self._speed_degraded else 'rpm_priority'}_backoff"
                if self._rpm_interval_index > 0
                else ("rpm_only" if self._speed_degraded else "rpm_priority")
            ),
            backoff_active=self._rpm_interval_index > 0,
            last_raw_response=self._last_raw_response,
        )

    def _record_pid_metrics(self, result: ObdPidPollResult) -> None:
        if not result.executed:
            return
        if result.duration_s is not None:
            self._avg_request_rtt_s = _update_ema(
                self._avg_request_rtt_s,
                result.duration_s,
                weight=_REQUEST_RTT_EMA_WEIGHT,
            )
        if result.failure_kind is None:
            return
        if result.failure_kind is ObdPidFailureKind.TIMEOUT:
            self._timeout_count += 1
        elif result.failure_kind is not ObdPidFailureKind.NO_DATA:
            self._error_count += 1

    def _record_rpm_cadence(self, result: ObdPidPollResult) -> None:
        if not result.executed or result.started_at_s is None:
            return
        if self._last_rpm_poll_started_at is not None:
            interval_s = max(0.001, result.started_at_s - self._last_rpm_poll_started_at)
            self._effective_rpm_interval_s = _update_ema(
                self._effective_rpm_interval_s,
                interval_s,
                weight=_RPM_INTERVAL_EMA_WEIGHT,
            )
        self._last_rpm_poll_started_at = result.started_at_s

    def _adapt_rpm_interval(self, result: ObdPidPollResult) -> None:
        if not result.executed:
            return
        target_interval_s = self._current_rpm_target_interval_s()
        should_backoff = (
            result.error is not None
            or result.no_data
            or (result.duration_s is not None and result.duration_s > target_interval_s)
        )
        if should_backoff:
            if self._rpm_interval_index < len(self._adaptive_interval_steps) - 1:
                self._rpm_interval_index += 1
            self._rpm_stable_poll_count = 0
            return
        self._rpm_stable_poll_count += 1
        if self._rpm_interval_index <= 0 or self._rpm_stable_poll_count < _STABLE_POLLS_TO_SPEED_UP:
            return
        faster_interval_s = self._adaptive_interval_steps[self._rpm_interval_index - 1]
        reference_rtt_s = (
            self._avg_request_rtt_s if self._avg_request_rtt_s is not None else result.duration_s
        )
        if reference_rtt_s is not None and reference_rtt_s <= (faster_interval_s * 0.9):
            self._rpm_interval_index -= 1
            self._rpm_stable_poll_count = 0

    def _current_rpm_target_interval_s(self) -> float:
        return self._adaptive_interval_steps[self._rpm_interval_index]

    def _speed_companion_interval_s(self) -> float:
        return min(
            _MAX_SPEED_COMPANION_INTERVAL_S,
            max(
                _MIN_SPEED_COMPANION_INTERVAL_S,
                self._current_rpm_target_interval_s() * _SPEED_COMPANION_INTERVAL_MULTIPLIER,
            ),
        )

    def _rpm_request_timeout_s(self) -> float:
        return min(
            _MAX_RPM_REQUEST_TIMEOUT_S,
            max(_MIN_REQUEST_TIMEOUT_S, self._current_rpm_target_interval_s() * 4.0),
        )

    def _speed_request_timeout_s(self) -> float:
        return min(
            _MAX_SPEED_REQUEST_TIMEOUT_S,
            max(_MIN_REQUEST_TIMEOUT_S, self._current_rpm_target_interval_s() * 2.0),
        )
