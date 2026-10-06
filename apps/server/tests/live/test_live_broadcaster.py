"""Live WebSocket broadcaster: payload selection, cadence, serialization, and sends."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import anyio
import numpy as np
import pytest
from starlette.websockets import WebSocketDisconnect, WebSocketDisconnected
from test_support.ws_hub import build_broadcaster, sent_json, sent_json_sequence

from vibesensor.ingest.diagnostics import IngestDiagnosticsCollector
from vibesensor.live import broadcaster as broadcaster_module
from vibesensor.live.broadcaster import ERROR_PAYLOAD_TEXT
from vibesensor.live.payload_types import (
    SCHEMA_VERSION,
    ClientApiRow,
    LiveWsPayload,
    RotationalSpeedsPayload,
)
from vibesensor.live.runtime_failures import BroadcastTickLoopFailure


def _client_row(client_id: str, name: str) -> ClientApiRow:
    return {
        "id": client_id,
        "mac_address": client_id,
        "name": name,
        "connected": True,
        "location_code": "",
        "firmware_version": "fw",
        "sample_rate_hz": 800,
        "last_seen_age_ms": 0,
        "frames_total": 0,
        "dropped_frames": 0,
        "frame_samples": 200,
    }


def _rotational_payload() -> RotationalSpeedsPayload:
    return {
        "basis_speed_source": "gps",
        "wheel": {"rpm": 1.0, "mode": "calculated", "reason": None},
        "driveshaft": {"rpm": 1.0, "mode": "calculated", "reason": None},
        "engine": {"rpm": 1.0, "mode": "calculated", "reason": None},
        "order_bands": None,
    }


def _shared_payload(
    *,
    clients: list[ClientApiRow] | None = None,
    server_time: str = "2026-04-05T00:00:00Z",
) -> LiveWsPayload:
    return {
        "schema_version": SCHEMA_VERSION,
        "server_time": server_time,
        "speed_mps": 12.5,
        "clients": clients or [],
        "selected_client_id": None,
        "rotational_speeds": _rotational_payload(),
        "spectra": {"freq": [], "clients": {}},
    }


class _StubPayloadSource:
    def __init__(self, payloads: list[LiveWsPayload] | None = None) -> None:
        self.calls: list[bool] = []
        self._payloads = payloads or [_shared_payload()]

    def build_shared_payload(self, *, include_heavy: bool) -> LiveWsPayload:
        self.calls.append(include_heavy)
        index = min(len(self.calls) - 1, len(self._payloads) - 1)
        return self._payloads[index]


@pytest.mark.parametrize(
    ("clients", "selected_client", "expected_selected"),
    [
        pytest.param(
            [_client_row("aaaaaaaaaaaa", "front-left")],
            "aaaaaaaaaaaa",
            "aaaaaaaaaaaa",
            id="explicit-selection",
        ),
        pytest.param(
            [
                _client_row("aaaaaaaaaaaa", "front-left"),
                _client_row("bbbbbbbbbbbb", "rear-right"),
            ],
            None,
            "aaaaaaaaaaaa",
            id="auto-selects-first-client",
        ),
        pytest.param([], None, None, id="no-clients"),
    ],
)
async def test_selected_client_defaults_to_first_client(
    clients: list[ClientApiRow],
    selected_client: str | None,
    expected_selected: str | None,
) -> None:
    broadcaster, [ws] = build_broadcaster(
        _StubPayloadSource([_shared_payload(clients=clients)]),
        selected_client,
    )

    await broadcaster.broadcast(include_heavy=True)

    payload = sent_json(ws)
    assert payload["clients"] == clients
    assert payload["selected_client_id"] == expected_selected


async def test_one_payload_build_per_tick_shared_across_selections() -> None:
    clients = [_client_row("aaaaaaaaaaaa", "front-left"), _client_row("bbbbbbbbbbbb", "rear")]
    source = _StubPayloadSource([_shared_payload(clients=clients)])
    broadcaster, [ws_a, ws_b, ws_default] = build_broadcaster(
        source,
        "aaaaaaaaaaaa",
        "bbbbbbbbbbbb",
        None,
    )

    await broadcaster.broadcast(include_heavy=False)

    assert source.calls == [False]
    assert sent_json(ws_a)["selected_client_id"] == "aaaaaaaaaaaa"
    assert sent_json(ws_b)["selected_client_id"] == "bbbbbbbbbbbb"
    assert sent_json(ws_default)["selected_client_id"] == "aaaaaaaaaaaa"
    assert sent_json(ws_a)["server_time"] == sent_json(ws_b)["server_time"]


async def test_select_and_remove_route_payloads() -> None:
    clients = [_client_row("aaaaaaaaaaaa", "front-left"), _client_row("bbbbbbbbbbbb", "rear")]
    broadcaster, [ws, removed] = build_broadcaster(
        _StubPayloadSource([_shared_payload(clients=clients)]),
        None,
        None,
    )
    broadcaster.select(ws, "bbbbbbbbbbbb")
    broadcaster.remove(removed)
    broadcaster.remove(removed)
    broadcaster.select(removed, "aaaaaaaaaaaa")

    await broadcaster.broadcast(include_heavy=True)

    assert sent_json(ws)["selected_client_id"] == "bbbbbbbbbbbb"
    removed.send_text.assert_not_awaited()
    assert broadcaster.connection_count() == 1


async def test_selection_change_and_removal_mid_tick_use_the_tick_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A browser selecting a sensor or leaving while the tick serializes (Pi KeyError)."""
    clients = [_client_row("aaaaaaaaaaaa", "front-left"), _client_row("bbbbbbbbbbbb", "rear")]
    broadcaster, [selecting, leaving, default] = build_broadcaster(
        _StubPayloadSource([_shared_payload(clients=clients)]),
        "aaaaaaaaaaaa",
        "aaaaaaaaaaaa",
        None,
    )
    serialize = broadcaster_module._serialize
    browser_acted = False

    def _serialize_while_browsers_act(shared: LiveWsPayload, selected: str | None) -> str:
        nonlocal browser_acted
        if not browser_acted:
            browser_acted = True
            # The /ws route runs these on the event loop while the tick awaits this thread.
            anyio.from_thread.run_sync(broadcaster.select, selecting, "bbbbbbbbbbbb")
            anyio.from_thread.run_sync(broadcaster.remove, leaving)
        return serialize(shared, selected)

    monkeypatch.setattr(broadcaster_module, "_serialize", _serialize_while_browsers_act)

    await broadcaster.broadcast(include_heavy=True)
    await broadcaster.broadcast(include_heavy=True)

    assert [p["selected_client_id"] for p in sent_json_sequence(selecting)] == [
        "aaaaaaaaaaaa",
        "bbbbbbbbbbbb",
    ]
    assert [p["selected_client_id"] for p in sent_json_sequence(default)] == ["aaaaaaaaaaaa"] * 2
    leaving.send_text.assert_not_awaited()
    leaving.on_drop.assert_not_called()
    assert broadcaster.connection_count() == 2


