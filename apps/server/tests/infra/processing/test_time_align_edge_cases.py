"""Edge-case tests for vibesensor.infra.processing.time_align.

These complement the primary test file (test_processing_time_align.py) by
covering degenerate inputs and corner cases not handled there:

- ``analysis_time_range`` with zero / negative sample rate
- ``compute_overlap`` with a single zero-duration range
- ``analysis_time_range`` sensor-clock end-time advance via ``samples_since_t0``
"""

from __future__ import annotations

import pytest

from vibesensor.infra.processing.time_align import (
    analysis_time_range,
    compute_overlap,
)


class TestAnalysisTimeRangeEdgeCases:
    """Additional edge-case coverage for analysis_time_range."""

    def test_zero_sample_rate_returns_none(self) -> None:
        """sample_rate_hz=0 must return None to avoid division by zero."""
        result = analysis_time_range(
            count=100,
            last_ingest_mono_s=1000.0,
            sample_rate_hz=0,
            waveform_seconds=5.0,
            capacity=2048,
            last_t0_us=0,
            samples_since_t0=0,
        )
        assert result is None

    def test_negative_sample_rate_returns_none(self) -> None:
        """Negative sample rate is invalid and must also return None."""
        result = analysis_time_range(
            count=50,
            last_ingest_mono_s=1000.0,
            sample_rate_hz=-200,
            waveform_seconds=5.0,
            capacity=2048,
            last_t0_us=0,
            samples_since_t0=0,
        )
        assert result is None

    def test_sensor_clock_end_time_advances_by_samples_since_t0(self) -> None:
        """With last_t0_us set, end_s should advance by samples_since_t0/rate."""
        # 1 000 Hz sensor; t0 at exactly 1.0 s; 500 samples ingested since t0
        sr = 1000
        t0_us = 1_000_000  # 1.000 s
        samples_since_t0 = 500

        result = analysis_time_range(
            count=1000,
            # last_ingest_mono_s must be > 0 to pass the early guard;
            # the sensor-clock path ignores it when last_t0_us > 0.
            last_ingest_mono_s=999.0,
            sample_rate_hz=sr,
            waveform_seconds=1.0,
            capacity=2048,
            last_t0_us=t0_us,
            samples_since_t0=samples_since_t0,
        )
        assert result is not None
        start_s, end_s, synced = result
        assert synced is True
        # Expected end: 1.0 + (500 / 1000) = 1.5 s
        assert end_s == pytest.approx(1.5, abs=1e-6)
        # Duration is 1.0 s (waveform_seconds), so start = 0.5 s
        assert start_s == pytest.approx(0.5, abs=1e-6)


class TestComputeOverlapEdgeCases:
    """Additional edge-case coverage for compute_overlap."""

    def test_single_range_zero_duration_not_aligned(self) -> None:
        """A single sensor window with start == end has overlap_ratio 0."""
        result = compute_overlap([5.0], [5.0])
        assert result.overlap_ratio == pytest.approx(0.0)
        assert result.aligned is False
        assert result.overlap_s == pytest.approx(0.0)

    def test_many_identical_ranges_are_fully_aligned(self) -> None:
        """Five sensors with identical windows should be 100 % aligned."""
        starts = [0.0] * 5
        ends = [10.0] * 5
        result = compute_overlap(starts, ends)
        assert result.overlap_ratio == pytest.approx(1.0)
        assert result.aligned is True
        assert result.overlap_s == pytest.approx(10.0)

    def test_two_touching_but_not_overlapping_ranges(self) -> None:
        """Ranges that share only a single point have no practical overlap."""
        # [0, 5] and [5, 10]: union = 10, intersection = 0
        result = compute_overlap([0.0, 5.0], [5.0, 10.0])
        assert result.overlap_ratio == pytest.approx(0.0)
        assert result.aligned is False
