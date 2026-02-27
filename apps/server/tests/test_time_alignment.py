"""Tests for multi-sensor time-window alignment.

Covers:
- Buffer time-range computation
- Cross-sensor alignment calculation (overlap ratio, shared window)
- ``multi_spectrum_payload`` alignment metadata
- Drift / offset scenarios (stale sensor, late start, jitter)
- ``CMD_SYNC_CLOCK`` protocol round-trip
"""

from __future__ import annotations

import struct
from unittest.mock import patch

import numpy as np
import pytest

from vibesensor.processing import _ALIGNMENT_MIN_OVERLAP, SignalProcessor

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_processor(**kwargs) -> SignalProcessor:
    defaults = dict(
        sample_rate_hz=200,
        waveform_seconds=2,
        waveform_display_hz=50,
        fft_n=256,
        spectrum_max_hz=100,
    )
    defaults.update(kwargs)
    return SignalProcessor(**defaults)


def _fill_sensor(
    proc: SignalProcessor,
    client_id: str,
    *,
    n_samples: int = 500,
    sample_rate_hz: int = 200,
    freq_hz: float = 50.0,
    mono_time: float | None = None,
    t0_us: int | None = None,
) -> None:
    """Ingest samples for a sensor, optionally pinning monotonic time and/or t0_us."""
    t = np.arange(n_samples, dtype=np.float32) / sample_rate_hz
    signal = 0.01 * np.sin(2 * np.pi * freq_hz * t)
    samples = np.column_stack([signal, signal, signal])
    if mono_time is not None:
        with patch("vibesensor.processing.time") as mock_time:
            mock_time.monotonic.return_value = mono_time
            proc.ingest(client_id, samples, sample_rate_hz=sample_rate_hz, t0_us=t0_us)
    else:
        proc.ingest(client_id, samples, sample_rate_hz=sample_rate_hz, t0_us=t0_us)


# ---------------------------------------------------------------------------
# _analysis_time_range
# ---------------------------------------------------------------------------


