from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from vibesensor.adapters.obd.models import ObdDeviceSnapshot
from vibesensor.adapters.obd.monitor import OBDSpeedMonitor


def test_obd_monitor_polls_speed_and_rpm_from_connected_session() -> None:
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
    session.request.side_effect = ["410D28", "410C1AF8"]
    monitor = OBDSpeedMonitor(
        admin_client=admin_client,
        session_factory=lambda: session,
        monotonic=time.monotonic,
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
    monitor._set_connection_state("connected", error=None)
    monitor._apply_poll_result(monitor._poll_cycle_blocking(connected_session))

    session.connect.assert_called_once_with("00043e5a4a4d", 1)
    session.initialize.assert_called_once_with()
    assert monitor.resolve_speed().source == "obd2"
    assert monitor.resolve_speed().speed_mps == pytest.approx(40.0 / 3.6)
    status = monitor.status_snapshot(refresh_admin=False)
    assert status.last_speed_kmh == pytest.approx(40.0)
    assert status.last_rpm == pytest.approx(0x1AF8 / 4.0)
    assert status.connection_state == "connected"


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
    admin_client.device_info.side_effect = RuntimeError("sudo: a password is required")
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
