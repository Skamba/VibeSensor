from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.adapters.gps.speed_status import SpeedSourceStatusSnapshot
from vibesensor.adapters.http.settings import create_settings_routes
from vibesensor.adapters.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot
from vibesensor.shared.operational_errors import ExternalCommandError


def _build_client() -> tuple[TestClient, MagicMock, MagicMock, MagicMock, MagicMock]:
    settings_store = MagicMock()
    speed_source_service = MagicMock()
    speed_status_service = MagicMock()
    speed_status_service.status_snapshot.return_value = SpeedSourceStatusSnapshot(
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
    obd_admin_service = MagicMock()
    app = FastAPI()
    app.include_router(
        create_settings_routes(
            settings_store,
            speed_source_service,
            speed_status_service,
            obd_admin_service,
        )
    )
    return (
        TestClient(app),
        settings_store,
        speed_source_service,
        speed_status_service,
        obd_admin_service,
    )


def test_scan_obd_devices_endpoint_returns_serialized_devices() -> None:
    client, _, _, _speed_status_service, obd_admin_service = _build_client()
    obd_admin_service.scan_obd_devices.return_value = [
        ObdDeviceSnapshot(
            mac_address="00043e5a4a4d",
            name="OBDLink MX+",
            paired=True,
            trusted=True,
            connected=False,
            rfcomm_channel=1,
        )
    ]

    response = client.post("/api/settings/obd/scan")

    assert response.status_code == 200
    assert response.json()["devices"][0]["mac_address"] == "00043e5a4a4d"
    obd_admin_service.scan_obd_devices.assert_called_once_with()


def test_scan_obd_devices_endpoint_returns_structured_runtime_error_detail() -> None:
    client, _, _, _speed_status_service, obd_admin_service = _build_client()
    obd_admin_service.scan_obd_devices.side_effect = ExternalCommandError(
        "Bluetooth OBD scan requires the Pi sudo helper and NOPASSWD sudoers entry "
        "to run non-interactively."
    )

    response = client.post("/api/settings/obd/scan")

    assert response.status_code == 503
    assert response.json() == {
        "detail": (
            "Bluetooth OBD scan requires the Pi sudo helper and NOPASSWD sudoers entry "
            "to run non-interactively."
        )
    }


def test_pair_obd_device_endpoint_returns_503_for_operational_failure() -> None:
    client, _, _, _speed_status_service, obd_admin_service = _build_client()
    obd_admin_service.pair_obd_device.side_effect = ExternalCommandError(
        "Bluetooth OBD helper failed"
    )

    response = client.post(
        "/api/settings/obd/pair",
        json={"mac_address": "00:04:3E:5A:4A:4D"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Bluetooth OBD helper failed"}


def test_pair_obd_device_endpoint_normalizes_mac_and_persists_config() -> None:
    (
        client,
        settings_store,
        speed_source_service,
        _speed_status_service,
        obd_admin_service,
    ) = _build_client()
    obd_admin_service.pair_obd_device.return_value = ObdDeviceSnapshot(
        mac_address="00043e5a4a4d",
        name="OBDLink MX+",
        paired=True,
        trusted=True,
        connected=True,
        rfcomm_channel=1,
    )
    speed_source_service.update_speed_source.return_value = {
        "speedSource": "gps",
        "manualSpeedKph": None,
        "staleTimeoutS": 8.0,
        "obdDeviceMac": "00043e5a4a4d",
        "obdDeviceName": "OBDLink MX+",
    }

    response = client.post(
        "/api/settings/obd/pair",
        json={"mac_address": "00:04:3E:5A:4A:4D"},
    )

    assert response.status_code == 200
    assert response.json()["configured_device_mac"] == "00043e5a4a4d"
    obd_admin_service.pair_obd_device.assert_called_once_with("00043e5a4a4d")
    settings_store.update_speed_source.assert_not_called()
    speed_source_service.update_speed_source.assert_called_once_with(
        {
            "obdDeviceMac": "00043e5a4a4d",
            "obdDeviceName": "OBDLink MX+",
        }
    )


def test_get_obd_status_endpoint_returns_runtime_snapshot() -> None:
    client, _, _, speed_status_service, _obd_admin_service = _build_client()
    speed_status_service.obd_status.return_value = ObdStatusSnapshot(
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
        rpm_target_interval_ms=75,
        rpm_effective_hz=13.3,
        request_rtt_ms=61.4,
        timeout_count=1,
        error_count=2,
        poll_mode="rpm_only_backoff",
        backoff_active=True,
        last_error=None,
        last_raw_response="410D0C",
        reconnect_delay_s=None,
        debug_hint=None,
    )

    response = client.get("/api/settings/obd/status")

    assert response.status_code == 200
    body = response.json()
    assert body["configured_device_mac"] == "00043e5a4a4d"
    assert body["last_rpm"] == 2100.0
    assert body["rpm_target_interval_ms"] == 75
    assert body["poll_mode"] == "rpm_only_backoff"
    assert body["backoff_active"] is True
    speed_status_service.obd_status.assert_called_once_with()
