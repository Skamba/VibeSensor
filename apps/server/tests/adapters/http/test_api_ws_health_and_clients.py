from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from _history_endpoint_helpers import (
    FakeWs,
    make_router_and_state,
    response_payload,
    route_endpoint,
    route_endpoint_with_method,
)
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_ws_selected_client_id_validation() -> None:
    router, state = make_router_and_state(language="en")
    endpoint = route_endpoint(router, "/ws")
    ws = FakeWs(
        messages=[
            json.dumps({"client_id": "not-a-mac"}),
            json.dumps({"client_id": "aa:bb:cc:dd:ee:ff"}),
        ],
        selected_query="ZZZZZZZZZZZZ",
    )
    await endpoint(ws)
    assert None in state.ws_hub.selected_updates
    assert "aabbccddeeff" in state.ws_hub.selected_updates


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "messages",
    [
        ['{"client_id":123}'],
        ['{"foo":"bar"}'],
        ["not-json"],
        ['{"client_id":"not-a-mac"}'],
    ],
)
async def test_ws_ignores_invalid_client_selection_messages(messages: list[str]) -> None:
    router, state = make_router_and_state(language="en")
    endpoint = route_endpoint(router, "/ws")
    ws = FakeWs(messages=messages)
    await endpoint(ws)
    assert state.ws_hub.selected_updates == [None]


@pytest.mark.asyncio
async def test_ws_unexpected_update_error_propagates() -> None:
    router, state = make_router_and_state(language="en")
    endpoint = route_endpoint(router, "/ws")
    state.ws_hub.update_selected_client = AsyncMock(side_effect=RuntimeError("boom"))
    ws = FakeWs(messages=[json.dumps({"client_id": "aa:bb:cc:dd:ee:ff"})])

    with pytest.raises(RuntimeError, match="boom"):
        await endpoint(ws)


@pytest.mark.asyncio
async def test_health_ok_status_when_no_failures() -> None:
    router, _ = make_router_and_state()
    endpoint = route_endpoint(router, "/api/health")
    resp = response_payload(await endpoint())
    assert resp["status"] == "ok"
    assert resp["startup_state"] == "ready"


@pytest.mark.asyncio
async def test_health_warn_status_when_processing_failures() -> None:
    router, state = make_router_and_state()
    state.health_state.mark_ready()
    state.processing_loop_state.processing_failure_count = 3
    endpoint = route_endpoint(router, "/api/health")
    resp = response_payload(await endpoint())
    assert resp["status"] == "warn"
    assert resp["processing_failures"] == 3


@pytest.mark.asyncio
async def test_identify_client_404_when_sensor_not_in_registry() -> None:
    from vibesensor.adapters.http.clients import create_client_routes

    registry = type("R", (), {"get": lambda self, cid: None})()
    control_plane = MagicMock()
    settings_store = MagicMock()
    router = create_client_routes(registry, control_plane, settings_store, MagicMock())
    endpoint = route_endpoint_with_method(router, "/api/clients/{client_id}/identify", "POST")

    with pytest.raises(HTTPException) as exc_info:
        await endpoint("aa:bb:cc:dd:ee:ff", type("Req", (), {"duration_ms": 1000})())
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_identify_client_503_when_sensor_known_but_unreachable() -> None:
    from vibesensor.adapters.http.clients import create_client_routes

    sentinel = object()
    registry = type("R", (), {"get": lambda self, cid: sentinel})()
    control_plane = type("C", (), {"send_identify": lambda self, _id, _dur: (False, None)})()
    settings_store = MagicMock()
    router = create_client_routes(registry, control_plane, settings_store, MagicMock())
    endpoint = route_endpoint_with_method(router, "/api/clients/{client_id}/identify", "POST")

    with pytest.raises(HTTPException) as exc_info:
        await endpoint("aa:bb:cc:dd:ee:ff", type("Req", (), {"duration_ms": 1000})())
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_identify_client_200_when_sensor_reachable() -> None:
    from vibesensor.adapters.http.clients import create_client_routes

    sentinel = object()
    registry = type("R", (), {"get": lambda self, cid: sentinel})()
    control_plane = type("C", (), {"send_identify": lambda self, _id, _dur: (True, 7)})()
    settings_store = MagicMock()
    router = create_client_routes(registry, control_plane, settings_store, MagicMock())
    endpoint = route_endpoint_with_method(router, "/api/clients/{client_id}/identify", "POST")

    resp = response_payload(
        await endpoint("aa:bb:cc:dd:ee:ff", type("Req", (), {"duration_ms": 1000})()),
    )
    assert resp == {"status": "sent", "cmd_seq": 7}


@pytest.mark.asyncio
async def test_identify_client_normalizes_client_id_before_registry_and_control_plane() -> None:
    from vibesensor.adapters.http.clients import create_client_routes

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
    router = create_client_routes(registry, control_plane, settings_store, MagicMock())
    endpoint = route_endpoint_with_method(router, "/api/clients/{client_id}/identify", "POST")

    resp = response_payload(
        await endpoint(" AA:BB:CC:DD:EE:FF ", type("Req", (), {"duration_ms": 1000})()),
    )

    assert registry.requested_ids == ["aabbccddeeff"]
    assert control_plane.calls == [("aabbccddeeff", 1000)]
    assert resp == {"status": "sent", "cmd_seq": 7}


