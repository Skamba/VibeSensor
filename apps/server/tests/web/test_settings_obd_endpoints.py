from __future__ import annotations

from unittest.mock import MagicMock, create_autospec

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.common.operational_errors import ExternalCommandError
from vibesensor.settings.services import build_settings_services
from vibesensor.settings.speed_source_runtime import SpeedSourceSettingsService
from vibesensor.speed.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot
from vibesensor.speed.source_coordinator import SpeedSourceObservationService
from vibesensor.speed.speed_status import SpeedSourceStatusSnapshot


def _build_client() -> tuple[TestClient, SpeedSourceSettingsService, MagicMock, MagicMock]:
    from vibesensor.speed.obd.service import ObdService
    from vibesensor.web.settings.obd import create_obd_admin_routes

    speed_source_service = build_settings_services().speed_source_service
    speed_status_service = create_autospec(SpeedSourceObservationService, instance=True)
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
    obd_admin_service = create_autospec(ObdService, instance=True)
    app = FastAPI()
    app.include_router(
        create_obd_admin_routes(
            speed_source_service=speed_source_service,
            speed_status_service=speed_status_service,
            obd_admin_service=obd_admin_service,
        )
    )
    return (
        TestClient(app),
        speed_source_service,
        speed_status_service,
        obd_admin_service,
    )


def test_scan_obd_devices_endpoint_returns_serialized_devices() -> None:
    client, _, _speed_status_service, obd_admin_service = _build_client()
    obd_admin_service.scan_obd_devices.return_value = [
        ObdDeviceSnapshot(
            mac_address="02000000004d",
            name="OBDLink MX+",
            paired=True,
            trusted=True,
            connected=False,
            rfcomm_channel=1,
        )
    ]

    response = client.post("/api/settings/obd/scan")

    assert response.status_code == 200
    assert response.json()["devices"][0]["mac_address"] == "02000000004d"
    obd_admin_service.scan_obd_devices.assert_called_once_with()


def test_scan_obd_devices_endpoint_returns_structured_runtime_error_detail() -> None:
    client, _, _speed_status_service, obd_admin_service = _build_client()
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
    client, _, _speed_status_service, obd_admin_service = _build_client()
    obd_admin_service.pair_obd_device.side_effect = ExternalCommandError(
        "Bluetooth OBD helper failed"
    )

    response = client.post(
        "/api/settings/obd/pair",
        json={"mac_address": "02:00:00:00:00:4D"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Bluetooth OBD helper failed"}


def test_pair_obd_device_endpoint_normalizes_mac_and_persists_config() -> None:
    (
        client,
        speed_source_service,
        _speed_status_service,
        obd_admin_service,
    ) = _build_client()
    obd_admin_service.pair_obd_device.return_value = ObdDeviceSnapshot(
        mac_address="02000000004d",
        name="OBDLink MX+",
        paired=True,
        trusted=True,
        connected=True,
        rfcomm_channel=1,
    )

    response = client.post(
        "/api/settings/obd/pair",
        json={"mac_address": "02:00:00:00:00:4D"},
    )

    assert response.status_code == 200
    assert response.json()["configured_device_mac"] == "02000000004d"
    obd_admin_service.pair_obd_device.assert_called_once_with("02000000004d")
    saved = speed_source_service.get_speed_source()
    assert saved["obdDeviceMac"] == "02000000004d"
    assert saved["obdDeviceName"] == "OBDLink MX+"


def test_get_obd_status_endpoint_returns_runtime_snapshot() -> None:
    client, _, speed_status_service, obd_admin_service = _build_client()
    speed_status_service.obd_status.return_value = ObdStatusSnapshot(
        configured_device_mac="02000000004d",
        configured_device_name="OBDLink MX+",
        connection_state="connected",
        device_mac="02000000004d",
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
    )

    response = client.get("/api/settings/obd/status")

    assert response.status_code == 200
    body = response.json()
    assert body["configured_device_mac"] == "02000000004d"
    assert body["last_rpm"] == 2100.0
    assert body["rpm_target_interval_ms"] == 75
    assert body["poll_mode"] == "rpm_only_backoff"
    assert body["backoff_active"] is True
    obd_admin_service.refresh_obd_status.assert_called_once_with()
    speed_status_service.obd_status.assert_called_once_with()
