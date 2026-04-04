from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from test_support.obd_runtime import (
    FakeClock as _FakeClock,
)
from test_support.obd_runtime import (
    build_connected_obd_runtime_parts as _connected_runtime_parts,
)
from test_support.obd_runtime import (
    build_obd_runtime_parts as _build_runtime_parts,
)

from vibesensor.adapters.http.obd_status_presentation import obd_debug_hint
from vibesensor.adapters.obd.elm327 import ObdTransportError
from vibesensor.adapters.obd.models import ObdDeviceSnapshot
from vibesensor.adapters.obd.polling import ObdPidFailureKind, ObdPidPollResult, ObdPollResult
from vibesensor.shared.operational_errors import ExternalCommandError


def test_obd_observation_prioritizes_rpm_and_keeps_speed_as_a_companion_poll() -> None:
    clock = _FakeClock(now=time.monotonic())
    started_at = clock.now
    calls: list[tuple[str, float | None]] = []
    rpm_responses = [("410C1AF8", 0.01), ("410C1AF8", 0.01)]
    speed_responses = [("410D28", 0.02)]
    parts = _connected_runtime_parts(clock=clock)

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

    parts.session.request.side_effect = request

    parts.connection_state.apply_poll_cycle(parts.executor._poll_cycle_blocking(parts.session))
    clock.now = started_at + 0.05
    parts.connection_state.apply_poll_cycle(parts.executor._poll_cycle_blocking(parts.session))

    assert calls == [("010C", 0.2), ("010D", 0.2), ("010C", 0.2)]
    assert parts.observation.resolve_speed().source == "obd2"
    assert parts.observation.resolve_speed().speed_mps == pytest.approx(40.0 / 3.6)
    status = parts.observation.status_snapshot()
    assert status.last_speed_kmh == pytest.approx(40.0)
    assert status.last_rpm == pytest.approx(0x1AF8 / 4.0)
    assert status.rpm_target_interval_ms == 50
    assert status.rpm_effective_hz == pytest.approx(20.0)
    assert status.poll_mode == "rpm_priority"
    assert status.backoff_active is False
    assert status.connection_state == "connected"


def test_obd_observation_keeps_last_good_rpm_until_the_reference_goes_stale() -> None:
    clock = _FakeClock()
    rpm_responses = [("410C1AF8", 0.01)]
    speed_responses = [("410D28", 0.01)]
    parts = _connected_runtime_parts(clock=clock)

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

    parts.session.request.side_effect = request

    parts.connection_state.apply_poll_cycle(parts.executor._poll_cycle_blocking(parts.session))
    clock.now = 0.05
    parts.connection_state.apply_poll_cycle(parts.executor._poll_cycle_blocking(parts.session))

    assert parts.observation.engine_rpm == pytest.approx(0x1AF8 / 4.0)
    clock.now = 1.99
    assert parts.observation.engine_rpm == pytest.approx(0x1AF8 / 4.0)
    clock.now = 2.11
    assert parts.observation.engine_rpm is None

    status = parts.observation.status_snapshot()
    assert status.timeout_count == 1
    assert status.backoff_active is True


def test_obd_connection_state_backs_off_and_stays_in_rpm_only_mode_when_speed_times_out() -> None:
    clock = _FakeClock()
    calls: list[tuple[str, float | None]] = []
    rpm_responses = [("410C1AF8", 0.12), ("410C1AF8", 0.06)]
    parts = _connected_runtime_parts(clock=clock)

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

    parts.session.request.side_effect = request

    parts.connection_state.apply_poll_cycle(parts.executor._poll_cycle_blocking(parts.session))
    parts.connection_state.apply_poll_cycle(parts.executor._poll_cycle_blocking(parts.session))

    assert calls == [("010C", 0.2), ("010D", 0.2), ("010C", 0.3)]
    status = parts.observation.status_snapshot()
    assert status.poll_mode == "rpm_only_backoff"
    assert status.backoff_active is True
    assert status.timeout_count == 1
    assert status.error_count == 0
    assert status.rpm_target_interval_ms == 75
    assert status.request_rtt_ms is not None


def test_obd_runtime_observation_resolves_stale_speed_to_manual_fallback() -> None:
    parts = _build_runtime_parts(clock=lambda: 100.0)
    parts.settings.apply_speed_source_settings(
        effective_speed_kmh=54.0,
        manual_source_selected=False,
        stale_timeout_s=5.0,
        selected_source="obd2",
        obd_device_mac="00043e5a4a4d",
        obd_device_name="OBDLink MX+",
    )
    parts.store.state.speed_snapshot = (10.0, 90.0)
    parts.connection_state.mark_connected()

    resolution = parts.observation.resolve_speed()

    assert resolution.source == "fallback_manual"
    assert resolution.speed_mps == pytest.approx(54.0 / 3.6)
    assert resolution.fallback_active is True


