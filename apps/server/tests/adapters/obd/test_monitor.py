from __future__ import annotations

import time
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from vibesensor.adapters.obd.elm327 import ObdTransportError
from vibesensor.adapters.obd.models import ObdDeviceSnapshot
from vibesensor.adapters.obd.monitor import OBDSpeedMonitor
from vibesensor.shared.operational_errors import ExternalCommandError


class _FakeClock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _connected_monitor(
    *,
    clock: Callable[[], float],
    admin_client: MagicMock | None = None,
    session_factory: Callable[[], MagicMock] | None = None,
) -> tuple[OBDSpeedMonitor, MagicMock]:
    admin = MagicMock() if admin_client is None else admin_client
    admin.device_info.return_value = ObdDeviceSnapshot(
        mac_address="00043e5a4a4d",
        name="OBDLink MX+",
        paired=True,
        trusted=True,
        connected=False,
        rfcomm_channel=1,
    )
    session = MagicMock()
    monitor = OBDSpeedMonitor(
        admin_client=admin,
        session_factory=(lambda: session) if session_factory is None else session_factory,
        monotonic=clock,
    )
    monitor.apply_speed_source_settings(
        effective_speed_kmh=None,
        manual_source_selected=False,
        stale_timeout_s=5.0,
        selected_source="obd2",
        obd_device_mac="00043e5a4a4d",
        obd_device_name="OBDLink MX+",
    )
    connected_session, device = monitor._connect_blocking("00043e5a4a4d", "OBDLink MX+")
    monitor._apply_device_snapshot(device)
    monitor._reset_poll_schedule()
    monitor._set_connection_state("connected", error=None)
    return monitor, connected_session


def test_obd_monitor_prioritizes_rpm_and_keeps_speed_as_a_companion_poll() -> None:
    clock = _FakeClock(now=time.monotonic())
    started_at = clock.now
    calls: list[tuple[str, float | None]] = []
    rpm_responses = [("410C1AF8", 0.01), ("410C1AF8", 0.01)]
    speed_responses = [("410D28", 0.02)]

    monitor, session = _connected_monitor(clock=clock)

    def request(command: str, *, timeout_s: float | None = None) -> str:
        calls.append((command, timeout_s))
        if command == "010C":
            raw_response, duration_s = rpm_responses.pop(0)
            clock.advance(duration_s)
            return raw_response
        if command == "010D":
            raw_response, duration_s = speed_responses.pop(0)
            clock.advance(duration_s)
            return raw_response
        raise AssertionError(f"Unexpected PID request {command}")

    session.request.side_effect = request

    monitor._apply_poll_result(monitor._poll_cycle_blocking(session))
    clock.now = started_at + 0.05
    monitor._apply_poll_result(monitor._poll_cycle_blocking(session))

    assert calls == [("010C", 0.2), ("010D", 0.2), ("010C", 0.2)]
    assert monitor.resolve_speed().source == "obd2"
    assert monitor.resolve_speed().speed_mps == pytest.approx(40.0 / 3.6)
    status = monitor.status_snapshot(refresh_admin=False)
    assert status.last_speed_kmh == pytest.approx(40.0)
    assert status.last_rpm == pytest.approx(0x1AF8 / 4.0)
    assert status.rpm_target_interval_ms == 50
    assert status.rpm_effective_hz == pytest.approx(20.0)
    assert status.poll_mode == "rpm_priority"
    assert status.backoff_active is False
    assert status.connection_state == "connected"


