from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from vibesensor.adapters.gps.speed_resolution import SpeedResolution
from vibesensor.adapters.gps.speed_status import SpeedSourceStatusSnapshot
from vibesensor.adapters.obd.models import ObdStatusSnapshot
from vibesensor.adapters.speed import SpeedSourceCoordinator


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


def test_speed_source_coordinator_switches_to_obd_status_and_resolution() -> None:
    gps_monitor = MagicMock()
    gps_monitor.speed_mps = 5.0
    gps_monitor.gps_enabled = True
    gps_monitor.status_snapshot.return_value = _gps_status_snapshot()
    gps_monitor.apply_speed_source_settings.return_value = None

    obd_monitor = MagicMock()
    obd_monitor.resolve_speed.return_value = SpeedResolution(12.0, False, "obd2")
    obd_monitor.status_snapshot.return_value = ObdStatusSnapshot(
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
        last_error=None,
        last_raw_response="410D0C",
        reconnect_delay_s=None,
        debug_hint=None,
    )
    obd_monitor.stale_timeout_s = 8.0
    coordinator = SpeedSourceCoordinator(gps_monitor=gps_monitor, obd_monitor=obd_monitor)

    coordinator.apply_speed_source_settings(
        effective_speed_kmh=None,
        manual_source_selected=False,
        stale_timeout_s=8.0,
        selected_source="obd2",
        obd_device_mac="00043e5a4a4d",
        obd_device_name="OBDLink MX+",
    )

    status = coordinator.status_snapshot()

    assert coordinator.resolve_speed().source == "obd2"
    assert coordinator.gps_speed_mps == pytest.approx(5.0)
    assert status.device == "OBDLink MX+ (00043e5a4a4d)"
    assert status.raw_speed_kmh == pytest.approx(43.2)
    assert status.speed_source == "obd2"