async def test_no_payload_built_without_connections() -> None:
    source = _StubPayloadSource()
    broadcaster, _ = build_broadcaster(source)

    await broadcaster.broadcast(include_heavy=True)

    assert source.calls == []


@pytest.mark.parametrize(
    ("push_hz", "heavy_push_hz", "expected"),
    [
        pytest.param(10, 4, [False, False, True, False, True] * 2, id="fractional"),
        pytest.param(10, 2, [False, False, False, False, True] * 2, id="every-fifth"),
        pytest.param(4, 4, [True] * 10, id="heavy-every-tick"),
    ],
)
def test_heavy_cadence(push_hz: int, heavy_push_hz: int, expected: list[bool]) -> None:
    broadcaster, _ = build_broadcaster(
        _StubPayloadSource(),
        push_hz=push_hz,
        heavy_push_hz=heavy_push_hz,
    )

    assert [broadcaster._next_tick_includes_heavy() for _ in range(10)] == expected


async def test_build_failure_sends_error_payload_to_every_connection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = MagicMock()
    source.build_shared_payload.side_effect = RuntimeError("boom")
    broadcaster, websockets = build_broadcaster(source, "aaaaaaaaaaaa", None)

    with caplog.at_level(logging.ERROR):
        await broadcaster.broadcast(include_heavy=True)

    for ws in websockets:
        ws.send_text.assert_awaited_once_with(ERROR_PAYLOAD_TEXT)
    assert sent_json(websockets[0]) == {"error": "payload_build_failed"}
    assert "payload build failed" in caplog.text
    assert broadcaster.connection_count() == 2


