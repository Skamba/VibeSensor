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
from vibesensor.live.processor import SignalProcessor
from vibesensor.settings.sensor_settings import SensorSettingsService
from vibesensor.settings.services import build_settings_services


def _client_routes_app(registry, control_plane, settings_store, processor) -> FastAPI:
    from vibesensor.web.clients import create_client_routes

    app = FastAPI()
    app.include_router(create_client_routes(registry, control_plane, settings_store, processor))
    return app


def _hello(client_hex: str, name: str = "advertised-name") -> HelloMessage:
    return HelloMessage(
        client_id=bytes.fromhex(client_hex),
        control_port=9010,
        sample_rate_hz=800,
        name=name,
        firmware_version="fw",
    )


@dataclass
class _ClientRig:
    db: HistoryDB
    registry: ClientRegistry
    settings: SensorSettingsService
    control_plane: UDPControlPlane
    processor: SignalProcessor

    def app(self) -> FastAPI:
        return _client_routes_app(self.registry, self.control_plane, self.settings, self.processor)


@pytest.fixture
def client_rig(tmp_path: Path):
    """Real registry, sensor settings and HistoryDB; spec'd control plane and processor."""
    db = HistoryDB(tmp_path / "history.db")
    processor = create_autospec(SignalProcessor, instance=True)
    processor.all_latest_metrics.return_value = {}
    rig = _ClientRig(
        db=db,
        registry=ClientRegistry(db=db),
        settings=build_settings_services(db=db).sensor_settings,
        control_plane=create_autospec(UDPControlPlane, instance=True),
        processor=processor,
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
        processor = create_autospec(SignalProcessor, instance=True)
        processor.all_latest_metrics.return_value = {}
        app = _client_routes_app(
            registry,
            create_autospec(UDPControlPlane, instance=True),
            build_settings_services(db=db).sensor_settings,
            processor,
        )

        with TestClient(app) as client:
            response = client.get("/api/clients")

        assert response.status_code == 200
        processor.all_latest_metrics.assert_called_once_with([])
        clients = response.json()["clients"]
        assert len(clients) == 1
        assert clients[0]["id"] == "001122334455"
        assert clients[0]["name"] == "sensor"
        assert clients[0]["connected"] is False
        assert clients[0]["last_seen_age_ms"] == 8000
        assert clients[0]["latest_metrics"] == {}
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
        processor = create_autospec(SignalProcessor, instance=True)
        processor.all_latest_metrics.return_value = {}
        app = _client_routes_app(
            registry, create_autospec(UDPControlPlane, instance=True), settings_store, processor
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
        assert clients[0]["latest_metrics"] == {}
    finally:
        db.close()
