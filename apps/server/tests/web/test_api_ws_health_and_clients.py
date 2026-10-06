from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, create_autospec

import pytest
from _history_endpoint_helpers import make_app_and_state
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.history.history_db import HistoryDB
from vibesensor.ingest.protocol_messages import HelloMessage
from vibesensor.ingest.registry import ClientRegistry
from vibesensor.ingest.udp_control_tx import UDPControlPlane
from vibesensor.settings.sensor_settings import SensorSettingsService
from vibesensor.settings.services import build_settings_services
from vibesensor.updates.firmware.esp_flash_manager import EspFlashManager


def _client_routes_app(
    registry, control_plane, settings_store, bundled_firmware_version: str = ""
) -> FastAPI:
    from vibesensor.web.clients import create_client_routes

    esp_flash_manager = create_autospec(EspFlashManager, instance=True, spec_set=True)
    esp_flash_manager.bundled_firmware_version.return_value = bundled_firmware_version
    app = FastAPI()
    app.include_router(
        create_client_routes(registry, control_plane, settings_store, esp_flash_manager)
    )
    return app


def _hello(
    client_hex: str, name: str = "advertised-name", firmware_version: str = "fw"
) -> HelloMessage:
    return HelloMessage(
        client_id=bytes.fromhex(client_hex),
        control_port=9010,
        sample_rate_hz=800,
        name=name,
        firmware_version=firmware_version,
    )


@dataclass
class _ClientRig:
    db: HistoryDB
    registry: ClientRegistry
    settings: SensorSettingsService
    control_plane: UDPControlPlane

    def app(self, bundled_firmware_version: str = "") -> FastAPI:
        return _client_routes_app(
            self.registry,
            self.control_plane,
            self.settings,
            bundled_firmware_version,
        )


@pytest.fixture
def client_rig(tmp_path: Path):
    """Real registry, sensor settings and HistoryDB; spec'd control plane."""
    db = HistoryDB(tmp_path / "history.db")
    rig = _ClientRig(
        db=db,
        registry=ClientRegistry(db=db),
        settings=build_settings_services(db=db).sensor_settings,
        control_plane=create_autospec(UDPControlPlane, instance=True),
    )
    yield rig
    db.close()


def test_ws_selected_client_id_validation() -> None:
    app, state = make_app_and_state(language="en")

    with TestClient(app) as client:
        with client.websocket_connect("/ws?client_id=ZZZZZZZZZZZZ") as ws:
            ws.send_text(json.dumps({"client_id": "not-a-mac"}))
            ws.send_text(json.dumps({"client_id": "aa:bb:cc:dd:ee:ff"}))

    assert None in state.ws_broadcaster.selected_updates
    assert "aabbccddeeff" in state.ws_broadcaster.selected_updates


@pytest.mark.parametrize(
    "messages",
    [
        ['{"client_id":123}'],
        ['{"foo":"bar"}'],
        ["not-json"],
        ['{"client_id":"not-a-mac"}'],
    ],
)
def test_ws_ignores_invalid_client_selection_messages(messages: list[str]) -> None:
    app, state = make_app_and_state(language="en")

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            for message in messages:
                ws.send_text(message)

    assert state.ws_broadcaster.selected_updates == [None]


def test_ws_unexpected_update_error_propagates() -> None:
    app, state = make_app_and_state(language="en")
    state.ws_broadcaster.select = MagicMock(side_effect=RuntimeError("boom"))

    with TestClient(app) as client, pytest.raises(RuntimeError, match="boom"):
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"client_id": "aa:bb:cc:dd:ee:ff"}))


