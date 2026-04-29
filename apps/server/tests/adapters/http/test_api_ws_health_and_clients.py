from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from _history_endpoint_helpers import make_app_and_state
from fastapi import FastAPI
from fastapi.testclient import TestClient


async def _close_history_db(db) -> None:
    await db.aclose()


def _client_routes_app(registry, control_plane, settings_store, processor) -> FastAPI:
    from vibesensor.adapters.http.clients import create_client_routes

    app = FastAPI()
    app.include_router(create_client_routes(registry, control_plane, settings_store, processor))
    return app


def test_ws_selected_client_id_validation() -> None:
    app, state = make_app_and_state(language="en")

    with TestClient(app) as client:
        with client.websocket_connect("/ws?client_id=ZZZZZZZZZZZZ") as ws:
            ws.send_text(json.dumps({"client_id": "not-a-mac"}))
            ws.send_text(json.dumps({"client_id": "aa:bb:cc:dd:ee:ff"}))

    assert None in state.ws_hub.selected_updates
    assert "aabbccddeeff" in state.ws_hub.selected_updates


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

    assert state.ws_hub.selected_updates == [None]


def test_ws_unexpected_update_error_propagates() -> None:
    app, state = make_app_and_state(language="en")
    state.ws_hub.update_selected_client = AsyncMock(side_effect=RuntimeError("boom"))

    with TestClient(app) as client, pytest.raises(RuntimeError, match="boom"):
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"client_id": "aa:bb:cc:dd:ee:ff"}))


def test_identify_client_404_when_sensor_not_in_registry() -> None:
    registry = type("R", (), {"get": lambda self, cid: None})()
    control_plane = MagicMock()
    settings_store = MagicMock()
    app = _client_routes_app(registry, control_plane, settings_store, MagicMock())

    with TestClient(app) as client:
        response = client.post(
            "/api/clients/aa:bb:cc:dd:ee:ff/identify",
            json={"duration_ms": 1000},
        )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_identify_client_503_when_sensor_known_but_unreachable() -> None:
    sentinel = object()
    registry = type("R", (), {"get": lambda self, cid: sentinel})()
    control_plane = type("C", (), {"send_identify": lambda self, _id, _dur: (False, None)})()
    settings_store = MagicMock()
    app = _client_routes_app(registry, control_plane, settings_store, MagicMock())

    with TestClient(app) as client:
        response = client.post(
            "/api/clients/aa:bb:cc:dd:ee:ff/identify",
            json={"duration_ms": 1000},
        )

    assert response.status_code == 503


def test_identify_client_200_when_sensor_reachable() -> None:
    sentinel = object()
    registry = type("R", (), {"get": lambda self, cid: sentinel})()
    control_plane = type("C", (), {"send_identify": lambda self, _id, _dur: (True, 7)})()
    settings_store = MagicMock()
    app = _client_routes_app(registry, control_plane, settings_store, MagicMock())

    with TestClient(app) as client:
        response = client.post(
            "/api/clients/aa:bb:cc:dd:ee:ff/identify",
            json={"duration_ms": 1000},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "sent", "cmd_seq": 7}


def test_identify_client_normalizes_client_id_before_registry_and_control_plane() -> None:
    class RecordingRegistry:
        def __init__(self) -> None:
            self.requested_ids: list[str] = []

        def get(self, client_id: str) -> object:
            self.requested_ids.append(client_id)
            return object()

    class RecordingControlPlane:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def send_identify(self, client_id: str, duration_ms: int) -> tuple[bool, int]:
            self.calls.append((client_id, duration_ms))
            return True, 7

    registry = RecordingRegistry()
    control_plane = RecordingControlPlane()
    settings_store = MagicMock()
    app = _client_routes_app(registry, control_plane, settings_store, MagicMock())

    with TestClient(app) as client:
        response = client.post(
            "/api/clients/ AA:BB:CC:DD:EE:FF /identify",
            json={"duration_ms": 1000},
        )

    assert response.status_code == 200
    assert registry.requested_ids == ["aabbccddeeff"]
    assert control_plane.calls == [("aabbccddeeff", 1000)]
    assert response.json() == {"status": "sent", "cmd_seq": 7}


def test_set_client_location_maps_canonical_location_conflict_to_409() -> None:
    class KnownRegistry:
        def get(self, _client_id: str) -> object:
            return object()

    registry = KnownRegistry()
    control_plane = MagicMock()
    settings_store = MagicMock()
    settings_store.assign_sensor_location.side_effect = ValueError(
        "Location 'front_left_wheel' already assigned to other sensor",
    )
    app = _client_routes_app(registry, control_plane, settings_store, MagicMock())

    with TestClient(app) as client:
        response = client.post(
            "/api/clients/aa:bb:cc:dd:ee:ff/location",
            json={"location_code": "front_left_wheel"},
        )

    assert response.status_code == 409
    assert "already assigned" in response.json()["detail"]


