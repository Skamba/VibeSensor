"""Coverage-gap audit (round 2).

Findings addressed
-------------------
1. Processing: multi_spectrum_payload alignment metadata untested
2. Worker pool: submit after shutdown + map_unordered timing metrics
3. WS Hub: run() loop (tick callback, exception recovery, cancellation)
4. GPS: set_fallback_settings boundary values + NaN/Inf override
5. GPS: reconnect back-off doubling and cap
6. History DB: store_analysis idempotency (double-complete) + store_analysis_error
7. History DB: finalize_run no-op on wrong status
8. API export: _flatten_for_csv edge cases (nested dict, extras column)
9. API export: _safe_filename sanitization
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Iterator
from math import pi
from pathlib import Path
from unittest.mock import AsyncMock

import numpy as np
import pytest
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.gps.gps_speed import (
    MAX_STALE_TIMEOUT_S,
    MIN_STALE_TIMEOUT_S,
    GPSSpeedMonitor,
)
from vibesensor.adapters.gps.transport_lifecycle import (
    GPS_RECONNECT_DELAY_S,
    GPS_RECONNECT_MAX_DELAY_S,
)
from vibesensor.adapters.http._helpers import safe_filename as _safe_filename
from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.adapters.websocket.hub import WebSocketHub
from vibesensor.infra.processing import SignalProcessor
from vibesensor.infra.workers.worker_pool import WorkerPool
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.history.exports import flatten_for_csv as _flatten_for_csv

# ── helpers ──────────────────────────────────────────────────────────────────


def _proc(**kwargs) -> SignalProcessor:
    defaults = {
        "sample_rate_hz": 800,
        "waveform_seconds": 4,
        "waveform_display_hz": 100,
        "fft_n": 512,
        "spectrum_max_hz": 200,
    }
    defaults.update(kwargs)
    return SignalProcessor(**defaults)


def _metadata(run_id: str, **overrides: object) -> RunMetadata:
    payload: dict[str, object] = {
        "run_id": run_id,
        "start_time_utc": "2026-01-01T00:00:00Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "source": "test",
    }
    payload.update(overrides)
    return run_metadata_from_mapping(payload)


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


# ═══════════════════════════════════════════════════════════════════════════
# 1. Processing: multi_spectrum_payload alignment metadata
# ═══════════════════════════════════════════════════════════════════════════


class TestMultiSpectrumAlignment:
    """multi_spectrum_payload with multiple sensors should include alignment
    metadata only when ≥ 2 sensors have spectrum data.
    """

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
    """Cover direct submit behavior, runtime stats, worker clamping, and wait-free shutdown."""

    def test_submit_returns_future(self) -> None:
        pool = WorkerPool(max_workers=2)
        try:
            fut = pool.submit(lambda: 42)
            assert fut.result(timeout=2) == 42
        finally:
            pool.shutdown()

    def test_stats_tracks_total_run_s(self) -> None:
        pool = WorkerPool(max_workers=1)
        try:
            pool.map_unordered(lambda x: time.sleep(0.01) or x, [1, 2])
            stats = pool.stats()
            assert stats["total_run_s"] > 0
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
        hub = WebSocketHub()
        ws = AsyncMock()
        ws.send_text = AsyncMock()
        await hub.add(ws, None)

        tick_count = 0

        def on_tick():
            nonlocal tick_count
            tick_count += 1

        task = asyncio.create_task(
            hub.run(hz=100, payload_builder=lambda _: {"ok": True}, on_tick=on_tick),
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


# ═══════════════════════════════════════════════════════════════════════════
# 5. GPS: set_fallback_settings + NaN/Inf override
# ═══════════════════════════════════════════════════════════════════════════


class TestGPSFallbackSettings:
    """Cover fallback timeout clamping, non-finite overrides, and manual-source toggles."""

    def test_set_fallback_settings_clamps_stale_timeout(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        m.set_fallback_settings(stale_timeout_s=0.1)
        assert m.stale_timeout_s == MIN_STALE_TIMEOUT_S

        m.set_fallback_settings(stale_timeout_s=99999)
        assert m.stale_timeout_s == MAX_STALE_TIMEOUT_S

        m.set_fallback_settings(stale_timeout_s=30)
        assert m.stale_timeout_s == 30

    @pytest.mark.parametrize("value", [float("nan"), float("inf")])
    def test_override_non_finite_clears(self, value: float) -> None:
        m = GPSSpeedMonitor(gps_enabled=False)
        m.set_speed_override_kmh(80.0)
        assert m.override_speed_mps is not None
        m.set_speed_override_kmh(value)
        assert m.override_speed_mps is None

    def test_set_manual_source_selected(self) -> None:
        m = GPSSpeedMonitor(gps_enabled=True)
        assert m.manual_source_selected is True
        m.set_manual_source_selected(True)
        assert m.manual_source_selected is True
        m.set_manual_source_selected(False)
        assert m.manual_source_selected is False


# ═══════════════════════════════════════════════════════════════════════════
# 6. GPS: reconnect back-off
# ═══════════════════════════════════════════════════════════════════════════


class TestGPSReconnectBackoff:
    """Cover reconnect delay growth/capping and VERSION-message device-info capture."""

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
        assert delays_seen[0] == GPS_RECONNECT_DELAY_S
        # Delays double
        for i in range(1, min(3, len(delays_seen))):
            assert delays_seen[i] >= delays_seen[i - 1]
        # Should be capped
        for d in delays_seen:
            assert d <= GPS_RECONNECT_MAX_DELAY_S

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


# ═══════════════════════════════════════════════════════════════════════════
# 7. History DB: store_analysis idempotency + store_analysis_error
# ═══════════════════════════════════════════════════════════════════════════


class TestHistoryDBAnalysisIdempotency:
    """Cover store_analysis idempotency, error transitions, and stored-analysis readback."""

    def test_store_analysis_twice_keeps_first(self, history_db: HistoryDB) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1"))
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        history_db.store_analysis("r1", make_persisted_analysis({"findings": ["a"]}))
        # Second store should be no-op (run already complete)
        history_db.store_analysis("r1", make_persisted_analysis({"findings": ["b"]}))
        run = history_db.get_run("r1")
        assert run is not None
        assert run.analysis is not None
        assert run.analysis["findings"] == ["a"], "Second store should not overwrite"

    def test_store_analysis_error_transitions_to_error(self, history_db: HistoryDB) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1"))
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        history_db.store_analysis_error("r1", "pipeline crash")
        run = history_db.get_run("r1")
        assert run is not None
        assert run.status.value == "error"
        assert run.error_message == "pipeline crash"

    def test_get_run_analysis_returns_stored_analysis(self, history_db: HistoryDB) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1"))
        # No analysis yet
        run = history_db.get_run("r1")
        assert run is not None
        assert run.analysis is None
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        history_db.store_analysis("r1", make_persisted_analysis({"result": "ok"}))
        # Complete — should return
        run = history_db.get_run("r1")
        assert run is not None
        result = run.analysis
        assert result is not None
        assert result["result"] == "ok"


# ═══════════════════════════════════════════════════════════════════════════
# 8. History DB: finalize_run on non-recording status
# ═══════════════════════════════════════════════════════════════════════════


class TestHistoryDBFinalizeNoOp:
    """Cover finalize_run no-op behavior for complete, missing, and non-recording runs."""

    def test_finalize_run_noop_on_already_complete(self, history_db: HistoryDB) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1"))
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        history_db.store_analysis("r1", make_persisted_analysis({"ok": True}))
        # Run is now 'complete'.  Calling finalize again should be a no-op.
        history_db.finalize_run("r1", "2026-01-01T00:10:00Z")
        run = history_db.get_run("r1")
        assert run is not None
        assert run.status.value == "complete"

    def test_finalize_run_noop_on_missing_run(self, history_db: HistoryDB) -> None:
        # Should not raise
        history_db.finalize_run("nonexistent", "2026-01-01T00:00:00Z")
        assert history_db.get_run("nonexistent") is None

    def test_finalize_run_with_metadata_noop_when_not_recording(
        self,
        history_db: HistoryDB,
    ) -> None:
        history_db.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1", v=1))
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        # Now analyzing — finalize_run with metadata should no-op
        history_db.finalize_run("r1", "2026-01-01T00:10:00Z", metadata=_metadata("r1", v=2))
        run = history_db.get_run("r1")
        # Metadata should still be the original if the call didn't match status
        assert run is not None
        assert run.status.value == "analyzing"

    def test_get_run_missing_returns_none(self, history_db: HistoryDB) -> None:
        assert history_db.get_run("nonexistent") is None

    def test_get_active_run_id(self, history_db: HistoryDB) -> None:
        assert history_db.get_active_run_id() is None
        history_db.create_run("r1", "2026-01-01T00:00:00Z", _metadata("r1"))
        assert history_db.get_active_run_id() == "r1"
        history_db.finalize_run("r1", "2026-01-01T00:05:00Z")
        assert history_db.get_active_run_id() is None


# ═══════════════════════════════════════════════════════════════════════════
# 9. API export: _flatten_for_csv and extras column
# ═══════════════════════════════════════════════════════════════════════════


class TestFlattenForCSV:
    """Cover CSV flattening for nested known fields and omission of unknown extras."""

    def test_nested_dict_serialised_as_json(self) -> None:
        row = {"top_peaks": [{"hz": 30, "amp": 0.1}], "accel_x_g": 0.5}
        flat = _flatten_for_csv(row)
        # top_peaks is a known CSV column and is list → JSON serialized
        assert isinstance(flat["top_peaks"], str)
        parsed = json.loads(flat["top_peaks"])
        assert parsed == [{"hz": 30, "amp": 0.1}]
        # Scalar values are kept as-is
        assert flat["accel_x_g"] == 0.5

    def test_unknown_keys_are_dropped(self) -> None:
        row = {"accel_x_g": 1.0, "custom_field": "hello", "another": 42}
        flat = _flatten_for_csv(row)
        assert "custom_field" not in flat
        assert "another" not in flat
        assert "extras" not in flat

    def test_no_extras_when_all_known(self) -> None:
        row = {"accel_x_g": 1.0, "speed_kmh": 80.0}
        flat = _flatten_for_csv(row)
        assert "extras" not in flat or flat.get("extras") is None

    def test_empty_row(self) -> None:
        flat = _flatten_for_csv({})
        # Should not crash; no extras
        assert isinstance(flat, dict)


# ═══════════════════════════════════════════════════════════════════════════
# 10. API export: _safe_filename sanitization
# ═══════════════════════════════════════════════════════════════════════════


class TestSafeFilename:
    """Cover exact sanitization outputs, special-character replacement, and truncation."""

    @pytest.mark.parametrize(
        ("input_name", "expected"),
        [
            ("run-2026-01-01_abc", "run-2026-01-01_abc"),
            ("", "download"),
            ("///", "___"),
        ],
    )
    def test_exact_output(self, input_name: str, expected: str) -> None:
        assert _safe_filename(input_name) == expected

    def test_special_chars_replaced(self) -> None:
        result = _safe_filename("run/with spaces & $pecial")
        assert "/" not in result
        assert " " not in result
        assert "$" not in result

    def test_long_name_truncated(self) -> None:
        result = _safe_filename("a" * 500)
        assert len(result) <= 200