def test_obd_monitor_keeps_last_good_rpm_until_the_rpm_reference_goes_stale() -> None:
    clock = _FakeClock()
    rpm_responses = [("410C1AF8", 0.01)]
    speed_responses = [("410D28", 0.01)]
    monitor, session = _connected_monitor(clock=clock)

    def request(command: str, *, timeout_s: float | None = None) -> str:
        if command == "010C":
            if rpm_responses:
                raw_response, duration_s = rpm_responses.pop(0)
                clock.advance(duration_s)
                return raw_response
            clock.advance(timeout_s or 0.2)
            raise ObdTransportError("Timed out waiting for OBD response prompt")
        if command == "010D":
            raw_response, duration_s = speed_responses.pop(0)
            clock.advance(duration_s)
            return raw_response
        raise AssertionError(f"Unexpected PID request {command}")

    session.request.side_effect = request

    monitor._apply_poll_result(monitor._poll_cycle_blocking(session))
    clock.now = 0.05
    monitor._apply_poll_result(monitor._poll_cycle_blocking(session))

    assert monitor.engine_rpm == pytest.approx(0x1AF8 / 4.0)
    clock.now = 1.99
    assert monitor.engine_rpm == pytest.approx(0x1AF8 / 4.0)
    clock.now = 2.11
    assert monitor.engine_rpm is None

    status = monitor.status_snapshot(refresh_admin=False)
    assert status.timeout_count == 1
    assert status.backoff_active is True


def test_obd_monitor_backs_off_and_stays_in_rpm_only_mode_when_speed_times_out() -> None:
    clock = _FakeClock()
    calls: list[tuple[str, float | None]] = []
    rpm_responses = [("410C1AF8", 0.12), ("410C1AF8", 0.06)]
    monitor, session = _connected_monitor(clock=clock)

    def request(command: str, *, timeout_s: float | None = None) -> str:
        calls.append((command, timeout_s))
        if command == "010C":
            raw_response, duration_s = rpm_responses.pop(0)
            clock.advance(duration_s)
            return raw_response
        if command == "010D":
            clock.advance(timeout_s or 0.2)
            raise ObdTransportError("Timed out waiting for OBD response prompt")
        raise AssertionError(f"Unexpected PID request {command}")

    session.request.side_effect = request

    monitor._apply_poll_result(monitor._poll_cycle_blocking(session))
    monitor._apply_poll_result(monitor._poll_cycle_blocking(session))

    assert calls == [("010C", 0.2), ("010D", 0.2), ("010C", 0.3)]
    status = monitor.status_snapshot(refresh_admin=False)
    assert status.poll_mode == "rpm_only_backoff"
    assert status.backoff_active is True
    assert status.timeout_count == 1
    assert status.error_count == 0
    assert status.rpm_target_interval_ms == 75
    assert status.request_rtt_ms is not None


def test_obd_monitor_resolves_stale_speed_to_manual_fallback() -> None:
    monitor = OBDSpeedMonitor(
        admin_client=MagicMock(),
        session_factory=lambda: MagicMock(),
        monotonic=lambda: 100.0,
    )
    monitor.apply_speed_source_settings(
        effective_speed_kmh=54.0,
        manual_source_selected=False,
        stale_timeout_s=5.0,
        selected_source="obd2",
        obd_device_mac="00043e5a4a4d",
        obd_device_name="OBDLink MX+",
    )
    monitor._speed_snapshot = (10.0, 90.0)
    monitor._set_connection_state("connected", error=None)

    resolution = monitor.resolve_speed()

    assert resolution.source == "fallback_manual"
    assert resolution.speed_mps == pytest.approx(54.0 / 3.6)
    assert resolution.fallback_active is True


def test_obd_status_reports_sudo_helper_hint_when_admin_refresh_fails() -> None:
    admin_client = MagicMock()
    admin_client.device_info.side_effect = ExternalCommandError("sudo: a password is required")
    monitor = OBDSpeedMonitor(
        admin_client=admin_client,
        session_factory=lambda: MagicMock(),
        monotonic=lambda: 100.0,
    )
    monitor.apply_speed_source_settings(
        effective_speed_kmh=None,
        manual_source_selected=False,
        selected_source="obd2",
        obd_device_mac="00043e5a4a4d",
        obd_device_name="OBDLink MX+",
    )

    status = monitor.status_snapshot(refresh_admin=True)

    assert "sudo" in str(status.last_error).lower()
    assert "sudo helper" in str(status.debug_hint).lower()
