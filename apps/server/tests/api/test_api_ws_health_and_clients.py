from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from _history_endpoint_helpers import (
    FakeWs,
    make_router_and_state,
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
async def test_health_ok_status_when_no_failures() -> None:
    router, _ = make_router_and_state()
    endpoint = route_endpoint(router, "/api/health")
    resp = await endpoint()
    assert resp["status"] == "ok"
    assert resp["startup_state"] == "ready"


@pytest.mark.asyncio
async def test_health_degraded_status_when_processing_failures() -> None:
    router, state = make_router_and_state()
    state.health_state.mark_ready()
    state.loop_state.processing_failure_count = 3
    endpoint = route_endpoint(router, "/api/health")
    resp = await endpoint()
    assert resp["status"] == "degraded"
    assert resp["processing_failures"] == 3


@pytest.mark.asyncio
async def test_identify_client_404_when_sensor_not_in_registry() -> None:
    from vibesensor.routes.clients import create_client_routes

    registry = type("R", (), {"get": lambda self, cid: None})()
    control_plane = MagicMock()
    settings_store = MagicMock()
    router = create_client_routes(registry, control_plane, settings_store)
    endpoint = route_endpoint_with_method(router, "/api/clients/{client_id}/identify", "POST")

    with pytest.raises(HTTPException) as exc_info:
        await endpoint("aa:bb:cc:dd:ee:ff", type("Req", (), {"duration_ms": 1000})())
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_identify_client_503_when_sensor_known_but_unreachable() -> None:
    from vibesensor.routes.clients import create_client_routes

    sentinel = object()
    registry = type("R", (), {"get": lambda self, cid: sentinel})()
    control_plane = type("C", (), {"send_identify": lambda self, _id, _dur: (False, None)})()
    settings_store = MagicMock()
    router = create_client_routes(registry, control_plane, settings_store)
    endpoint = route_endpoint_with_method(router, "/api/clients/{client_id}/identify", "POST")

    with pytest.raises(HTTPException) as exc_info:
        await endpoint("aa:bb:cc:dd:ee:ff", type("Req", (), {"duration_ms": 1000})())
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_identify_client_200_when_sensor_reachable() -> None:
    from vibesensor.routes.clients import create_client_routes

    sentinel = object()
    registry = type("R", (), {"get": lambda self, cid: sentinel})()
    control_plane = type("C", (), {"send_identify": lambda self, _id, _dur: (True, 7)})()
    settings_store = MagicMock()
    router = create_client_routes(registry, control_plane, settings_store)
    endpoint = route_endpoint_with_method(router, "/api/clients/{client_id}/identify", "POST")

    resp = await endpoint("aa:bb:cc:dd:ee:ff", type("Req", (), {"duration_ms": 1000})())
    assert resp == {"status": "sent", "cmd_seq": 7}
