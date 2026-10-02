"""Live WebSocket broadcaster: payload selection, cadence, serialization, and sends."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import anyio
import numpy as np
import pytest
from test_support.ws_hub import build_broadcaster, sent_json, sent_json_sequence

from vibesensor.ingest.diagnostics import IngestDiagnosticsCollector
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
    [TimeoutError("slow"), ConnectionError("reset"), RuntimeError("closed")],
    ids=["timeout", "os-error", "runtime-error"],
)
async def test_failed_send_drops_and_closes_only_that_connection(send_error: Exception) -> None:
    broadcaster, [healthy, failing] = build_broadcaster(_StubPayloadSource(), None, None)
    failing.send_text = AsyncMock(side_effect=send_error)
    failing.close = AsyncMock(side_effect=RuntimeError("already closed"))

    await broadcaster.broadcast(include_heavy=True)
    await broadcaster.broadcast(include_heavy=True)

    assert len(sent_json_sequence(healthy)) == 2
    failing.send_text.assert_awaited_once()
    failing.close.assert_awaited_once()
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
    slow.close.assert_awaited_once()
    assert broadcaster.connection_count() == 1


async def test_send_failure_logging_is_rate_limited(caplog: pytest.LogCaptureFixture) -> None:
    broadcaster, websockets = build_broadcaster(_StubPayloadSource(), "c1", "c2")
    for ws in websockets:
        ws.send_text = AsyncMock(side_effect=ConnectionError("boom"))

    with caplog.at_level(logging.WARNING):
        await broadcaster.broadcast(include_heavy=True)

    assert [r for r in caplog.records if "send failed" in r.message][0].args == ("c1",)
    assert len([r for r in caplog.records if "send failed" in r.message]) == 1


async def test_run_records_publish_metrics_and_escalates_repeated_tick_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnostics = MagicMock(spec=IngestDiagnosticsCollector)
    broadcaster, _ = build_broadcaster(
        _StubPayloadSource(),
        None,
        ingest_diagnostics=diagnostics,
        push_hz=1000,
    )
    outcomes: list[Exception | None] = [None, OSError("one")] + [OSError("again")] * 10
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
    assert len(heavy_flags) == 11
    diagnostics.note_ws_publish.assert_called_once()
    assert diagnostics.note_ws_publish.call_args.kwargs["connection_count"] == 1