async def test_serialization_replaces_non_finite_and_numpy_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    payload = _shared_payload()
    payload["speed_mps"] = float("nan")
    payload["spectra"] = {"freq": np.array([1.0, np.inf], dtype=np.float32), "clients": {}}  # type: ignore[typeddict-item]
    broadcaster, [ws] = build_broadcaster(_StubPayloadSource([payload]), None)

    with caplog.at_level(logging.WARNING):
        await broadcaster.broadcast(include_heavy=True)

    sent = sent_json(ws)
    assert sent["speed_mps"] is None
    assert sent["spectra"] == {"freq": [1.0, None], "clients": {}}
    assert "NaN/Inf" in caplog.text


@pytest.mark.parametrize(
    "send_error",
    [
        TimeoutError("slow"),
        ConnectionError("reset"),
        WebSocketDisconnect(1006),
        RuntimeError("closed"),
        ValueError("unexpected"),
    ],
    ids=["timeout", "os-error", "disconnect", "runtime-error", "unexpected-error"],
)
async def test_failed_send_drops_only_that_connection(send_error: Exception) -> None:
    broadcaster, [healthy, failing] = build_broadcaster(_StubPayloadSource(), None, None)
    failing.send_text = AsyncMock(side_effect=send_error)

    await broadcaster.broadcast(include_heavy=True)
    await broadcaster.broadcast(include_heavy=True)

    assert len(sent_json_sequence(healthy)) == 2
    failing.send_text.assert_awaited_once()
    failing.on_drop.assert_called_once_with()
    healthy.on_drop.assert_not_called()
    # The /ws endpoint owns closing; the broadcaster never closes a socket itself.
    failing.close.assert_not_awaited()
    assert broadcaster.connection_count() == 1


async def test_slow_consumer_is_dropped_without_blocking_fast_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("vibesensor.live.broadcaster.SEND_TIMEOUT_S", 0.01)
    broadcaster, [fast, slow] = build_broadcaster(_StubPayloadSource(), None, None)

    async def _hang(_text: str) -> None:
        await anyio.sleep_forever()

    slow.send_text.side_effect = _hang

    with anyio.fail_after(1.0):
        await broadcaster.broadcast(include_heavy=True)

    fast.send_text.assert_awaited_once()
    slow.on_drop.assert_called_once_with()
    assert broadcaster.connection_count() == 1


@pytest.mark.parametrize(
    ("send_error", "level", "has_traceback"),
    [
        (ConnectionError("reset"), logging.INFO, False),
        (WebSocketDisconnected("closed"), logging.INFO, False),
        (TimeoutError(), logging.INFO, False),
        (RuntimeError("unexpected"), logging.WARNING, True),
    ],
    ids=["os-error", "already-closed", "timeout", "unexpected"],
)
async def test_send_failure_logging_is_one_line_for_gone_clients_and_rate_limited(
    caplog: pytest.LogCaptureFixture,
    send_error: Exception,
    level: int,
    has_traceback: bool,
) -> None:
    broadcaster, websockets = build_broadcaster(_StubPayloadSource(), "c1", "c2")
    for ws in websockets:
        ws.send_text = AsyncMock(side_effect=send_error)

    with caplog.at_level(logging.DEBUG, logger="vibesensor.live.broadcaster"):
        await broadcaster.broadcast(include_heavy=True)

    [record] = [r for r in caplog.records if "dropping connection" in r.message]
    assert record.args is not None and record.args[0] == "c1"
    assert record.levelno == level
    assert (record.exc_info is not None) is has_traceback


async def test_run_survives_failed_ticks_and_escalates_only_repeated_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnostics = MagicMock(spec=IngestDiagnosticsCollector)
    broadcaster, _ = build_broadcaster(
        _StubPayloadSource(),
        None,
        ingest_diagnostics=diagnostics,
        push_hz=1000,
    )
    unexpected = ExceptionGroup("tick", [KeyError("c0ffee000001")])
    outcomes: list[Exception | None] = [None, unexpected, None] + [OSError("again")] * 10
    heavy_flags: list[bool] = []

    async def _broadcast(*, include_heavy: bool) -> None:
        heavy_flags.append(include_heavy)
        outcome = outcomes.pop(0)
        if outcome is not None:
            raise outcome

    monkeypatch.setattr(broadcaster, "broadcast", _broadcast)

    with anyio.fail_after(5.0), pytest.raises(BroadcastTickLoopFailure) as excinfo:
        await broadcaster.run()

    assert excinfo.value.consecutive_failures == 10
    assert len(heavy_flags) == 13
    assert diagnostics.note_ws_publish.call_count == 2
    assert diagnostics.note_ws_publish.call_args.kwargs["connection_count"] == 1
