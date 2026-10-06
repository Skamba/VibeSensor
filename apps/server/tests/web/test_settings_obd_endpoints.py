from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, create_autospec

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.common.operational_errors import ExternalCommandError
from vibesensor.history.history_db import HistoryDB
from vibesensor.ingest.registry import ClientRegistry
from vibesensor.recording.recorder import RunRecorder
from vibesensor.settings.services import build_settings_services
from vibesensor.settings.speed_source_runtime import SpeedSourceSettingsService
from vibesensor.speed.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot
from vibesensor.speed.source_coordinator import SpeedSourceObservationService
from vibesensor.speed.speed_status import SpeedSourceStatusSnapshot


@dataclass(frozen=True)
class _Harness:
    client: TestClient
    speed_source_service: SpeedSourceSettingsService
    speed_status_service: MagicMock
    obd_admin_service: MagicMock
    registry: MagicMock
    run_recorder: MagicMock


def _build_client(*, recording: bool = False, db: HistoryDB | None = None) -> _Harness:
    from vibesensor.speed.obd.service import ObdService
    from vibesensor.web.settings.obd import create_obd_admin_routes
    from vibesensor.web.settings.speed_source import create_speed_source_routes

    speed_source_service = build_settings_services(db=db).speed_source_service
    speed_status_service = create_autospec(SpeedSourceObservationService, instance=True)
    speed_status_service.status_snapshot.return_value = SpeedSourceStatusSnapshot(
        gps_enabled=True,
        connection_state="connected",
        device="/dev/ttyUSB0",
        fix_wait_s=None,
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
    registry = create_autospec(ClientRegistry, instance=True)
    run_recorder = create_autospec(RunRecorder, instance=True)
    run_recorder.enabled = recording
    app = FastAPI()
    app.include_router(
        create_obd_admin_routes(
            speed_source_service=speed_source_service,
            speed_status_service=speed_status_service,
            obd_admin_service=obd_admin_service,
            registry=registry,
            run_recorder=run_recorder,
        )
    )
    app.include_router(create_speed_source_routes(speed_source_service, speed_status_service))
    return _Harness(
        client=TestClient(app),
        speed_source_service=speed_source_service,
        speed_status_service=speed_status_service,
        obd_admin_service=obd_admin_service,
        registry=registry,
        run_recorder=run_recorder,
    )


def test_scan_obd_devices_endpoint_returns_serialized_devices() -> None:
    harness = _build_client()
    client, obd_admin_service = harness.client, harness.obd_admin_service
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
    harness = _build_client()
    client, obd_admin_service = harness.client, harness.obd_admin_service
    obd_admin_service.scan_obd_devices.side_effect = ExternalCommandError(
        "Privileged helper socket /run/vibesensor-privileged.sock is unavailable"
    )

    response = client.post("/api/settings/obd/scan")

    assert response.status_code == 503
    assert response.json() == {
        "detail": ("Privileged helper socket /run/vibesensor-privileged.sock is unavailable")
    }


def test_pair_obd_device_endpoint_returns_503_for_operational_failure() -> None:
    harness = _build_client()
    client, obd_admin_service = harness.client, harness.obd_admin_service
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
    harness = _build_client()
    client, obd_admin_service = harness.client, harness.obd_admin_service
    speed_source_service = harness.speed_source_service
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
    harness = _build_client()
    client, obd_admin_service = harness.client, harness.obd_admin_service
    speed_status_service = harness.speed_status_service
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


def test_scan_and_pair_are_refused_while_recording() -> None:
    harness = _build_client(recording=True)

    scan = harness.client.post("/api/settings/obd/scan")
    pair = harness.client.post(
        "/api/settings/obd/pair",
        json={"mac_address": "02:00:00:00:00:4D"},
    )

    assert (scan.status_code, pair.status_code) == (409, 409)
    assert "Stop the recording" in scan.json()["detail"]
    assert "Stop the recording" in pair.json()["detail"]
    harness.obd_admin_service.scan_obd_devices.assert_not_called()
    harness.obd_admin_service.pair_obd_device.assert_not_called()
    harness.registry.expecting_frame_loss.assert_not_called()


def test_scan_and_pair_mark_the_sensor_frame_loss_they_cause_as_expected() -> None:
    harness = _build_client()
    harness.obd_admin_service.scan_obd_devices.return_value = []
    harness.obd_admin_service.pair_obd_device.side_effect = ExternalCommandError(
        "Bluetooth OBD helper failed"
    )

    assert harness.client.post("/api/settings/obd/scan").status_code == 200
    pair = harness.client.post(
        "/api/settings/obd/pair",
        json={"mac_address": "02:00:00:00:00:4D"},
    )

    assert pair.status_code == 503
    reasons = [call.args[0] for call in harness.registry.expecting_frame_loss.call_args_list]
    assert reasons == ["bluetooth_scan", "bluetooth_pairing"]
    window = harness.registry.expecting_frame_loss.return_value
    assert window.__exit__.call_count == 2


def test_pairing_makes_the_adapter_the_speed_source_unless_one_was_chosen() -> None:
    harness = _build_client()
    harness.obd_admin_service.pair_obd_device.return_value = ObdDeviceSnapshot(
        mac_address="02000000004d",
        name="OBDLink MX+",
        paired=True,
        trusted=True,
        connected=True,
        rfcomm_channel=1,
    )

    def pair() -> None:
        response = harness.client.post(
            "/api/settings/obd/pair", json={"mac_address": "02:00:00:00:00:4D"}
        )
        assert response.status_code == 200

    pair()
    assert harness.speed_source_service.get_speed_source()["speedSource"] == "obd2"

    harness.speed_source_service.update_speed_source({"speedSource": "gps"})
    pair()
    assert harness.speed_source_service.get_speed_source()["speedSource"] == "gps"


def test_a_chosen_speed_source_survives_a_restart_and_a_later_pairing(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    before_restart = _build_client(db=db)
    chosen = before_restart.client.put("/api/settings/speed-source", json={"speed_source": "gps"})
    assert chosen.status_code == 200

    harness = _build_client(db=db)
    harness.obd_admin_service.pair_obd_device.return_value = ObdDeviceSnapshot(
        mac_address="02000000004d",
        name="OBDLink MX+",
        paired=True,
        trusted=True,
        connected=True,
        rfcomm_channel=1,
    )
    paired = harness.client.post(
        "/api/settings/obd/pair", json={"mac_address": "02:00:00:00:00:4D"}
    )

    assert paired.status_code == 200
    saved = harness.client.get("/api/settings/speed-source").json()
    assert (saved["speed_source"], saved["obd_device_mac"]) == ("gps", "02000000004d")
    after_next_restart = _build_client(db=db).client.get("/api/settings/speed-source").json()
    assert after_next_restart["speed_source"] == "gps"
