from __future__ import annotations

from unittest.mock import MagicMock

from vibesensor.adapters.obd.elm327 import ObdTransportError
from vibesensor.adapters.obd.polling import (
    ObdPidFailureKind,
    ObdPidPollResult,
    ObdPollingCadence,
    ObdPollPlan,
    ObdPollResult,
    execute_poll_plan,
)


class _FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_execute_poll_plan_classifies_fatal_transport_and_skips_speed() -> None:
    clock = _FakeClock()
    session = MagicMock()

    def request(command: str, *, timeout_s: float | None = None) -> str:
        assert command == "010C"
        assert timeout_s == 0.2
        clock.advance(0.05)
        raise ObdTransportError("Session is not connected")

    session.request.side_effect = request

    result = execute_poll_plan(
        session,
        plan=ObdPollPlan(
            rpm_due=True,
            speed_due=True,
            rpm_timeout_s=0.2,
            speed_timeout_s=0.2,
        ),
        monotonic=clock,
    )

    assert result.rpm.failure_kind is ObdPidFailureKind.FATAL_TRANSPORT
    assert result.rpm.error == "PID 010C request failed: Session is not connected"
    assert result.connection_lost is True
    assert result.speed.executed is False
    assert session.request.call_count == 1


def test_polling_cadence_backs_off_and_reports_snapshot() -> None:
    cadence = ObdPollingCadence(max_interval_s=0.75)
    cadence.reset(now=0.0)

    cadence.apply_result(
        ObdPollResult(
            rpm=ObdPidPollResult(
                value=0x1AF8 / 4.0,
                raw_response="410C1AF8",
                error=None,
                duration_s=0.12,
                executed=True,
                started_at_s=0.0,
            ),
            speed=ObdPidPollResult(
                value=None,
                raw_response=None,
                error="Timed out waiting for PID 010D response",
                duration_s=0.2,
                executed=True,
                started_at_s=0.12,
                failure_kind=ObdPidFailureKind.TIMEOUT,
            ),
        ),
        now=0.32,
    )

    snapshot = cadence.snapshot()
    plan = cadence.prepare_poll(now=0.2)

    assert snapshot.poll_mode == "rpm_only_backoff"
    assert snapshot.backoff_active is True
    assert snapshot.timeout_count == 1
    assert snapshot.error_count == 0
    assert snapshot.rpm_target_interval_ms == 75
    assert snapshot.request_rtt_ms is not None
    assert snapshot.last_raw_response == "410C1AF8"
    assert plan.rpm_due is True
    assert plan.speed_due is False
    assert plan.rpm_timeout_s == 0.3