@pytest.mark.asyncio
async def test_set_client_location_maps_canonical_location_conflict_to_409() -> None:
    from vibesensor.adapters.http.clients import create_client_routes

    class KnownRegistry:
        def get(self, _client_id: str) -> object:
            return object()

    registry = KnownRegistry()
    control_plane = MagicMock()
    settings_store = MagicMock()
    settings_store.assign_sensor_location.side_effect = ValueError(
        "Location 'front_left_wheel' already assigned to other sensor",
    )
    router = create_client_routes(registry, control_plane, settings_store, MagicMock())
    endpoint = route_endpoint_with_method(router, "/api/clients/{client_id}/location", "POST")

    with pytest.raises(HTTPException) as exc_info:
        request = type("Req", (), {"location_code": "front_left_wheel"})()
        await endpoint("aa:bb:cc:dd:ee:ff", request)
    assert exc_info.value.status_code == 409
    assert "already assigned" in exc_info.value.detail


@pytest.mark.asyncio
async def test_set_client_location_maps_unknown_location_to_400() -> None:
    from vibesensor.adapters.http.clients import create_client_routes

    class KnownRegistry:
        def get(self, _client_id: str) -> object:
            return object()

    registry = KnownRegistry()
    control_plane = MagicMock()
    settings_store = MagicMock()
    settings_store.assign_sensor_location.side_effect = ValueError("Unknown location_code")
    router = create_client_routes(registry, control_plane, settings_store, MagicMock())
    endpoint = route_endpoint_with_method(router, "/api/clients/{client_id}/location", "POST")

    with pytest.raises(HTTPException) as exc_info:
        request = type("Req", (), {"location_code": "not_a_real_location"})()
        await endpoint("aa:bb:cc:dd:ee:ff", request)
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Unknown location_code"


@pytest.mark.asyncio
async def test_set_client_location_persists_canonical_name_and_location() -> None:
    from vibesensor.adapters.http.clients import create_client_routes

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
    router = create_client_routes(registry, control_plane, settings_store, MagicMock())
    endpoint = route_endpoint_with_method(router, "/api/clients/{client_id}/location", "POST")

    request = type("Req", (), {"location_code": "front_left_wheel"})()
    resp = response_payload(await endpoint("aa:bb:cc:dd:ee:ff", request))

    settings_store.assign_sensor_location.assert_called_once_with(
        "aabbccddeeff",
        "front_left_wheel",
    )
    assert registry.locations == [("aabbccddeeff", "front_left_wheel")]
    assert registry.names == [("aabbccddeeff", "Front Left Wheel")]
    assert registry.cleared == []
    assert resp["name"] == "Front Left Wheel"
    assert resp["location_code"] == "front_left_wheel"


@pytest.mark.asyncio
async def test_get_clients_keeps_retained_stale_client_but_marks_it_disconnected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from vibesensor.adapters.http.clients import create_client_routes
    from vibesensor.adapters.persistence.history_db import HistoryDB
    from vibesensor.adapters.udp.protocol import HelloMessage
    from vibesensor.infra.runtime.registry import ClientRegistry

    db = HistoryDB(tmp_path / "history.db")
    registry = ClientRegistry(db=db, live_ttl_seconds=5.0, retention_ttl_seconds=30.0)
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
    router = create_client_routes(registry, control_plane, settings_store, processor)
    endpoint = route_endpoint(router, "/api/clients")

    resp = response_payload(await endpoint())
    assert processor.all_latest_metrics.call_args.args == ([],)
    assert resp["clients"] == [
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


@pytest.mark.asyncio
async def test_get_clients_overlays_canonical_settings_metadata_after_restart(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from test_support.settings_services import build_settings_services

    from vibesensor.adapters.http.clients import create_client_routes
    from vibesensor.adapters.persistence.history_db import HistoryDB
    from vibesensor.adapters.udp.protocol import HelloMessage
    from vibesensor.infra.runtime.registry import ClientRegistry

    db = HistoryDB(tmp_path / "history.db")
    initial_settings = build_settings_services(db=db)
    initial_settings.sensor_settings.assign_sensor_location(
        "00:11:22:33:44:55",
        "rear_left_wheel",
    )

    settings_store = build_settings_services(db=db).sensor_settings
    registry = ClientRegistry(db=db)
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
    router = create_client_routes(registry, control_plane, settings_store, processor)
    endpoint = route_endpoint(router, "/api/clients")

    resp = response_payload(await endpoint())

    assert settings_store.get_sensors()["001122334455"] == {
        "name": "Rear Left Wheel",
        "location_code": "rear_left_wheel",
    }
    assert resp["clients"] == [
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
