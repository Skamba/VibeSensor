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
        with patch("vibesensor.processing.processor.time") as mock_time:
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
        parsed_time_us = struct.unpack("<Q", params)[0]
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

    @pytest.mark.parametrize(
        "t0_us, expected",
        [
            pytest.param(100_000_000, True, id="with_t0_us"),
            pytest.param(None, False, id="without_t0_us"),
        ],
    )
    def test_synced_flag(self, t0_us: int | None, expected: bool) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=400, mono_time=100.0, t0_us=t0_us)
        info = proc.time_alignment_info(["s1"])
        assert info["per_sensor"]["s1"]["synced"] is expected
        assert info["clock_synced"] is expected

    @pytest.mark.parametrize(
        "s1_t0, s2_mono, s2_t0, expected_aligned",
        [
            pytest.param(50_000_000, 100.1, 50_100_000, True, id="close_timestamps"),
            pytest.param(50_000_000, 100.0, 60_000_000, False, id="large_t0_offset"),
            pytest.param(10_000_000, 100.0, 15_000_000, False, id="same_arrival_diff_sensor_ts"),
        ],
    )
    def test_synced_pair_alignment(
        self, s1_t0: int, s2_mono: float, s2_t0: int, expected_aligned: bool
    ) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=400, mono_time=100.0, t0_us=s1_t0)
        _fill_sensor(proc, "s2", n_samples=400, mono_time=s2_mono, t0_us=s2_t0)
        info = proc.time_alignment_info(["s1", "s2"])
        assert info["aligned"] is expected_aligned
        assert info["clock_synced"] is True
        if expected_aligned:
            assert info["overlap_ratio"] > 0.9

    def test_mixed_synced_unsynced_not_clock_synced(self) -> None:
        proc = _make_processor(sample_rate_hz=200, waveform_seconds=2)
        _fill_sensor(proc, "s1", n_samples=400, mono_time=100.0, t0_us=50_000_000)
        _fill_sensor(proc, "s2", n_samples=400, mono_time=100.0)  # no t0_us
        info = proc.time_alignment_info(["s1", "s2"])
        assert info["clock_synced"] is False

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


# ---------------------------------------------------------------------------
# Wave 3 Bruno3 — analysis_time_range edge-case fixes
# ---------------------------------------------------------------------------


class TestAnalysisTimeRangeEdgeCases:
    """Tests for Fix 9 (negative samples_since_t0 guard) and Fix 10
    (waveform_seconds <= 0 early return) in analysis_time_range."""

    def test_negative_samples_since_t0_clamped_to_zero(self) -> None:
        """Fix 9: samples_since_t0 < 0 must not produce end_us < last_t0_us.

        When samples_since_t0 is negative (defensive guard against corruption),
        analysis_time_range should clamp it to 0 so end_s == last_t0_us / 1e6.
        """
        from vibesensor.processing.time_align import analysis_time_range

        last_t0_us = 10_000_000  # 10 s
        result = analysis_time_range(
            count=400,
            last_ingest_mono_s=10.5,
            sample_rate_hz=200,
            waveform_seconds=2,
            capacity=400,
            last_t0_us=last_t0_us,
            samples_since_t0=-50,  # corrupt / inverted — must be clamped
        )
        assert result is not None
        start_s, end_s, synced = result
        assert synced is True
        # end_s must equal last_t0_us / 1e6 (0 samples advanced)
        assert end_s == pytest.approx(10.0)
        assert start_s <= end_s

    def test_zero_waveform_seconds_returns_none(self) -> None:
        """Fix 10: waveform_seconds <= 0 must return None rather than a silent 1-sample window."""
        from vibesensor.processing.time_align import analysis_time_range

        result = analysis_time_range(
            count=400,
            last_ingest_mono_s=10.5,
            sample_rate_hz=200,
            waveform_seconds=0,
            capacity=400,
            last_t0_us=0,
            samples_since_t0=0,
        )
        assert result is None

    def test_negative_waveform_seconds_returns_none(self) -> None:
        """Fix 10: waveform_seconds < 0 must also return None."""
        from vibesensor.processing.time_align import analysis_time_range

        result = analysis_time_range(
            count=200,
            last_ingest_mono_s=5.0,
            sample_rate_hz=100,
            waveform_seconds=-3,
            capacity=300,
            last_t0_us=0,
            samples_since_t0=0,
        )
        assert result is None

