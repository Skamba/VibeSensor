"""WebSocket hub selected-client routing behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from test_support.ws_hub import build_hub
from test_support.ws_hub import make_websocket as _make_ws
from test_support.ws_hub import sent_json as _sent_json
from test_support.ws_hub import sent_json_sequence as _sent_json_sequence

from vibesensor.adapters.websocket.hub import WebSocketHub


@pytest.mark.asyncio
async def test_update_selected_client_routes_payload_to_connection() -> None:
    hub, [ws] = await build_hub(None)

    await hub.update_selected_client(ws, "abc123")
    await hub.broadcast(lambda selected: {"selected": selected})

    assert hub.connection_count() == 1
    assert _sent_json_sequence(ws) == [{"selected": "abc123"}]


@pytest.mark.asyncio
async def test_update_selected_client_for_unknown_connection_is_noop() -> None:
    hub = WebSocketHub()

    await hub.update_selected_client(_make_ws(), "abc123")

    assert hub.connection_count() == 0


@pytest.mark.asyncio
async def test_broadcast_passes_selected_client_to_payload_builder() -> None:
    hub, [ws] = await build_hub("client_a")
    payload_builder = MagicMock(return_value={"data": "test"})

    await hub.broadcast(payload_builder)

    payload_builder.assert_called_once_with("client_a")
    assert _sent_json_sequence(ws) == [{"data": "test"}]


@pytest.mark.asyncio
async def test_broadcast_skips_payload_builder_without_connections() -> None:
    hub = WebSocketHub()
    payload_builder = MagicMock(return_value={})

    await hub.broadcast(payload_builder)

    payload_builder.assert_not_called()


@pytest.mark.asyncio
async def test_broadcast_uses_latest_selection_when_selection_changes_during_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = WebSocketHub()
    ws = _make_ws()
    await hub.add(ws, "client_a")
    payload_builder = MagicMock(side_effect=lambda selected: {"selected": selected})
    selection_swapped = False

    async def fake_to_thread(func, /, *args, **kwargs):
        nonlocal selection_swapped
        if not selection_swapped:
            selection_swapped = True
            await hub.update_selected_client(ws, "client_b")
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "vibesensor.adapters.websocket.payload_orchestrator.anyio.to_thread.run_sync",
        fake_to_thread,
    )

    await hub.broadcast(payload_builder)

    assert _sent_json(ws) == {"selected": "client_b"}
    assert [call.args[0] for call in payload_builder.call_args_list] == [
        "client_a",
        "client_b",
    ]


@pytest.mark.asyncio
async def test_broadcast_reuses_payload_when_connections_converge_on_same_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = WebSocketHub()
    ws1 = _make_ws()
    ws2 = _make_ws()
    await hub.add(ws1, "client_a")
    await hub.add(ws2, "client_c")
    payload_builder = MagicMock(side_effect=lambda selected: {"selected": selected})
    selection_swapped = False

    async def fake_to_thread(func, /, *args, **kwargs):
        nonlocal selection_swapped
        if not selection_swapped:
            selection_swapped = True
            await hub.update_selected_client(ws1, "client_b")
            await hub.update_selected_client(ws2, "client_b")
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "vibesensor.adapters.websocket.payload_orchestrator.anyio.to_thread.run_sync",
        fake_to_thread,
    )

    await hub.broadcast(payload_builder)

    assert _sent_json(ws1) == {"selected": "client_b"}
    assert _sent_json(ws2) == {"selected": "client_b"}
    assert [call.args[0] for call in payload_builder.call_args_list] == [
        "client_a",
        "client_c",
        "client_b",
    ]
