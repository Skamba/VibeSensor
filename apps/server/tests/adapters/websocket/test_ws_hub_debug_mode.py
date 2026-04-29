from __future__ import annotations

import pytest

from vibesensor.adapters.websocket.hub import WebSocketHub


@pytest.mark.asyncio
async def test_broadcast_reads_ws_debug_env_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = WebSocketHub()
    capture_debug_values: list[bool] = []

    async def fake_broadcast(payload_builder, *, capture_debug: bool) -> None:
        capture_debug_values.append(capture_debug)
        assert payload_builder(None) == {"ok": True}

    monkeypatch.setattr(hub._runner, "broadcast", fake_broadcast)

    monkeypatch.delenv("VIBESENSOR_WS_DEBUG", raising=False)
    await hub.broadcast(lambda _selected: {"ok": True})

    monkeypatch.setenv("VIBESENSOR_WS_DEBUG", "1")
    await hub.broadcast(lambda _selected: {"ok": True})

    monkeypatch.delenv("VIBESENSOR_WS_DEBUG", raising=False)
    await hub.broadcast(lambda _selected: {"ok": True})

    assert capture_debug_values == [False, True, False]
