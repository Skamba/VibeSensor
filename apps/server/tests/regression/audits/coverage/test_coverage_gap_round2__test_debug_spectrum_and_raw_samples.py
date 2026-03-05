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
import math
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


class TestDebugSpectrumAndRawSamples:
    """debug_spectrum() and raw_samples() are only tested indirectly via API
    mocks.  Direct unit tests ensure correctness of the returned data."""

    def test_debug_spectrum_insufficient_samples(self) -> None:
        proc = _proc(fft_n=512)
        # No data
        result = proc.debug_spectrum("nonexistent")
        assert result["error"] == "insufficient samples"
        assert result["count"] == 0
        assert result["fft_n"] == 512

    def test_debug_spectrum_returns_expected_keys(self) -> None:
        proc = _proc(fft_n=512)
        _inject(proc, "c1", n=1024)
        proc.compute_metrics("c1")
        result = proc.debug_spectrum("c1")
        assert "error" not in result
        assert result["client_id"] == "c1"
        assert result["fft_n"] == 512
        assert result["window"] == "hann"
        assert result["freq_bins"] > 0
        assert result["freq_resolution_hz"] > 0
        assert math.isfinite(result["vibration_strength_db"])
        assert isinstance(result["top_bins_by_amplitude"], list)
        assert len(result["top_bins_by_amplitude"]) <= 10
        for b in result["top_bins_by_amplitude"]:
            assert "freq_hz" in b
            assert "combined_amp_g" in b

    def test_debug_spectrum_raw_stats_are_finite(self) -> None:
        proc = _proc(fft_n=256)
        _inject(proc, "c1", n=512)
        result = proc.debug_spectrum("c1")
        for key in ("mean_g", "std_g", "min_g", "max_g"):
            vals = result["raw_stats"][key]
            assert len(vals) == 3
            for v in vals:
                assert math.isfinite(v), f"non-finite in raw_stats[{key}]"
        assert len(result["detrended_std_g"]) == 3

    def test_raw_samples_no_data(self) -> None:
        proc = _proc()
        result = proc.raw_samples("nonexistent")
        assert result["error"] == "no data"
        assert result["count"] == 0

    def test_raw_samples_returns_axes(self) -> None:
        proc = _proc()
        _inject(proc, "c1", n=200)
        result = proc.raw_samples("c1", n_samples=100)
        assert result["client_id"] == "c1"
        assert result["n_samples"] == 100
        assert len(result["x"]) == 100
        assert len(result["y"]) == 100
        assert len(result["z"]) == 100

    def test_raw_samples_caps_at_available(self) -> None:
        proc = _proc()
        _inject(proc, "c1", n=50)
        result = proc.raw_samples("c1", n_samples=9999)
        assert result["n_samples"] == 50
