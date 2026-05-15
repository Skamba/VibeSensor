"""HTTP client tests for update and ESP flash endpoints."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.adapters.http.updates import create_update_routes
from vibesensor.shared.exceptions import ConfigurationError, UpdateError
from vibesensor.use_cases.updates.firmware.esp_flash_types import (
    EspFlashHistoryEntry,
    EspFlashState,
    EspFlashStatus,
    SerialPortInfo,
)
from vibesensor.use_cases.updates.models import (
    UpdateIssue,
    UpdateJobStatus,
    UpdatePhase,
    UpdateRuntimeDetails,
    UpdateState,
    UpdateTransport,
    UsbInternetStatus,
)


def _make_update_status(
    *,
    state: UpdateState = UpdateState.idle,
    phase: UpdatePhase = UpdatePhase.idle,
    transport: UpdateTransport = UpdateTransport.wifi,
    ssid: str | None = None,
    uplink_interface: str | None = None,
) -> UpdateJobStatus:
    return UpdateJobStatus(
        state=state,
        phase=phase,
        transport=transport,
        started_at=10.0 if state != UpdateState.idle else None,
        phase_started_at=12.0 if state == UpdateState.running else None,
        updated_at=15.0,
        ssid=ssid,
        uplink_interface=uplink_interface,
        issues=[UpdateIssue(phase="restore", message="warning", detail="detail")],
        log_tail=["line-1", "line-2"],
        runtime=UpdateRuntimeDetails(
            version="1.2.3",
            commit="deadbeef",
            ui_source_hash="ui-hash",
            static_assets_hash="assets-hash",
            static_build_source_hash="build-hash",
            static_build_commit="build-commit",
            assets_verified=True,
            has_packaged_static=True,
        ),
    )


@pytest.fixture
def update_client(fake_state):
    app = FastAPI()
    app.include_router(
        create_update_routes(fake_state.update_manager, fake_state.esp_flash_manager)
    )
    with TestClient(app) as client:
        yield client, fake_state


def test_get_update_status_returns_serialized_status(update_client) -> None:
    client, state = update_client
    state.update_manager.status = _make_update_status(
        state=UpdateState.running,
        phase=UpdatePhase.checking,
        ssid="GarageNet",
    )

    response = client.get("/api/update/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "running"
    assert payload["phase"] == "checking"
    assert payload["transport"] == "wifi"
    assert payload["ssid"] == "GarageNet"
    assert payload["runtime"]["assets_verified"] is True
    assert payload["issues"][0]["phase"] == "restore"


def test_get_update_internet_status_returns_serialized_snapshot(update_client) -> None:
    client, state = update_client
    state.update_manager.get_usb_internet_status.return_value = UsbInternetStatus(
        detected=True,
        usable=True,
        interface_name="usb0",
        connection_name="iPhone USB",
        driver="ipheth",
        ipv4_addresses=("172.20.10.2/28",),
        gateway="172.20.10.1",
        has_default_route=True,
        diagnostic="USB internet is ready on 'usb0'.",
    )

    response = client.get("/api/update/internet-status")

    assert response.status_code == 200
    assert response.json() == {
        "detected": True,
        "usable": True,
        "interface_name": "usb0",
        "connection_name": "iPhone USB",
        "driver": "ipheth",
        "ipv4_addresses": ["172.20.10.2/28"],
        "gateway": "172.20.10.1",
        "has_default_route": True,
        "diagnostic": "USB internet is ready on 'usb0'.",
    }


def test_start_update_returns_started_response(update_client) -> None:
    client, state = update_client

    response = client.post(
        "/api/update/start",
        json={
            "transport": "wifi",
            "ssid": "GarageNet",
            "password": "secret123",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "started",
        "transport": "wifi",
        "ssid": "GarageNet",
    }
    state.update_manager.start.assert_called_once_with(
        ssid="GarageNet",
        password="secret123",
        transport=UpdateTransport.wifi,
    )


def test_start_update_with_usb_internet_returns_started_response(update_client) -> None:
    client, state = update_client

    response = client.post("/api/update/start", json={"transport": "usb_internet"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "started",
        "transport": "usb_internet",
        "ssid": None,
    }
    state.update_manager.start.assert_called_once_with(
        ssid=None,
        password="",
        transport=UpdateTransport.usb_internet,
    )


def test_start_update_maps_configuration_error_to_400(update_client) -> None:
    client, state = update_client
    state.update_manager.start.side_effect = ConfigurationError("SSID must be 1-64 characters")

    response = client.post(
        "/api/update/start",
        json={"transport": "wifi", "ssid": "x", "password": ""},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "SSID must be 1-64 characters"


def test_start_update_maps_update_conflict_to_409(update_client) -> None:
    client, state = update_client
    state.update_manager.start.side_effect = UpdateError(
        "Update already in progress",
        status="conflict",
    )

    response = client.post(
        "/api/update/start",
        json={"transport": "wifi", "ssid": "GarageNet", "password": ""},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Update already in progress"


def test_cancel_update_returns_cancelled_flag(update_client) -> None:
    client, state = update_client
    state.update_manager.cancel.return_value = True

    response = client.post("/api/update/cancel")

    assert response.status_code == 200
    assert response.json() == {"cancelled": True}
    state.update_manager.cancel.assert_called_once_with()


def test_list_esp_flash_ports_returns_detected_ports(update_client) -> None:
    client, state = update_client
    state.esp_flash_manager.list_ports.return_value = [
        SerialPortInfo(
            port="/dev/ttyUSB0",
            description="USB Serial",
            vid=0x10C4,
            pid=0xEA60,
            serial_number="abc123",
        ).to_dict()
    ]

    response = client.get("/api/esp-flash/ports")

    assert response.status_code == 200
    assert response.json()["ports"] == [
        {
            "port": "/dev/ttyUSB0",
            "description": "USB Serial",
            "vid": 4292,
            "pid": 60000,
            "serial_number": "abc123",
        }
    ]


def test_start_esp_flash_returns_started_response(update_client) -> None:
    client, state = update_client
    state.esp_flash_manager.start.return_value = 7

    response = client.post(
        "/api/esp-flash/start",
        json={"port": "/dev/ttyUSB0", "auto_detect": False},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "started", "job_id": 7}
    state.esp_flash_manager.start.assert_called_once_with(
        port="/dev/ttyUSB0",
        auto_detect=False,
    )


def test_start_esp_flash_rejects_missing_port_when_auto_detect_disabled(update_client) -> None:
    client, _state = update_client

    response = client.post("/api/esp-flash/start", json={"auto_detect": False})

    assert response.status_code == 422
    assert "port is required when auto_detect is False" in str(response.json())


def test_start_esp_flash_maps_configuration_error_to_400(update_client) -> None:
    client, state = update_client
    state.esp_flash_manager.start.side_effect = ConfigurationError(
        "port is required when auto_detect is False"
    )

    response = client.post("/api/esp-flash/start", json={"port": None, "auto_detect": True})

    assert response.status_code == 400
    assert response.json()["detail"] == "port is required when auto_detect is False"


def test_start_esp_flash_maps_update_conflict_to_409(update_client) -> None:
    client, state = update_client
    state.esp_flash_manager.start.side_effect = UpdateError(
        "Flash already in progress",
        status="conflict",
    )

    response = client.post("/api/esp-flash/start", json={"port": None, "auto_detect": True})

    assert response.status_code == 409
    assert response.json()["detail"] == "Flash already in progress"


def test_get_esp_flash_status_returns_serialized_status(update_client) -> None:
    client, state = update_client
    state.esp_flash_manager.status = EspFlashStatus(
        state=EspFlashState.running,
        phase="flashing",
        job_id=3,
        selected_port="/dev/ttyUSB0",
        auto_detect=False,
        started_at=10.0,
        last_success_at=5.0,
        log_count=12,
    )

    response = client.get("/api/esp-flash/status")

    assert response.status_code == 200
    assert response.json() == {
        "state": "running",
        "phase": "flashing",
        "job_id": 3,
        "selected_port": "/dev/ttyUSB0",
        "auto_detect": False,
        "started_at": 10.0,
        "finished_at": None,
        "last_success_at": 5.0,
        "exit_code": None,
        "error": None,
        "log_count": 12,
    }


def test_get_esp_flash_logs_uses_after_query_param(update_client) -> None:
    client, state = update_client
    state.esp_flash_manager.logs_since.return_value = {
        "from_index": 4,
        "next_index": 6,
        "lines": ["line 5", "line 6"],
    }

    response = client.get("/api/esp-flash/logs", params={"after": 4})

    assert response.status_code == 200
    assert response.json() == {
        "from_index": 4,
        "next_index": 6,
        "lines": ["line 5", "line 6"],
    }
    state.esp_flash_manager.logs_since.assert_called_once_with(4)


def test_cancel_esp_flash_returns_cancelled_flag(update_client) -> None:
    client, state = update_client
    state.esp_flash_manager.cancel.return_value = True

    response = client.post("/api/esp-flash/cancel")

    assert response.status_code == 200
    assert response.json() == {"cancelled": True}
    state.esp_flash_manager.cancel.assert_called_once_with()


def test_get_esp_flash_history_returns_attempts(update_client) -> None:
    client, state = update_client
    state.esp_flash_manager.history.return_value = [
        EspFlashHistoryEntry(
            job_id=5,
            state=EspFlashState.success,
            selected_port="/dev/ttyUSB0",
            auto_detect=False,
            started_at=10.0,
            finished_at=20.0,
            exit_code=0,
            error=None,
        ).to_dict()
    ]

    response = client.get("/api/esp-flash/history")

    assert response.status_code == 200
    assert response.json() == {
        "attempts": [
            {
                "job_id": 5,
                "state": "success",
                "selected_port": "/dev/ttyUSB0",
                "auto_detect": False,
                "started_at": 10.0,
                "finished_at": 20.0,
                "exit_code": 0,
                "error": None,
            }
        ]
    }
