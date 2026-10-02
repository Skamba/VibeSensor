"""Shared builders for live WebSocket broadcaster tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from vibesensor.ingest.diagnostics import IngestDiagnosticsCollector
from vibesensor.live.broadcaster import LiveBroadcaster


def make_websocket() -> AsyncMock:
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


def sent_json(ws: AsyncMock) -> dict[str, object]:
    return json.loads(ws.send_text.call_args[0][0])


def sent_json_sequence(ws: AsyncMock) -> list[dict[str, object]]:
    return [json.loads(call.args[0]) for call in ws.send_text.call_args_list]


def build_broadcaster(
    payload_source: object,
    *selected_client_ids: str | None,
    ingest_diagnostics: IngestDiagnosticsCollector | None = None,
    push_hz: int = 10,
    heavy_push_hz: int = 4,
) -> tuple[LiveBroadcaster, list[AsyncMock]]:
    broadcaster = LiveBroadcaster(
        payload_source=payload_source,
        ingest_diagnostics=ingest_diagnostics or MagicMock(spec=IngestDiagnosticsCollector),
        push_hz=push_hz,
        heavy_push_hz=heavy_push_hz,
    )
    websockets: list[AsyncMock] = []
    for selected_client_id in selected_client_ids:
        ws = make_websocket()
        broadcaster.add(ws, selected_client_id)
        websockets.append(ws)
    return broadcaster, websockets
