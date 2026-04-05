from __future__ import annotations

from vibesensor.adapters.gps.speed_status import SpeedSourceStatusSnapshot
from vibesensor.adapters.http.settings.presentation import (
    obd_pair_response,
    obd_scan_response,
    obd_status_response,
    speed_source_status_response,
)
from vibesensor.adapters.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot


def test_speed_source_status_response_projects_snapshot() -> None:
    response = speed_source_status_response(
        SpeedSourceStatusSnapshot(
            gps_enabled=True,
            connection_state="connected",
            device="GPS dongle",
            fix_mode=3,
            fix_dimension="3d",
            speed_confidence="high",
            epx_m=1.2,
            epy_m=1.3,
            epv_m=2.4,
            last_update_age_s=0.8,
            raw_speed_kmh=42.5,
            effective_speed_kmh=41.7,
            last_error=None,
            reconnect_delay_s=None,
            fallback_active=False,
            speed_source="gps",
            stale_timeout_s=10.0,
        )
    )

    assert response.model_dump() == {
        "gps_enabled": True,
        "connection_state": "connected",
        "device": "GPS dongle",
        "fix_mode": 3,
        "fix_dimension": "3d",
        "speed_confidence": "high",
        "epx_m": 1.2,
        "epy_m": 1.3,
        "epv_m": 2.4,
        "last_update_age_s": 0.8,
        "raw_speed_kmh": 42.5,
        "effective_speed_kmh": 41.7,
        "last_error": None,
        "reconnect_delay_s": None,
        "fallback_active": False,
        "speed_source": "gps",
        "stale_timeout_s": 10.0,
    }


def test_obd_scan_and_pair_responses_project_device_snapshot() -> None:
    device = ObdDeviceSnapshot(
        mac_address="AA:BB:CC:DD:EE:FF",
        name="Vgate",
        paired=True,
        trusted=True,
        connected=False,
        rfcomm_channel=1,
    )

    scan_response = obd_scan_response([device])
    pair_response = obd_pair_response(
        configured_device_mac="AA:BB:CC:DD:EE:FF",
        configured_device_name="Vgate",
        snapshot=device,
    )

    assert scan_response.model_dump() == {
        "devices": [
            {
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "name": "Vgate",
                "paired": True,
                "trusted": True,
                "connected": False,
                "rfcomm_channel": 1,
            }
        ]
    }
    assert pair_response.model_dump() == {
        "configured_device_mac": "AA:BB:CC:DD:EE:FF",
        "configured_device_name": "Vgate",
        "paired": True,
        "trusted": True,
        "connected": False,
        "rfcomm_channel": 1,
    }


def test_obd_status_response_includes_debug_hint() -> None:
    response = obd_status_response(
        ObdStatusSnapshot(
            configured_device_mac=None,
            configured_device_name=None,
            connection_state="disconnected",
            device_mac=None,
            device_name=None,
            paired=False,
            trusted=False,
            connected=False,
            rfcomm_channel=None,
            last_sample_age_s=None,
            last_speed_kmh=None,
            last_rpm=None,
            rpm_sample_age_s=None,
            rpm_target_interval_ms=None,
            rpm_effective_hz=None,
            request_rtt_ms=None,
            timeout_count=0,
            error_count=0,
            poll_mode=None,
            backoff_active=False,
            last_error=None,
            last_raw_response=None,
            reconnect_delay_s=5.0,
        )
    )

    assert response.debug_hint == (
        "Pair a Bluetooth OBD adapter in Settings before selecting OBD-II as the speed source."
    )