class TestAnalysisTimeRange:
    def test_empty_buffer_returns_none(self) -> None:
        proc = _make_processor()
        info = proc.time_alignment_info(["no_such_sensor"])
        assert info["sensors_excluded"] == ["no_such_sensor"]

    def test_single_sensor_returns_range(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=400, sample_rate_hz=200, mono_time=100.0)
        info = proc.time_alignment_info(["s1"])
        ps = info["per_sensor"]["s1"]
        assert ps["end_s"] == pytest.approx(100.0)
        assert ps["duration_s"] == pytest.approx(2.0)
        assert ps["start_s"] == pytest.approx(98.0)
        assert ps["synced"] is False  # no t0_us provided

    def test_range_limited_by_available_samples(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        # Only 100 samples = 0.5 s of data (less than waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=100, sample_rate_hz=200, mono_time=50.0)
        info = proc.time_alignment_info(["s1"])
        ps = info["per_sensor"]["s1"]
        assert ps["duration_s"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# time_alignment_info – aligned sensors
# ---------------------------------------------------------------------------


class TestTimeAlignmentInfoAligned:
    def test_two_sensors_same_time(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", mono_time=100.0)
        _fill_sensor(proc, "s2", mono_time=100.0)
        info = proc.time_alignment_info(["s1", "s2"])
        assert info["aligned"] is True
        assert info["overlap_ratio"] == pytest.approx(1.0)
        assert info["shared_window"] is not None
        assert info["shared_window"]["duration_s"] == pytest.approx(2.0, abs=0.1)

    def test_small_offset_still_aligned(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", mono_time=100.0)
        _fill_sensor(proc, "s2", mono_time=100.5)  # 0.5 s offset
        info = proc.time_alignment_info(["s1", "s2"])
        assert info["aligned"] is True
        assert info["overlap_ratio"] > _ALIGNMENT_MIN_OVERLAP
        assert info["shared_window"] is not None
        assert info["shared_window"]["duration_s"] > 1.0

    def test_three_sensors_aligned(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", mono_time=100.0)
        _fill_sensor(proc, "s2", mono_time=100.1)
        _fill_sensor(proc, "s3", mono_time=100.2)
        info = proc.time_alignment_info(["s1", "s2", "s3"])
        assert info["aligned"] is True
        assert len(info["sensors_included"]) == 3
        assert len(info["sensors_excluded"]) == 0


# ---------------------------------------------------------------------------
# time_alignment_info – misaligned sensors
# ---------------------------------------------------------------------------


class TestTimeAlignmentInfoMisaligned:
    def test_stale_sensor_not_aligned(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", mono_time=100.0)
        _fill_sensor(proc, "s2", mono_time=110.0)  # 10 s later – no overlap
        info = proc.time_alignment_info(["s1", "s2"])
        assert info["aligned"] is False
        assert info["overlap_ratio"] == pytest.approx(0.0)
        assert info["shared_window"] is None

    def test_partial_overlap(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", mono_time=100.0)
        _fill_sensor(proc, "s2", mono_time=101.5)  # 1.5 s offset → 0.5 s overlap
        info = proc.time_alignment_info(["s1", "s2"])
        assert info["shared_window"] is not None
        assert info["shared_window"]["duration_s"] == pytest.approx(0.5, abs=0.1)
        # overlap_ratio < threshold → not aligned
        assert info["aligned"] is False

    def test_one_sensor_no_data(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", mono_time=100.0)
        # "s2" has no data
        info = proc.time_alignment_info(["s1", "s2"])
        assert "s2" in info["sensors_excluded"]
        assert "s1" in info["sensors_included"]
        # single sensor → trivially aligned
        assert info["aligned"] is True


# ---------------------------------------------------------------------------
# multi_spectrum_payload – alignment metadata
# ---------------------------------------------------------------------------


class TestMultiSpectrumPayloadAlignment:
    def test_alignment_included_when_multiple_sensors(self) -> None:
        proc = _make_processor(sample_rate_hz=200, fft_n=128, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=300, mono_time=100.0)
        _fill_sensor(proc, "s2", n_samples=300, mono_time=100.0)
        proc.compute_metrics("s1", sample_rate_hz=200)
        proc.compute_metrics("s2", sample_rate_hz=200)
        payload = proc.multi_spectrum_payload(["s1", "s2"])
        assert "alignment" in payload
        assert payload["alignment"]["aligned"] is True
        assert payload["alignment"]["sensor_count"] == 2

    def test_no_alignment_key_for_single_sensor(self) -> None:
        proc = _make_processor(sample_rate_hz=200, fft_n=128, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=300, mono_time=100.0)
        proc.compute_metrics("s1", sample_rate_hz=200)
        payload = proc.multi_spectrum_payload(["s1"])
        # Only 1 sensor → no alignment block
        assert "alignment" not in payload

    def test_misaligned_sensors_flagged(self) -> None:
        proc = _make_processor(sample_rate_hz=200, fft_n=128, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=300, mono_time=100.0)
        _fill_sensor(proc, "s2", n_samples=300, mono_time=110.0)
        proc.compute_metrics("s1", sample_rate_hz=200)
        proc.compute_metrics("s2", sample_rate_hz=200)
        payload = proc.multi_spectrum_payload(["s1", "s2"])
        assert payload["alignment"]["aligned"] is False


# ---------------------------------------------------------------------------
# Drift simulation
# ---------------------------------------------------------------------------


class TestDriftSimulation:
    def test_gradual_drift_stays_aligned(self) -> None:
        """Sensors ingesting data with small monotonic jitter remain aligned."""
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        base_time = 1000.0
        for i in range(10):
            _fill_sensor(proc, "s1", n_samples=40, mono_time=base_time + i * 0.2)
            # s2 drifts by 5 ms per tick
            _fill_sensor(proc, "s2", n_samples=40, mono_time=base_time + i * 0.2 + i * 0.005)
        info = proc.time_alignment_info(["s1", "s2"])
        assert info["aligned"] is True

    def test_sensor_restart_detectable(self) -> None:
        """A sensor that restarts mid-session resets its first_ingest timestamp."""
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=400, mono_time=100.0)
        proc.flush_client_buffer("s1")
        _fill_sensor(proc, "s1", n_samples=400, mono_time=200.0)
        info = proc.time_alignment_info(["s1"])
        ps = info["per_sensor"]["s1"]
        assert ps["end_s"] == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# CMD_SYNC_CLOCK protocol round-trip
# ---------------------------------------------------------------------------


class TestCmdSyncClockProtocol:
    def test_pack_and_parse_sync_clock(self) -> None:
        from vibesensor.protocol import (
            CMD_SYNC_CLOCK,
            CMD_SYNC_CLOCK_BYTES,
            pack_cmd_sync_clock,
            parse_cmd,
        )

        client_id = b"\x01\x02\x03\x04\x05\x06"
        cmd_seq = 42
        server_time_us = 123_456_789_012

        raw = pack_cmd_sync_clock(client_id, cmd_seq, server_time_us)
        assert len(raw) == CMD_SYNC_CLOCK_BYTES

        msg = parse_cmd(raw)
        assert msg.cmd_id == CMD_SYNC_CLOCK
        assert msg.cmd_seq == cmd_seq

        # Verify server_time_us is in the params payload
        params = msg.params
        (parsed_time_us,) = struct.unpack("<Q", params)
        assert parsed_time_us == server_time_us

    def test_pack_sync_clock_struct_size(self) -> None:
        from vibesensor.protocol import CMD_SYNC_CLOCK_BYTES, CMD_SYNC_CLOCK_STRUCT

        assert CMD_SYNC_CLOCK_STRUCT.size == CMD_SYNC_CLOCK_BYTES


# ---------------------------------------------------------------------------
# first_ingest_mono_s tracking
# ---------------------------------------------------------------------------


class TestFirstIngestTracking:
    def test_first_ingest_set_on_first_data(self) -> None:
        proc = _make_processor()
        _fill_sensor(proc, "s1", n_samples=100, mono_time=42.0)
        # Access buffer internals (white-box test)
        buf = proc._buffers["s1"]
        assert buf.first_ingest_mono_s == pytest.approx(42.0)

    def test_first_ingest_not_reset_on_subsequent_data(self) -> None:
        proc = _make_processor()
        _fill_sensor(proc, "s1", n_samples=100, mono_time=42.0)
        _fill_sensor(proc, "s1", n_samples=100, mono_time=43.0)
        buf = proc._buffers["s1"]
        assert buf.first_ingest_mono_s == pytest.approx(42.0)
        assert buf.last_ingest_mono_s == pytest.approx(43.0)

    def test_first_ingest_reset_on_flush(self) -> None:
        proc = _make_processor()
        _fill_sensor(proc, "s1", n_samples=100, mono_time=42.0)
        proc.flush_client_buffer("s1")
        buf = proc._buffers["s1"]
        assert buf.first_ingest_mono_s == 0.0


# ---------------------------------------------------------------------------
# Synced-clock alignment (t0_us based)
# ---------------------------------------------------------------------------


class TestSyncedClockAlignment:
    """When sensors report CMD_SYNC_CLOCK-corrected t0_us, alignment uses
    the sensor-clock timestamps (more precise than arrival time)."""

    def test_synced_flag_true_when_t0_us_provided(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=400, mono_time=100.0, t0_us=100_000_000)
        info = proc.time_alignment_info(["s1"])
        assert info["per_sensor"]["s1"]["synced"] is True
        assert info["clock_synced"] is True

    def test_synced_flag_false_without_t0_us(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=400, mono_time=100.0)
        info = proc.time_alignment_info(["s1"])
        assert info["per_sensor"]["s1"]["synced"] is False
        assert info["clock_synced"] is False

    def test_two_synced_sensors_aligned(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        # Both sensors report server-relative timestamps within same window
        server_t = 50_000_000  # 50 s in µs
        _fill_sensor(proc, "s1", n_samples=400, mono_time=100.0, t0_us=server_t)
        _fill_sensor(proc, "s2", n_samples=400, mono_time=100.1, t0_us=server_t + 100_000)
        info = proc.time_alignment_info(["s1", "s2"])
        assert info["aligned"] is True
        assert info["clock_synced"] is True
        assert info["overlap_ratio"] > 0.9

    def test_synced_sensors_with_large_offset_misaligned(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        # Sensor timestamps 10 seconds apart → no overlap
        _fill_sensor(proc, "s1", n_samples=400, mono_time=100.0, t0_us=50_000_000)
        _fill_sensor(proc, "s2", n_samples=400, mono_time=100.0, t0_us=60_000_000)
        info = proc.time_alignment_info(["s1", "s2"])
        assert info["aligned"] is False
        assert info["clock_synced"] is True

    def test_mixed_synced_unsynced_not_clock_synced(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=400, mono_time=100.0, t0_us=50_000_000)
        _fill_sensor(proc, "s2", n_samples=400, mono_time=100.0)  # no t0_us
        info = proc.time_alignment_info(["s1", "s2"])
        assert info["clock_synced"] is False

    def test_synced_alignment_uses_sensor_timestamps_not_arrival_time(self) -> None:
        """Even though both sensors arrive at the server at the same monotonic
        time, the alignment should use the sensor-clock timestamps which may
        differ."""
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        # Same arrival time, but sensor timestamps 5 seconds apart
        _fill_sensor(proc, "s1", n_samples=400, mono_time=100.0, t0_us=10_000_000)
        _fill_sensor(proc, "s2", n_samples=400, mono_time=100.0, t0_us=15_000_000)
        info = proc.time_alignment_info(["s1", "s2"])
        # Sensor-clock says they don't overlap (5s gap, 2s windows)
        assert info["aligned"] is False
        assert info["clock_synced"] is True

    def test_t0_us_stored_in_buffer(self) -> None:
        proc = _make_processor()
        _fill_sensor(proc, "s1", n_samples=100, mono_time=42.0, t0_us=99_000_000)
        buf = proc._buffers["s1"]
        assert buf.last_t0_us == 99_000_000
        assert buf.samples_since_t0 == 100

    def test_t0_us_reset_on_flush(self) -> None:
        proc = _make_processor()
        _fill_sensor(proc, "s1", n_samples=100, mono_time=42.0, t0_us=99_000_000)
        proc.flush_client_buffer("s1")
        buf = proc._buffers["s1"]
        assert buf.last_t0_us == 0
        assert buf.samples_since_t0 == 0

    def test_multi_spectrum_payload_reports_clock_synced(self) -> None:
        proc = _make_processor(sample_rate_hz=200, fft_n=128, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=300, mono_time=100.0, t0_us=50_000_000)
        _fill_sensor(proc, "s2", n_samples=300, mono_time=100.0, t0_us=50_100_000)
        proc.compute_metrics("s1", sample_rate_hz=200)
        proc.compute_metrics("s2", sample_rate_hz=200)
        payload = proc.multi_spectrum_payload(["s1", "s2"])
        assert payload["alignment"]["clock_synced"] is True
        assert payload["alignment"]["aligned"] is True

    def test_samples_since_t0_accumulates_without_new_t0(self) -> None:
        """When successive ingests don't provide t0_us, samples_since_t0
        accumulates so the time range remains accurate."""
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=100, mono_time=100.0, t0_us=50_000_000)
        _fill_sensor(proc, "s1", n_samples=100, mono_time=100.5)  # no t0_us
        buf = proc._buffers["s1"]
        assert buf.last_t0_us == 50_000_000
        assert buf.samples_since_t0 == 200  # 100 + 100
