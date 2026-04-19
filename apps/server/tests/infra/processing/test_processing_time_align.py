"""Unit tests for vibesensor.infra.processing.time_align pure functions.

These tests validate the time-alignment utilities extracted from the
monolithic SignalProcessor class.  All functions under test are pure
(no shared state), enabling precise, deterministic testing.
"""

from __future__ import annotations

import pytest

from vibesensor.infra.processing.time_align import (
    _ALIGNMENT_MIN_OVERLAP,
    analysis_time_range,
    compute_overlap,
)


class TestComputeOverlap:
    """Tests for the intersection-over-union overlap computation."""

    @pytest.mark.parametrize(
        (
            "starts",
            "ends",
            "expected_ratio",
            "expected_aligned",
            "expected_shared_start",
            "expected_shared_end",
            "expected_overlap_s",
        ),
        [
            pytest.param([], [], 0.0, False, 0.0, 0.0, 0.0, id="empty-inputs"),
            pytest.param(
                [1.0],
                [2.0, 3.0],
                0.0,
                False,
                0.0,
                0.0,
                0.0,
                id="mismatched-lengths",
            ),
            pytest.param(
                [0.0, 0.0],
                [10.0, 10.0],
                1.0,
                True,
                0.0,
                10.0,
                10.0,
                id="identical-ranges",
            ),
            pytest.param(
                [0.0, 20.0],
                [10.0, 30.0],
                0.0,
                False,
                20.0,
                10.0,
                0.0,
                id="no-overlap",
            ),
            pytest.param(
                [0.0, 5.0],
                [10.0, 15.0],
                5.0 / 15.0,
                False,
                5.0,
                10.0,
                5.0,
                id="partial-overlap",
            ),
            pytest.param(
                [0.0, 2.0, 4.0],
                [10.0, 12.0, 14.0],
                6.0 / 14.0,
                False,
                4.0,
                10.0,
                6.0,
                id="three-ranges",
            ),
        ],
    )
    def test_compute_overlap_cases(
        self,
        starts: list[float],
        ends: list[float],
        expected_ratio: float,
        expected_aligned: bool,
        expected_shared_start: float,
        expected_shared_end: float,
        expected_overlap_s: float,
    ) -> None:
        result = compute_overlap(starts, ends)

        assert result.overlap_ratio == pytest.approx(expected_ratio)
        assert result.aligned is expected_aligned
        assert result.shared_start == pytest.approx(expected_shared_start)
        assert result.shared_end == pytest.approx(expected_shared_end)
        assert result.overlap_s == pytest.approx(expected_overlap_s)

    @pytest.mark.parametrize(
        ("starts", "ends", "expected_ratio", "expected_aligned"),
        [
            pytest.param([0.0, 5.000001], [10.0, 10.0], 0.4999999, False, id="just-below"),
            pytest.param([0.0, 5.0], [10.0, 10.0], 0.5, True, id="exact-threshold"),
            pytest.param([0.0, 4.999999], [10.0, 10.0], 0.5000001, True, id="just-above"),
        ],
    )
    def test_alignment_threshold_boundaries(
        self,
        starts: list[float],
        ends: list[float],
        expected_ratio: float,
        expected_aligned: bool,
    ) -> None:
        result = compute_overlap(starts, ends)

        assert result.overlap_ratio == pytest.approx(expected_ratio)
        assert result.aligned is expected_aligned
        if expected_aligned:
            assert result.overlap_ratio >= _ALIGNMENT_MIN_OVERLAP
        else:
            assert result.overlap_ratio < _ALIGNMENT_MIN_OVERLAP


_ATR_DEFAULTS: dict[str, object] = {
    "count": 1000,
    "last_ingest_mono_s": 100.0,
    "sample_rate_hz": 1000,
    "waveform_seconds": 2,
    "capacity": 2000,
    "last_t0_us": 0,
    "samples_since_t0": 0,
}


def _atr(**overrides: object) -> tuple[float, float, bool] | None:
    """Call ``analysis_time_range`` with shared defaults + overrides."""
    return analysis_time_range(**{**_ATR_DEFAULTS, **overrides})


class TestAnalysisTimeRange:
    """Tests for the analysis time range computation."""

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"count": 0}, id="no_data"),
            pytest.param({"count": 100, "last_ingest_mono_s": 0.0}, id="no_timing"),
            pytest.param({"count": 100, "sample_rate_hz": 0}, id="zero_sample_rate"),
        ],
    )
    def test_returns_none(self, overrides: dict[str, object]) -> None:
        assert _atr(**overrides) is None

    def test_server_clock_path_preserves_partial_window_and_drift(self) -> None:
        result = _atr(
            count=450,
            last_ingest_mono_s=100.123,
        )
        assert result is not None
        start, end, synced = result
        assert synced is False
        assert end == pytest.approx(100.123)
        assert start == pytest.approx(99.673)

    def test_server_clock_path_preserves_off_by_one_sample_duration(self) -> None:
        result = _atr(count=1001)
        assert result is not None
        start, end, synced = result
        assert synced is False
        assert end == pytest.approx(100.0)
        assert start == pytest.approx(98.999)
        assert (end - start) == pytest.approx(1.001)

    def test_sensor_clock_path(self) -> None:
        result = _atr(
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
        result = _atr(
            count=2000,
            waveform_seconds=5,  # wants 5000 samples
            capacity=2000,  # but only 2000 capacity
        )
        assert result is not None
        start, end, synced = result
        # Window should be 2000/1000 = 2s, not 5s
        assert (end - start) == pytest.approx(2.0)

    @pytest.mark.parametrize("last_ingest_mono_s", [0.0, -1.0])
    def test_bad_timestamp_combinations_return_none(
        self,
        last_ingest_mono_s: float,
    ) -> None:
        assert (
            _atr(
                count=100,
                last_ingest_mono_s=last_ingest_mono_s,
                last_t0_us=5_000_000,
                samples_since_t0=450,
            )
            is None
        )
