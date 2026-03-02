"""Unit tests for vibesensor.processing.time_align pure functions.

These tests validate the time-alignment utilities extracted from the
monolithic SignalProcessor class.  All functions under test are pure
(no shared state), enabling precise, deterministic testing.
"""

from __future__ import annotations

import pytest


class TestComputeOverlap:
    """Tests for the intersection-over-union overlap computation."""

    def test_empty_inputs(self) -> None:
        from vibesensor.processing.time_align import compute_overlap

        result = compute_overlap([], [])
        assert result.overlap_ratio == 0.0
        assert result.aligned is False
        assert result.overlap_s == 0.0

    def test_mismatched_lengths(self) -> None:
        from vibesensor.processing.time_align import compute_overlap

        result = compute_overlap([1.0], [2.0, 3.0])
        assert result.overlap_ratio == 0.0
        assert result.aligned is False

    def test_identical_ranges(self) -> None:
        from vibesensor.processing.time_align import compute_overlap

        result = compute_overlap([0.0, 0.0], [10.0, 10.0])
        assert result.overlap_ratio == pytest.approx(1.0)
        assert result.aligned is True
        assert result.overlap_s == pytest.approx(10.0)

    def test_no_overlap(self) -> None:
        from vibesensor.processing.time_align import compute_overlap

        result = compute_overlap([0.0, 20.0], [10.0, 30.0])
        assert result.overlap_ratio == pytest.approx(0.0)
        assert result.aligned is False
        assert result.overlap_s == pytest.approx(0.0)

    def test_partial_overlap(self) -> None:
        from vibesensor.processing.time_align import compute_overlap

        result = compute_overlap([0.0, 5.0], [10.0, 15.0])
        # Union: 0–15 = 15s, overlap: 5–10 = 5s → ratio = 5/15 ≈ 0.333
        assert result.overlap_ratio == pytest.approx(5.0 / 15.0)
        assert result.overlap_s == pytest.approx(5.0)
        assert result.shared_start == pytest.approx(5.0)
        assert result.shared_end == pytest.approx(10.0)

    def test_alignment_threshold(self) -> None:
        from vibesensor.processing.time_align import _ALIGNMENT_MIN_OVERLAP, compute_overlap

        # Create a case just above the threshold
        result = compute_overlap([0.0, 4.0], [10.0, 14.0])
        # Union: 0-14 = 14, overlap: 4-10 = 6 → ratio = 6/14 ≈ 0.43
        assert result.overlap_ratio < _ALIGNMENT_MIN_OVERLAP
        assert result.aligned is False

        # Create a case at or above threshold
        result2 = compute_overlap([0.0, 5.0], [10.0, 10.0])
        # Union: 0-10 = 10, overlap: 5-10 = 5 → ratio = 0.5
        assert result2.overlap_ratio >= _ALIGNMENT_MIN_OVERLAP
        assert result2.aligned is True

    def test_three_ranges(self) -> None:
        from vibesensor.processing.time_align import compute_overlap

        result = compute_overlap([0.0, 2.0, 4.0], [10.0, 12.0, 14.0])
        # Union: 0-14 = 14, shared: max(0,2,4)-min(10,12,14) = 4-10 = 6
        assert result.shared_start == pytest.approx(4.0)
        assert result.shared_end == pytest.approx(10.0)
        assert result.overlap_s == pytest.approx(6.0)


class TestAnalysisTimeRange:
    """Tests for the analysis time range computation."""

    def test_no_data(self) -> None:
        from vibesensor.processing.time_align import analysis_time_range

        result = analysis_time_range(
            count=0,
            last_ingest_mono_s=100.0,
            sample_rate_hz=1000,
            waveform_seconds=2,
            capacity=2000,
            last_t0_us=0,
            samples_since_t0=0,
        )
        assert result is None

    def test_no_timing(self) -> None:
        from vibesensor.processing.time_align import analysis_time_range

        result = analysis_time_range(
            count=100,
            last_ingest_mono_s=0.0,
            sample_rate_hz=1000,
            waveform_seconds=2,
            capacity=2000,
            last_t0_us=0,
            samples_since_t0=0,
        )
        assert result is None

    def test_zero_sample_rate(self) -> None:
        from vibesensor.processing.time_align import analysis_time_range

        result = analysis_time_range(
            count=100,
            last_ingest_mono_s=100.0,
            sample_rate_hz=0,
            waveform_seconds=2,
            capacity=2000,
            last_t0_us=0,
            samples_since_t0=0,
        )
        assert result is None

    def test_server_clock_path(self) -> None:
        from vibesensor.processing.time_align import analysis_time_range

        result = analysis_time_range(
            count=1000,
            last_ingest_mono_s=100.0,
            sample_rate_hz=1000,
            waveform_seconds=2,
            capacity=2000,
            last_t0_us=0,
            samples_since_t0=0,
        )
        assert result is not None
        start, end, synced = result
        assert synced is False
        assert end == pytest.approx(100.0)
        assert start == pytest.approx(99.0)  # 1000 samples / 1000 Hz = 1s window

    def test_sensor_clock_path(self) -> None:
        from vibesensor.processing.time_align import analysis_time_range

        result = analysis_time_range(
            count=1000,
            last_ingest_mono_s=100.0,
            sample_rate_hz=1000,
            waveform_seconds=2,
            capacity=2000,
            last_t0_us=5_000_000,  # 5 seconds in µs
            samples_since_t0=100,
        )
        assert result is not None
        start, end, synced = result
        assert synced is True
        # end_us = 5_000_000 + (100 * 1_000_000) // 1000 = 5_100_000
        # end_s = 5.1
        assert end == pytest.approx(5.1)

    def test_window_capped_by_capacity(self) -> None:
        from vibesensor.processing.time_align import analysis_time_range

        result = analysis_time_range(
            count=2000,
            last_ingest_mono_s=100.0,
            sample_rate_hz=1000,
            waveform_seconds=5,  # wants 5000 samples
            capacity=2000,  # but only 2000 capacity
            last_t0_us=0,
            samples_since_t0=0,
        )
        assert result is not None
        start, end, synced = result
        # Window should be 2000/1000 = 2s, not 5s
        assert (end - start) == pytest.approx(2.0)