def test_set_client_location_maps_unknown_location_to_400() -> None:
    class KnownRegistry:
        def get(self, _client_id: str) -> object:
            return object()

    registry = KnownRegistry()
    control_plane = MagicMock()
    settings_store = MagicMock()
    settings_store.assign_sensor_location.side_effect = ValueError("Unknown location_code")
    app = _client_routes_app(registry, control_plane, settings_store, MagicMock())

    with TestClient(app) as client:
        response = client.post(
            "/api/clients/aa:bb:cc:dd:ee:ff/location",
            json={"location_code": "not_a_real_location"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown location_code"


def test_set_client_location_persists_canonical_name_and_location() -> None:
    class KnownRegistry:
        def __init__(self) -> None:
            self.cleared: list[str] = []
            self.locations: list[tuple[str, str]] = []
            self.names: list[tuple[str, str]] = []

        def get(self, _client_id: str):
            return type("Rec", (), {"name": "legacy-name"})()

        def set_location(self, client_id: str, location_code: str):
            self.locations.append((client_id, location_code))
            return type("Rec", (), {"name": "legacy-name", "location_code": location_code})()

        def set_name(self, client_id: str, name: str):
            self.names.append((client_id, name))
            return type("Rec", (), {"name": name, "location_code": "front_left_wheel"})()

        def clear_name(self, client_id: str):
            self.cleared.append(client_id)
            return type("Rec", (), {"name": f"client-{client_id[-4:]}"})()

    registry = KnownRegistry()
    control_plane = MagicMock()
    settings_store = MagicMock()
    settings_store.assign_sensor_location.return_value = {
        "aabbccddeeff": {
            "name": "Front Left Wheel",
            "location_code": "front_left_wheel",
        }
    }
    app = _client_routes_app(registry, control_plane, settings_store, MagicMock())

    with TestClient(app) as client:
        response = client.post(
            "/api/clients/aa:bb:cc:dd:ee:ff/location",
            json={"location_code": "front_left_wheel"},
        )

    assert response.status_code == 200
    settings_store.assign_sensor_location.assert_called_once_with(
        "aabbccddeeff",
        "front_left_wheel",
    )
    assert registry.locations == [("aabbccddeeff", "front_left_wheel")]
    assert registry.names == [("aabbccddeeff", "Front Left Wheel")]
    assert registry.cleared == []
    assert response.json()["name"] == "Front Left Wheel"
    assert response.json()["location_code"] == "front_left_wheel"


def test_set_client_location_works_with_real_persistence_in_async_route(
    tmp_path: Path,
) -> None:
    from test_support.settings_services import build_settings_services

    from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
    from vibesensor.adapters.udp.protocol import HelloMessage
    from vibesensor.infra.runtime.registry import ClientRegistry

    db = create_history_persistence_adapters(tmp_path / "history.db")
    try:
        settings_store = build_settings_services(db=db.settings_snapshot_repository).sensor_settings
        registry = ClientRegistry(db=db.client_name_repository)
        registry.update_from_hello(
            HelloMessage(
                client_id=bytes.fromhex("001122334455"),
                control_port=9010,
                sample_rate_hz=800,
                name="advertised-name",
                firmware_version="fw",
            ),
            ("10.4.0.2", 9010),
            1.0,
            now_mono=1.0,
        )

        app = _client_routes_app(registry, MagicMock(), settings_store, MagicMock())

        with TestClient(app) as client:
            response = client.post(
                "/api/clients/00:11:22:33:44:55/location",
                json={"location_code": "front_left_wheel"},
            )

        assert response.status_code == 200
        assert response.json()["name"] == "Front Left Wheel"
        assert response.json()["location_code"] == "front_left_wheel"
        assert settings_store.get_sensors() == {
            "001122334455": {
                "name": "Front Left Wheel",
                "location_code": "front_left_wheel",
            }
        }
    finally:
        asyncio.run(_close_history_db(db))


def test_remove_client_clears_persisted_name_from_async_route(tmp_path: Path) -> None:
    from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
    from vibesensor.adapters.udp.protocol import HelloMessage
    from vibesensor.infra.runtime.registry import ClientRegistry

    db = create_history_persistence_adapters(tmp_path / "history.db")
    try:
        registry = ClientRegistry(db=db.client_name_repository)
        registry.update_from_hello(
            HelloMessage(
                client_id=bytes.fromhex("001122334455"),
                control_port=9010,
                sample_rate_hz=800,
                name="advertised-name",
                firmware_version="fw",
            ),
            ("10.4.0.2", 9010),
            1.0,
            now_mono=1.0,
        )
        registry.set_name("001122334455", "Front Left Wheel")

        app = _client_routes_app(registry, MagicMock(), MagicMock(), MagicMock())

        with TestClient(app) as client:
            response = client.delete("/api/clients/00:11:22:33:44:55")

        assert response.status_code == 200
        assert response.json() == {"id": "001122334455", "status": "removed"}
        assert db.client_name_repository.list_client_names() == {}
    finally:
        asyncio.run(_close_history_db(db))


def test_get_clients_keeps_retained_stale_client_but_marks_it_disconnected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
    from vibesensor.adapters.udp.protocol import HelloMessage
    from vibesensor.infra.runtime.registry import ClientRegistry

    db = create_history_persistence_adapters(tmp_path / "history.db")
    try:
        registry = ClientRegistry(
            db=db.client_name_repository,
            live_ttl_seconds=5.0,
            retention_ttl_seconds=30.0,
        )
        hello = HelloMessage(
            client_id=bytes.fromhex("001122334455"),
            control_port=9010,
            sample_rate_hz=800,
            name="sensor",
            firmware_version="fw",
        )
        registry.update_from_hello(hello, ("10.4.0.2", 9010), now=1.0, now_mono=1.0)

        now = {"wall": 9.0, "mono": 9.0}
        monkeypatch.setattr("vibesensor.infra.runtime.registry.time.time", lambda: now["wall"])
        monkeypatch.setattr("vibesensor.infra.runtime.registry.time.monotonic", lambda: now["mono"])

        control_plane = MagicMock()
        settings_store = MagicMock()
        settings_store.get_sensors.return_value = {}
        processor = MagicMock()
        processor.all_latest_metrics.return_value = {}
        app = _client_routes_app(registry, control_plane, settings_store, processor)

        with TestClient(app) as client:
            response = client.get("/api/clients")

        assert response.status_code == 200
        assert processor.all_latest_metrics.call_args.args == ([],)
        assert response.json()["clients"] == [
            {
                "id": "001122334455",
                "mac_address": "00:11:22:33:44:55",
                "name": "sensor",
                "connected": False,
                "location_code": "",
                "firmware_version": "fw",
                "sample_rate_hz": 800,
                "frame_samples": 0,
                "last_seen_age_ms": 8000,
                "frames_total": 0,
                "dropped_frames": 0,
                "latest_metrics": {},
                "reset_count": 0,
                "last_reset_time": None,
            },
        ]
    finally:
        asyncio.run(_close_history_db(db))


def test_get_clients_overlays_canonical_settings_metadata_after_restart(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from test_support.settings_services import build_settings_services

    from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
    from vibesensor.adapters.udp.protocol import HelloMessage
    from vibesensor.infra.runtime.registry import ClientRegistry

    db = create_history_persistence_adapters(tmp_path / "history.db")
    try:
        initial_settings = build_settings_services(db=db.settings_snapshot_repository)
        initial_settings.sensor_settings.assign_sensor_location(
            "00:11:22:33:44:55",
            "rear_left_wheel",
        )

        settings_store = build_settings_services(db=db.settings_snapshot_repository).sensor_settings
        registry = ClientRegistry(db=db.client_name_repository)
        registry.update_from_hello(
            HelloMessage(
                client_id=bytes.fromhex("001122334455"),
                control_port=9010,
                sample_rate_hz=800,
                name="advertised-name",
                firmware_version="fw",
            ),
            ("10.4.0.2", 9010),
            now=1.0,
            now_mono=1.0,
        )
        monkeypatch.setattr("vibesensor.infra.runtime.registry.time.time", lambda: 1.0)
        monkeypatch.setattr("vibesensor.infra.runtime.registry.time.monotonic", lambda: 1.0)

        control_plane = MagicMock()
        processor = MagicMock()
        processor.all_latest_metrics.return_value = {}
        app = _client_routes_app(registry, control_plane, settings_store, processor)

        with TestClient(app) as client:
            response = client.get("/api/clients")

        assert response.status_code == 200
        assert settings_store.get_sensors()["001122334455"] == {
            "name": "Rear Left Wheel",
            "location_code": "rear_left_wheel",
        }
        assert response.json()["clients"] == [
            {
                "id": "001122334455",
                "mac_address": "00:11:22:33:44:55",
                "name": "Rear Left Wheel",
                "connected": True,
                "location_code": "rear_left_wheel",
                "firmware_version": "fw",
                "sample_rate_hz": 800,
                "frame_samples": 0,
                "last_seen_age_ms": 0,
                "frames_total": 0,
                "dropped_frames": 0,
                "latest_metrics": {},
                "reset_count": 0,
                "last_reset_time": None,
            },
        ]
    finally:
        asyncio.run(_close_history_db(db))