def test_obd_status_snapshot_does_not_refresh_admin_state_implicitly() -> None:
    admin_client = MagicMock()
    parts = _build_runtime_parts(clock=lambda: 100.0, admin_client=admin_client)
    parts.settings.apply_speed_source_settings(
        effective_speed_kmh=None,
        manual_source_selected=False,
        selected_source="obd2",
        obd_device_mac="00043e5a4a4d",
        obd_device_name="OBDLink MX+",
    )

    status = parts.observation.status_snapshot()

    admin_client.device_info.assert_not_called()
    assert status.device_mac == "00043e5a4a4d"
    assert status.paired is False


def test_obd_status_reports_sudo_helper_hint_when_admin_refresh_fails() -> None:
    admin_client = MagicMock()
    admin_client.device_info.side_effect = ExternalCommandError("sudo: a password is required")
    parts = _build_runtime_parts(clock=lambda: 100.0, admin_client=admin_client)
    parts.settings.apply_speed_source_settings(
        effective_speed_kmh=None,
        manual_source_selected=False,
        selected_source="obd2",
        obd_device_mac="00043e5a4a4d",
        obd_device_name="OBDLink MX+",
    )

    parts.admin.refresh_configured_device()
    status = parts.observation.status_snapshot()

    assert "sudo" in str(status.last_error).lower()
    assert "sudo helper" in str(obd_debug_hint(status)).lower()


def test_obd_connection_state_marks_disconnected_after_fatal_poll_cycle() -> None:
    clock = _FakeClock()
    parts = _connected_runtime_parts(clock=clock)

    connection_lost = parts.connection_state.apply_poll_cycle(
        ObdPollResult(
            rpm=ObdPidPollResult(
                value=None,
                raw_response=None,
                error="PID 010C request failed: Session is not connected",
                duration_s=0.05,
                executed=True,
                failure_kind=ObdPidFailureKind.FATAL_TRANSPORT,
            ),
            speed=ObdPidPollResult.skipped(),
        ),
        reconnect_delay_s=4.0,
    )

    assert connection_lost is True
    status = parts.observation.status_snapshot()
    assert status.connection_state == "disconnected"
    assert status.last_error == "PID 010C request failed: Session is not connected"
    assert status.reconnect_delay_s == 4.0


def test_connect_blocking_closes_session_and_propagates_transport_error() -> None:
    clock = _FakeClock()
    admin_client = MagicMock()
    admin_client.device_info.return_value = ObdDeviceSnapshot(
        mac_address="00043e5a4a4d",
        name="OBDLink MX+",
        paired=True,
        trusted=True,
        connected=False,
        rfcomm_channel=1,
    )
    session = MagicMock()
    session.initialize.side_effect = ObdTransportError("no prompt from adapter")
    parts = _build_runtime_parts(clock=clock, admin_client=admin_client, session=session)

    with pytest.raises(ObdTransportError, match="no prompt from adapter"):
        parts.executor._connect_blocking("00043e5a4a4d", "OBDLink MX+")

    session.close.assert_called_once_with()


def test_connect_blocking_keeps_initialized_session_open() -> None:
    clock = _FakeClock()
    parts = _connected_runtime_parts(clock=clock)

    assert parts.runner is not None
    assert parts.observation is not None
    parts.session.initialize.assert_called_once_with()
    assert parts.session.close.call_count == 0


def test_connect_blocking_closes_session_and_propagates_unexpected_runtime_error() -> None:
    clock = _FakeClock()
    admin_client = MagicMock()
    admin_client.device_info.return_value = ObdDeviceSnapshot(
        mac_address="00043e5a4a4d",
        name="OBDLink MX+",
        paired=True,
        trusted=True,
        connected=False,
        rfcomm_channel=1,
    )
    session = MagicMock()
    session.initialize.side_effect = RuntimeError("session bug")
    parts = _build_runtime_parts(clock=clock, admin_client=admin_client, session=session)

    with pytest.raises(RuntimeError, match="session bug"):
        parts.executor._connect_blocking("00043e5a4a4d", "OBDLink MX+")

    session.close.assert_called_once_with()