@pytest.mark.parametrize(
    ("known", "send_result", "status_code", "expected_json"),
    [
        pytest.param(False, None, 404, None, id="unknown-sensor-404"),
        pytest.param(True, (False, None), 503, None, id="known-but-unreachable-503"),
        pytest.param(
            True, (True, 7), 200, {"status": "sent", "cmd_seq": 7}, id="reachable-sends-200"
        ),
    ],
)
def test_identify_client_status(
    client_rig: _ClientRig,
    known: bool,
    send_result: tuple[bool, int | None] | None,
    status_code: int,
    expected_json: dict[str, object] | None,
) -> None:
    if known:
        client_rig.registry.update_from_hello(
            _hello("aabbccddeeff"), ("10.4.0.2", 9010), 1.0, now_mono=1.0
        )
    client_rig.control_plane.send_identify.return_value = send_result

    with TestClient(client_rig.app()) as client:
        response = client.post(
            "/api/clients/ AA:BB:CC:DD:EE:FF /identify",
            json={"duration_ms": 1000},
        )

    assert response.status_code == status_code
    if status_code == 404:
        assert "not found" in response.json()["detail"].lower()
        client_rig.control_plane.send_identify.assert_not_called()
    else:
        client_rig.control_plane.send_identify.assert_called_once_with("aabbccddeeff", 1000)
    if expected_json is not None:
        assert response.json() == expected_json


@pytest.mark.parametrize("duration_ms", [99, 60_001])
def test_identify_rejects_durations_outside_100ms_to_60s(
    client_rig: _ClientRig, duration_ms: int
) -> None:
    with TestClient(client_rig.app()) as client:
        response = client.post(
            "/api/clients/aa:bb:cc:dd:ee:ff/identify", json={"duration_ms": duration_ms}
        )

    assert response.status_code == 422


def test_set_client_location_persists_canonical_name_and_location(client_rig: _ClientRig) -> None:
    client_rig.registry.update_from_hello(
        _hello("001122334455"), ("10.4.0.2", 9010), 1.0, now_mono=1.0
    )

    with TestClient(client_rig.app()) as client:
        response = client.post(
            "/api/clients/00:11:22:33:44:55/location",
            json={"location_code": "front_left_wheel"},
        )

    assert response.status_code == 200
    assert response.json()["name"] == "Front Left Wheel"
    assert response.json()["location_code"] == "front_left_wheel"
    assert client_rig.settings.get_sensors() == {
        "001122334455": {"name": "Front Left Wheel", "location_code": "front_left_wheel"}
    }
    record = client_rig.registry.get("001122334455")
    assert record is not None
    assert (record.name, record.location_code) == ("Front Left Wheel", "front_left_wheel")


def test_set_client_location_maps_location_conflict_to_409(client_rig: _ClientRig) -> None:
    for client_hex in ("001122334455", "001122334466"):
        client_rig.registry.update_from_hello(
            _hello(client_hex), ("10.4.0.2", 9010), 1.0, now_mono=1.0
        )

    with TestClient(client_rig.app()) as client:
        first = client.post(
            "/api/clients/00:11:22:33:44:55/location", json={"location_code": "front_left_wheel"}
        )
        conflict = client.post(
            "/api/clients/00:11:22:33:44:66/location", json={"location_code": "front_left_wheel"}
        )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert "already assigned" in conflict.json()["detail"]


def test_set_client_location_maps_unknown_location_to_400(client_rig: _ClientRig) -> None:
    client_rig.registry.update_from_hello(
        _hello("001122334455"), ("10.4.0.2", 9010), 1.0, now_mono=1.0
    )

    with TestClient(client_rig.app()) as client:
        response = client.post(
            "/api/clients/00:11:22:33:44:55/location",
            json={"location_code": "not_a_real_location"},
        )

    assert response.status_code == 400
    assert "location_code" in response.json()["detail"]


def test_remove_client_clears_persisted_name(client_rig: _ClientRig) -> None:
    client_rig.registry.update_from_hello(
        _hello("001122334455"), ("10.4.0.2", 9010), 1.0, now_mono=1.0
    )
    client_rig.registry.set_name("001122334455", "Front Left Wheel")

    with TestClient(client_rig.app()) as client:
        response = client.delete("/api/clients/00:11:22:33:44:55")

    assert response.status_code == 200
    assert response.json() == {"id": "001122334455", "status": "removed"}
    assert client_rig.db.list_client_names() == {}


