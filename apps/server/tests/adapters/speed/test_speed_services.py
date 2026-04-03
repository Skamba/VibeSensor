from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from vibesensor.adapters.gps.speed_resolution import SpeedResolution
from vibesensor.adapters.gps.speed_status import SpeedSourceStatusSnapshot
from vibesensor.adapters.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot
from vibesensor.adapters.speed import build_speed_source_services


def _gps_status_snapshot() -> SpeedSourceStatusSnapshot:
    return SpeedSourceStatusSnapshot(
        gps_enabled=True,
        connection_state="connected",
        device="/dev/ttyUSB0",
        fix_mode=3,
        fix_dimension="3d",
        speed_confidence="high",
        epx_m=1.0,
        epy_m=1.0,
        epv_m=1.0,
        last_update_age_s=0.5,
        raw_speed_kmh=48.0,
        effective_speed_kmh=48.0,
        last_error=None,
        reconnect_delay_s=None,
        fallback_active=False,
        speed_source="gps",
        stale_timeout_s=8.0,
    )


def _obd_status_snapshot() -> ObdStatusSnapshot:
    return ObdStatusSnapshot(
        configured_device_mac="00043e5a4a4d",
        configured_device_name="OBDLink MX+",
        connection_state="connected",
        device_mac="00043e5a4a4d",
        device_name="OBDLink MX+",
        paired=True,
        trusted=True,
        connected=True,
        rfcomm_channel=1,
        last_sample_age_s=0.2,
        last_speed_kmh=43.2,
        last_rpm=2100.0,
        rpm_sample_age_s=0.1,
        rpm_target_interval_ms=50,
        rpm_effective_hz=20.0,
        request_rtt_ms=48.0,
        timeout_count=0,
        error_count=0,
        poll_mode="rpm_priority",
        backoff_active=False,
        last_error=None,
        last_raw_response="410D0C",
        reconnect_delay_s=None,
        debug_hint=None,
    )


def test_observation_service_switches_to_obd_status_and_resolution() -> None:
    gps_monitor = MagicMock()
    gps_monitor.speed_mps = 5.0
    gps_monitor.gps_enabled = True
    gps_monitor.status_snapshot.return_value = _gps_status_snapshot()
    gps_monitor.apply_speed_source_settings.return_value = None

    obd_monitor = MagicMock()
    obd_monitor.resolve_speed.return_value = SpeedResolution(12.0, False, "obd2")
    obd_monitor.status_snapshot.return_value = _obd_status_snapshot()
    obd_monitor.stale_timeout_s = 8.0
    services = build_speed_source_services(gps_monitor=gps_monitor, obd_monitor=obd_monitor)

    services.control.apply_speed_source_settings(
        effective_speed_kmh=None,
        manual_source_selected=False,
        stale_timeout_s=8.0,
        selected_source="obd2",
        obd_device_mac="00043e5a4a4d",
        obd_device_name="OBDLink MX+",
    )

    status = services.observation.status_snapshot()

    assert services.observation.resolve_speed().source == "obd2"
    assert services.observation.gps_speed_mps == pytest.approx(5.0)
    assert status.device == "OBDLink MX+ (00043e5a4a4d)"
    assert status.raw_speed_kmh == pytest.approx(43.2)
    assert status.speed_source == "obd2"
    obd_monitor.refresh_admin_state.assert_not_called()
    obd_monitor.status_snapshot.assert_called_once_with()


def test_observation_service_obd_status_is_side_effect_free() -> None:
    gps_monitor = MagicMock()
    obd_monitor = MagicMock()
    expected_status = _obd_status_snapshot()
    obd_monitor.status_snapshot.return_value = expected_status
    services = build_speed_source_services(gps_monitor=gps_monitor, obd_monitor=obd_monitor)

    services.control.apply_speed_source_settings(
        effective_speed_kmh=None,
        manual_source_selected=False,
        stale_timeout_s=8.0,
        selected_source="obd2",
        obd_device_mac="00043e5a4a4d",
        obd_device_name="OBDLink MX+",
    )

    status = services.observation.obd_status()

    assert status == expected_status
    obd_monitor.refresh_admin_state.assert_not_called()
    obd_monitor.status_snapshot.assert_called_once_with()


def test_admin_service_refreshes_obd_status_explicitly() -> None:
    gps_monitor = MagicMock()
    obd_monitor = MagicMock()
    services = build_speed_source_services(gps_monitor=gps_monitor, obd_monitor=obd_monitor)

    services.admin.refresh_obd_status()

    obd_monitor.refresh_admin_state.assert_called_once_with()


def test_admin_service_delegates_scan_and_pair_to_obd_monitor() -> None:
    gps_monitor = MagicMock()
    obd_monitor = MagicMock()
    device = ObdDeviceSnapshot(
        mac_address="00043e5a4a4d",
        name="OBDLink MX+",
        paired=True,
        trusted=True,
        connected=False,
        rfcomm_channel=1,
    )
    obd_monitor.scan_devices.return_value = [device]
    obd_monitor.pair_device.return_value = device
    services = build_speed_source_services(gps_monitor=gps_monitor, obd_monitor=obd_monitor)

    scanned = services.admin.scan_obd_devices()
    paired = services.admin.pair_obd_device("00043e5a4a4d")

    assert scanned == [device]
    assert paired == device
    obd_monitor.scan_devices.assert_called_once_with(timeout_s=8)
    obd_monitor.pair_device.assert_called_once_with("00043e5a4a4d")
