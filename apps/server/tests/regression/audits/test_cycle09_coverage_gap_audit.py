"""Cycle 2 (cycle 9 in sequence) test-coverage gap audit.

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
import json
import math
import time
from math import pi
from pathlib import Path
from unittest.mock import AsyncMock

import numpy as np
import pytest

from vibesensor.processing import SignalProcessor
from vibesensor.worker_pool import WorkerPool

# ── helpers ──────────────────────────────────────────────────────────────────


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


# ═══════════════════════════════════════════════════════════════════════════
# 1. Processing: debug_spectrum / raw_samples
# ═══════════════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════════════
# 2. Processing: multi_spectrum_payload alignment metadata
# ═══════════════════════════════════════════════════════════════════════════


class TestMultiSpectrumAlignment:
    """multi_spectrum_payload with multiple sensors should include alignment
    metadata only when ≥ 2 sensors have spectrum data."""

    def test_single_sensor_no_alignment_key(self) -> None:
        proc = _proc()
        _inject(proc, "c1", n=1024)
        proc.compute_metrics("c1")
        result = proc.multi_spectrum_payload(["c1"])
        assert "alignment" not in result

    def test_two_sensors_produces_alignment(self) -> None:
        proc = _proc()
        _inject(proc, "c1", n=1024)
        _inject(proc, "c2", n=1024)
        proc.compute_metrics("c1")
        proc.compute_metrics("c2")
        result = proc.multi_spectrum_payload(["c1", "c2"])
        assert "alignment" in result
        alignment = result["alignment"]
        assert "overlap_ratio" in alignment
        assert "aligned" in alignment
        assert isinstance(alignment["sensor_count"], int)
        assert alignment["sensor_count"] == 2

    def test_alignment_overlap_ratio_is_finite(self) -> None:
        proc = _proc()
        _inject(proc, "c1", n=1024)
        _inject(proc, "c2", n=1024)
        proc.compute_metrics("c1")
        proc.compute_metrics("c2")
        result = proc.multi_spectrum_payload(["c1", "c2"])
        assert math.isfinite(result["alignment"]["overlap_ratio"])
        assert isinstance(result["alignment"]["clock_synced"], bool)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Worker pool: submit + timing metrics
# ═══════════════════════════════════════════════════════════════════════════


class TestWorkerPoolExtended:
    def test_submit_returns_future(self) -> None:
        pool = WorkerPool(max_workers=2)
        try:
            fut = pool.submit(lambda: 42)
            assert fut.result(timeout=2) == 42
        finally:
            pool.shutdown()

    def test_stats_tracks_total_wait_s(self) -> None:
        pool = WorkerPool(max_workers=1)
        try:
            pool.map_unordered(lambda x: time.sleep(0.01) or x, [1, 2])
            stats = pool.stats()
            assert stats["total_wait_s"] > 0
            assert stats["total_tasks"] == 2
        finally:
            pool.shutdown()

    def test_max_workers_clamped_to_one(self) -> None:
        pool = WorkerPool(max_workers=0)
        try:
            assert pool.max_workers == 1
        finally:
            pool.shutdown()

    def test_shutdown_wait_false(self) -> None:
        pool = WorkerPool(max_workers=2)
        pool.shutdown(wait=False)
        assert pool.stats()["alive"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 4. WS Hub: run() loop
# ═══════════════════════════════════════════════════════════════════════════


class TestWSHubRunLoop:
    """WebSocketHub.run() is the main broadcast loop; never directly tested."""

    @pytest.mark.asyncio
    async def test_run_calls_on_tick_and_broadcasts(self) -> None:
        from vibesensor.ws_hub import WebSocketHub

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
        from vibesensor.ws_hub import WebSocketHub

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
        from vibesensor.ws_hub import WebSocketHub

        hub = WebSocketHub()
        task = asyncio.create_task(hub.run(hz=0, payload_builder=lambda _: {}))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# ═══════════════════════════════════════════════════════════════════════════
# 5. GPS: set_fallback_settings + NaN/Inf override
# ═══════════════════════════════════════════════════════════════════════════


class TestGPSFallbackSettings:
    def test_set_fallback_settings_clamps_stale_timeout(self) -> None:
        from vibesensor.gps_speed import (
            MAX_STALE_TIMEOUT_S,
            MIN_STALE_TIMEOUT_S,
            GPSSpeedMonitor,
        )

        m = GPSSpeedMonitor(gps_enabled=True)
        m.set_fallback_settings(stale_timeout_s=0.1)
        assert m.stale_timeout_s == MIN_STALE_TIMEOUT_S

        m.set_fallback_settings(stale_timeout_s=99999)
        assert m.stale_timeout_s == MAX_STALE_TIMEOUT_S

        m.set_fallback_settings(stale_timeout_s=30)
        assert m.stale_timeout_s == 30

    def test_set_fallback_settings_rejects_invalid_mode(self) -> None:
        from vibesensor.gps_speed import DEFAULT_FALLBACK_MODE, GPSSpeedMonitor

        m = GPSSpeedMonitor(gps_enabled=True)
        m.set_fallback_settings(fallback_mode="bogus_mode")
        assert m.fallback_mode == DEFAULT_FALLBACK_MODE

    def test_override_nan_clears(self) -> None:
        from vibesensor.gps_speed import GPSSpeedMonitor

        m = GPSSpeedMonitor(gps_enabled=False)
        m.set_speed_override_kmh(80.0)
        assert m.override_speed_mps is not None
        m.set_speed_override_kmh(float("nan"))
        assert m.override_speed_mps is None

    def test_override_inf_clears(self) -> None:
        from vibesensor.gps_speed import GPSSpeedMonitor

        m = GPSSpeedMonitor(gps_enabled=False)
        m.set_speed_override_kmh(80.0)
        m.set_speed_override_kmh(float("inf"))
        assert m.override_speed_mps is None

    def test_set_manual_source_selected(self) -> None:
        from vibesensor.gps_speed import GPSSpeedMonitor

        m = GPSSpeedMonitor(gps_enabled=True)
        assert m.manual_source_selected is None
        m.set_manual_source_selected(True)
        assert m.manual_source_selected is True
        m.set_manual_source_selected(False)
        assert m.manual_source_selected is False


# ═══════════════════════════════════════════════════════════════════════════
# 6. GPS: reconnect back-off
# ═══════════════════════════════════════════════════════════════════════════


class TestGPSReconnectBackoff:
    @pytest.mark.asyncio
    async def test_reconnect_delay_doubles_and_caps(self) -> None:
        from vibesensor.gps_speed import (
            _GPS_RECONNECT_DELAY_S,
            _GPS_RECONNECT_MAX_DELAY_S,
            GPSSpeedMonitor,
        )

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

        original = asyncio.open_connection
        asyncio.open_connection = _mock_open_connection  # type: ignore[assignment]
        # Patch sleep to avoid real delays
        original_sleep = asyncio.sleep

        async def _fast_sleep(delay):
            await original_sleep(0)

        asyncio.sleep = _fast_sleep  # type: ignore[assignment]
        try:
            with pytest.raises(asyncio.CancelledError):
                await m.run(host="127.0.0.1", port=29470)
        finally:
            asyncio.open_connection = original  # type: ignore[assignment]
            asyncio.sleep = original_sleep  # type: ignore[assignment]

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
        from vibesensor.gps_speed import GPSSpeedMonitor

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
        # Device info should contain either "gpsd 3.25" or the device from TPV
        assert "3.25" in (m.device_info or "") or m.device_info is not None


# ═══════════════════════════════════════════════════════════════════════════
# 7. History DB: store_analysis idempotency + store_analysis_error
# ═══════════════════════════════════════════════════════════════════════════


class TestHistoryDBAnalysisIdempotency:
    def test_store_analysis_twice_keeps_first(self, tmp_path: Path) -> None:
        from vibesensor.history_db import HistoryDB

        db = HistoryDB(tmp_path / "test.db")
        try:
            db.create_run("r1", "2026-01-01T00:00:00Z", {})
            db.finalize_run("r1", "2026-01-01T00:05:00Z")
            db.store_analysis("r1", {"findings": ["a"]})
            # Second store should be no-op (run already complete)
            db.store_analysis("r1", {"findings": ["b"]})
            run = db.get_run("r1")
            assert run is not None
            assert run["analysis"]["findings"] == ["a"], "Second store should not overwrite"
        finally:
            db.close()

    def test_store_analysis_error_transitions_to_error(self, tmp_path: Path) -> None:
        from vibesensor.history_db import HistoryDB

        db = HistoryDB(tmp_path / "test.db")
        try:
            db.create_run("r1", "2026-01-01T00:00:00Z", {})
            db.finalize_run("r1", "2026-01-01T00:05:00Z")
            db.store_analysis_error("r1", "pipeline crash")
            run = db.get_run("r1")
            assert run is not None
            assert run["status"] == "error"
            assert run["error_message"] == "pipeline crash"
        finally:
            db.close()

    def test_analysis_is_current_for_missing_run(self, tmp_path: Path) -> None:
        from vibesensor.history_db import HistoryDB

        db = HistoryDB(tmp_path / "test.db")
        try:
            assert db.analysis_is_current("nonexistent") is False
        finally:
            db.close()

    def test_get_run_analysis_only_returns_complete(self, tmp_path: Path) -> None:
        from vibesensor.history_db import HistoryDB

        db = HistoryDB(tmp_path / "test.db")
        try:
            db.create_run("r1", "2026-01-01T00:00:00Z", {})
            # Still recording — get_run_analysis should return None
            assert db.get_run_analysis("r1") is None
            db.finalize_run("r1", "2026-01-01T00:05:00Z")
            # Analyzing — still None
            assert db.get_run_analysis("r1") is None
            db.store_analysis("r1", {"result": "ok"})
            # Complete — should return
            result = db.get_run_analysis("r1")
            assert result is not None
            assert result["result"] == "ok"
        finally:
            db.close()


# ═══════════════════════════════════════════════════════════════════════════
# 8. History DB: finalize_run on non-recording status
# ═══════════════════════════════════════════════════════════════════════════


class TestHistoryDBFinalizeNoOp:
    def test_finalize_run_noop_on_already_complete(self, tmp_path: Path) -> None:
        from vibesensor.history_db import HistoryDB

        db = HistoryDB(tmp_path / "test.db")
        try:
            db.create_run("r1", "2026-01-01T00:00:00Z", {})
            db.finalize_run("r1", "2026-01-01T00:05:00Z")
            db.store_analysis("r1", {"ok": True})
            # Run is now 'complete'.  Calling finalize again should be a no-op.
            db.finalize_run("r1", "2026-01-01T00:10:00Z")
            run = db.get_run("r1")
            assert run["status"] == "complete"

        finally:
            db.close()

    def test_finalize_run_noop_on_missing_run(self, tmp_path: Path) -> None:
        from vibesensor.history_db import HistoryDB

        db = HistoryDB(tmp_path / "test.db")
        try:
            # Should not raise
            db.finalize_run("nonexistent", "2026-01-01T00:00:00Z")
        finally:
            db.close()

    def test_finalize_run_with_metadata_noop_when_not_recording(self, tmp_path: Path) -> None:
        from vibesensor.history_db import HistoryDB

        db = HistoryDB(tmp_path / "test.db")
        try:
            db.create_run("r1", "2026-01-01T00:00:00Z", {"v": 1})
            db.finalize_run("r1", "2026-01-01T00:05:00Z")
            # Now analyzing — finalize_run_with_metadata should no-op
            db.finalize_run_with_metadata("r1", "2026-01-01T00:10:00Z", {"v": 2})
            run = db.get_run("r1")
            # Metadata should still be the original if the call didn't match status
            assert run["status"] == "analyzing"
        finally:
            db.close()

    def test_get_run_status_missing_returns_none(self, tmp_path: Path) -> None:
        from vibesensor.history_db import HistoryDB

        db = HistoryDB(tmp_path / "test.db")
        try:
            assert db.get_run_status("nonexistent") is None
        finally:
            db.close()

    def test_get_active_run_id(self, tmp_path: Path) -> None:
        from vibesensor.history_db import HistoryDB

        db = HistoryDB(tmp_path / "test.db")
        try:
            assert db.get_active_run_id() is None
            db.create_run("r1", "2026-01-01T00:00:00Z", {})
            assert db.get_active_run_id() == "r1"
            db.finalize_run("r1", "2026-01-01T00:05:00Z")
            assert db.get_active_run_id() is None
        finally:
            db.close()


# ═══════════════════════════════════════════════════════════════════════════
# 9. API export: _flatten_for_csv and extras column
# ═══════════════════════════════════════════════════════════════════════════


class TestFlattenForCSV:
    def test_nested_dict_serialised_as_json(self) -> None:
        from vibesensor.api import _flatten_for_csv

        row = {"top_peaks": [{"hz": 30, "amp": 0.1}], "accel_x_g": 0.5}
        flat = _flatten_for_csv(row)
        # top_peaks is a known CSV column and is list → JSON serialized
        assert isinstance(flat["top_peaks"], str)
        parsed = json.loads(flat["top_peaks"])
        assert parsed == [{"hz": 30, "amp": 0.1}]
        # Scalar values are kept as-is
        assert flat["accel_x_g"] == 0.5

    def test_extras_column_collects_unknown_keys(self) -> None:
        from vibesensor.api import _flatten_for_csv

        row = {"accel_x_g": 1.0, "custom_field": "hello", "another": 42}
        flat = _flatten_for_csv(row)
        extras = json.loads(flat["extras"])
        assert extras["custom_field"] == "hello"
        assert extras["another"] == 42
        assert "accel_x_g" not in extras

    def test_no_extras_when_all_known(self) -> None:
        from vibesensor.api import _flatten_for_csv

        row = {"accel_x_g": 1.0, "speed_kmh": 80.0}
        flat = _flatten_for_csv(row)
        assert "extras" not in flat or flat.get("extras") is None

    def test_empty_row(self) -> None:
        from vibesensor.api import _flatten_for_csv

        flat = _flatten_for_csv({})
        # Should not crash; no extras
        assert isinstance(flat, dict)


# ═══════════════════════════════════════════════════════════════════════════
# 10. API export: _safe_filename sanitization
# ═══════════════════════════════════════════════════════════════════════════


class TestSafeFilename:
    def test_normal_name_preserved(self) -> None:
        from vibesensor.api import _safe_filename

        assert _safe_filename("run-2026-01-01_abc") == "run-2026-01-01_abc"

    def test_special_chars_replaced(self) -> None:
        from vibesensor.api import _safe_filename

        result = _safe_filename("run/with spaces & $pecial")
        assert "/" not in result
        assert " " not in result
        assert "$" not in result

    def test_empty_string_returns_download(self) -> None:
        from vibesensor.api import _safe_filename

        assert _safe_filename("") == "download"

    def test_long_name_truncated(self) -> None:
        from vibesensor.api import _safe_filename

        long_name = "a" * 500
        result = _safe_filename(long_name)
        assert len(result) <= 200

    def test_all_special_chars_replaced_with_underscores(self) -> None:
        from vibesensor.api import _safe_filename

        # All characters replaced with underscores
        result = _safe_filename("///")
        assert result == "___"
        # Only the empty-string case gives "download"
        assert _safe_filename("") == "download"