def test_remove_client_releases_location_for_replacement_sensor(client_rig: _ClientRig) -> None:
    for client_hex in ("001122334455", "001122334466"):
        client_rig.registry.update_from_hello(
            _hello(client_hex), ("10.4.0.2", 9010), 1.0, now_mono=1.0
        )

    with TestClient(client_rig.app()) as client:
        assigned = client.post(
            "/api/clients/00:11:22:33:44:55/location", json={"location_code": "front_left_wheel"}
        )
        removed = client.delete("/api/clients/00:11:22:33:44:55")
        replacement = client.post(
            "/api/clients/00:11:22:33:44:66/location", json={"location_code": "front_left_wheel"}
        )

    assert (assigned.status_code, removed.status_code, replacement.status_code) == (200, 200, 200)
    sensors = client_rig.settings.get_sensors()
    assert sensors["001122334455"]["location_code"] == ""
    assert sensors["001122334466"]["location_code"] == "front_left_wheel"


def test_get_clients_keeps_retained_stale_client_but_marks_it_disconnected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db = HistoryDB(tmp_path / "history.db")
    try:
        registry = ClientRegistry(db=db, live_ttl_seconds=5.0, retention_ttl_seconds=30.0)
        registry.update_from_hello(
            _hello("001122334455", name="sensor"), ("10.4.0.2", 9010), now=1.0, now_mono=1.0
        )
        monkeypatch.setattr("vibesensor.ingest.registry.time.time", lambda: 9.0)
        monkeypatch.setattr("vibesensor.ingest.registry.time.monotonic", lambda: 9.0)
        app = _client_routes_app(
            registry,
            create_autospec(UDPControlPlane, instance=True),
            build_settings_services(db=db).sensor_settings,
        )

        with TestClient(app) as client:
            response = client.get("/api/clients")

        assert response.status_code == 200
        clients = response.json()["clients"]
        assert len(clients) == 1
        assert clients[0]["id"] == "001122334455"
        assert clients[0]["name"] == "sensor"
        assert clients[0]["connected"] is False
        assert clients[0]["last_seen_age_ms"] == 8000
    finally:
        db.close()


def test_get_clients_overlays_canonical_settings_metadata_after_restart(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db = HistoryDB(tmp_path / "history.db")
    try:
        build_settings_services(db=db).sensor_settings.assign_sensor_location(
            "00:11:22:33:44:55", "rear_left_wheel"
        )
        settings_store = build_settings_services(db=db).sensor_settings
        registry = ClientRegistry(db=db)
        registry.update_from_hello(
            _hello("001122334455"), ("10.4.0.2", 9010), now=1.0, now_mono=1.0
        )
        monkeypatch.setattr("vibesensor.ingest.registry.time.time", lambda: 1.0)
        monkeypatch.setattr("vibesensor.ingest.registry.time.monotonic", lambda: 1.0)
        app = _client_routes_app(
            registry, create_autospec(UDPControlPlane, instance=True), settings_store
        )

        with TestClient(app) as client:
            response = client.get("/api/clients")

        assert response.status_code == 200
        clients = response.json()["clients"]
        assert len(clients) == 1
        assert clients[0]["id"] == "001122334455"
        assert clients[0]["name"] == "Rear Left Wheel"
        assert clients[0]["connected"] is True
        assert clients[0]["location_code"] == "rear_left_wheel"
    finally:
        db.close()


def test_get_clients_compares_each_sensor_firmware_with_the_bundled_build(
    client_rig: _ClientRig,
) -> None:
    bundled = "fw-20261005.1200+0123456789ab"
    for client_hex, firmware_version in (
        ("001122334455", bundled),
        ("001122334466", "esp32-atom-0.1"),  # firmware from before version stamping
        ("001122334477", "fw-20261006.0900+fedcba987654"),  # newer than the bundle
    ):
        client_rig.registry.update_from_hello(
            _hello(client_hex, firmware_version=firmware_version),
            ("10.4.0.2", 9010),
            now=1.0,
            now_mono=1.0,
        )

    with TestClient(client_rig.app(bundled)) as client:
        rows = client.get("/api/clients").json()["clients"]

    assert {row["id"]: (row["firmware_version"], row["firmware_status"]) for row in rows} == {
        "001122334455": (bundled, "current"),
        "001122334466": ("esp32-atom-0.1", "outdated"),
        "001122334477": ("fw-20261006.0900+fedcba987654", "unknown"),
    }
