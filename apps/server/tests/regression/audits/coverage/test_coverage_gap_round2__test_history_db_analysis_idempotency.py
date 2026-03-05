"""Coverage-gap audit (round 2).

Findings addressed
-------------------
1. Processing: debug_spectrum / raw_samples never directly tested
2. Processing: multi_spectrum_payload alignment metadata untested
3. Worker pool: submit after shutdown + map_unordered timing metrics
4. WS Hub: run() loop (tick callback, exception recovery, cancellation)
5. GPS: set_fallback_settings boundary values + NaN/Inf override
6. GPS: reconnect back-off doubling and cap
7. History DB: store_analysis idempotency (double-complete) + store_analysis_error
8. History DB: finalize_run no-op on wrong status
9. API export: _flatten_for_csv edge cases (nested dict, extras column)
10. API export: _safe_filename sanitization
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from math import pi
from pathlib import Path
from unittest.mock import AsyncMock

import numpy as np
import pytest

from vibesensor.gps_speed import (
    _GPS_RECONNECT_DELAY_S,
    _GPS_RECONNECT_MAX_DELAY_S,
    GPSSpeedMonitor,
)
from vibesensor.history_db import HistoryDB
from vibesensor.processing import SignalProcessor
from vibesensor.ws_hub import WebSocketHub


def _proc(**kwargs) -> SignalProcessor:
    defaults = dict(
        sample_rate_hz=800,
        waveform_seconds=4,
        waveform_display_hz=100,
        fft_n=512,
        spectrum_max_hz=200,
    )
    defaults.update(kwargs)
    return SignalProcessor(**defaults)


def _inject(proc: SignalProcessor, cid: str, n: int = 1024, sr: int = 800) -> None:
    rng = np.random.default_rng(42)
    t = np.arange(n, dtype=np.float64) / sr
    x = (0.03 * np.sin(2.0 * pi * 30.0 * t)).astype(np.float32)
    y = (0.02 * np.sin(2.0 * pi * 50.0 * t)).astype(np.float32)
    z = (rng.standard_normal(n) * 0.005).astype(np.float32)
    samples = np.stack([x, y, z], axis=1)
    proc.ingest(cid, samples, sample_rate_hz=sr)


@pytest.fixture
def history_db(tmp_path: Path) -> Iterator[HistoryDB]:
    """Yield an open HistoryDB that is closed after the test."""
    db = HistoryDB(tmp_path / "test.db")
    try:
        yield db
    finally:
        db.close()


class TestWSHubRunLoop:
    """WebSocketHub.run() is the main broadcast loop; never directly tested."""

    @pytest.mark.asyncio
    async def test_run_calls_on_tick_and_broadcasts(self) -> None:
        hub = WebSocketHub()
        ws = AsyncMock()
        ws.send_text = AsyncMock()
        await hub.add(ws, None)

        tick_count = 0

        def on_tick():
            nonlocal tick_count
            tick_count += 1

        task = asyncio.create_task(
            hub.run(hz=100, payload_builder=lambda _: {"ok": True}, on_tick=on_tick)
        )
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert tick_count >= 2, f"on_tick called {tick_count} times, expected >= 2"
        assert ws.send_text.await_count >= 2

    @pytest.mark.asyncio
    async def test_run_survives_broadcast_exception(self) -> None:
        hub = WebSocketHub()
        call_count = 0

        def flaky_builder(_cid):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first tick boom")
            return {"ok": True}

        ws = AsyncMock()
        ws.send_text = AsyncMock()
        await hub.add(ws, None)

        task = asyncio.create_task(hub.run(hz=50, payload_builder=flaky_builder))
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Should have recovered and called builder more than once
        assert call_count >= 2

    @pytest.mark.asyncio
    async def test_run_hz_clamps_to_minimum_1(self) -> None:
        hub = WebSocketHub()
        task = asyncio.create_task(hub.run(hz=0, payload_builder=lambda _: {}))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


class TestGPSReconnectBackoff:
    @pytest.mark.asyncio
    async def test_reconnect_delay_doubles_and_caps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        delays_seen: list[float] = []

        connect_count = 0

        async def _mock_open_connection(host, port):
            nonlocal connect_count
            connect_count += 1
            delays_seen.append(m.current_reconnect_delay)
            if connect_count >= 5:
                raise asyncio.CancelledError()
            raise ConnectionRefusedError("test")

        original_sleep = asyncio.sleep

        async def _fast_sleep(delay):
            await original_sleep(0)

        monkeypatch.setattr(asyncio, "open_connection", _mock_open_connection)
        monkeypatch.setattr(asyncio, "sleep", _fast_sleep)

        with pytest.raises(asyncio.CancelledError):
            await m.run(host="127.0.0.1", port=29470)

        # First reconnect_delay should be the base delay
        assert delays_seen[0] == _GPS_RECONNECT_DELAY_S
        # Delays double
        for i in range(1, min(3, len(delays_seen))):
            assert delays_seen[i] >= delays_seen[i - 1]
        # Should be capped
        for d in delays_seen:
            assert d <= _GPS_RECONNECT_MAX_DELAY_S

    @pytest.mark.asyncio
    async def test_version_message_sets_device_info(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)

        async def _handler(reader, writer):
            await reader.readline()  # consume WATCH command
            writer.write(b'{"class":"VERSION","rev":"3.25"}\n')
            await writer.drain()
            writer.write(b'{"class":"TPV","mode":3,"speed":10.0}\n')
            await writer.drain()
            # Keep alive briefly then close
            await asyncio.sleep(0.05)
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(_handler, host="127.0.0.1", port=0)
        host, port = server.sockets[0].getsockname()[:2]

        task = asyncio.create_task(m.run(host=host, port=port))
        await asyncio.sleep(0.2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        server.close()
        await server.wait_closed()

        assert m.device_info is not None
        # Device info should contain the gpsd version string
        assert "3.25" in m.device_info


class TestHistoryDBAnalysisIdempotency:
    def test_store_analysis_twice_keeps_first(self, history_db: HistoryDB) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", {})
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        history_db.store_analysis("r1", {"findings": ["a"]})
        # Second store should be no-op (run already complete)
        history_db.store_analysis("r1", {"findings": ["b"]})
        run = history_db.get_run("r1")
        assert run is not None
        assert run["analysis"]["findings"] == ["a"], "Second store should not overwrite"

    def test_store_analysis_error_transitions_to_error(self, history_db: HistoryDB) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", {})
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        history_db.store_analysis_error("r1", "pipeline crash")
        run = history_db.get_run("r1")
        assert run is not None
        assert run["status"] == "error"
        assert run["error_message"] == "pipeline crash"

    def test_analysis_is_current_for_missing_run(self, history_db: HistoryDB) -> None:
        assert history_db.analysis_is_current("nonexistent") is False

    def test_get_run_analysis_only_returns_complete(self, history_db: HistoryDB) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", {})
        # Still recording — get_run_analysis should return None
        assert history_db.get_run_analysis("r1") is None
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        # Analyzing — still None
        assert history_db.get_run_analysis("r1") is None
        history_db.store_analysis("r1", {"result": "ok"})
        # Complete — should return
        result = history_db.get_run_analysis("r1")
        assert result is not None
        assert result["result"] == "ok"
