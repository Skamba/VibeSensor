"""Tests for snapshot_builder: cache-hit decisions and window-size computation."""

from __future__ import annotations

from vibesensor.infra.processing.models import CachedMetricsHit
from vibesensor.infra.processing.snapshot_builder import (
    SnapshotWindow,
    check_cache_hit,
    compute_snapshot_window,
)


class TestCheckCacheHit:
    """Cover snapshot-builder cache-hit eligibility based on generations and sample rate."""

    def test_cache_hit_when_generations_and_rate_match(self) -> None:
        metrics = {"rms_x": 0.5}
        result = check_cache_hit(
            ingest_generation=3,
            compute_generation=3,
            compute_sample_rate_hz=200,
            effective_sample_rate_hz=200,
            latest_metrics=metrics,
        )
        assert isinstance(result, CachedMetricsHit)
        assert result.metrics is metrics

    def test_cache_miss_when_generation_differs(self) -> None:
        result = check_cache_hit(
            ingest_generation=4,
            compute_generation=3,
            compute_sample_rate_hz=200,
            effective_sample_rate_hz=200,
            latest_metrics={"rms_x": 0.5},
        )
        assert result is None

    def test_cache_miss_when_sample_rate_differs(self) -> None:
        result = check_cache_hit(
            ingest_generation=3,
            compute_generation=3,
            compute_sample_rate_hz=200,
            effective_sample_rate_hz=500,
            latest_metrics={"rms_x": 0.5},
        )
        assert result is None

    def test_cache_miss_when_never_computed(self) -> None:
        result = check_cache_hit(
            ingest_generation=0,
            compute_generation=-1,
            compute_sample_rate_hz=0,
            effective_sample_rate_hz=200,
            latest_metrics={},
        )
        assert result is None

    def test_cache_hit_with_empty_metrics(self) -> None:
        result = check_cache_hit(
            ingest_generation=1,
            compute_generation=1,
            compute_sample_rate_hz=100,
            effective_sample_rate_hz=100,
            latest_metrics={},
        )
        assert isinstance(result, CachedMetricsHit)
        assert result.metrics == {}


class TestComputeSnapshotWindow:
    """Exercise snapshot-window sizing and whether a separate FFT block is needed."""

    def test_basic_window_smaller_than_count(self) -> None:
        result = compute_snapshot_window(
            count=1000,
            capacity=2000,
            sample_rate_hz=200,
            waveform_seconds=2,
            fft_n=256,
        )
        assert result == SnapshotWindow(n_time=400, needs_separate_fft_block=False)

    def test_count_limits_window(self) -> None:
        result = compute_snapshot_window(
            count=50,
            capacity=2000,
            sample_rate_hz=200,
            waveform_seconds=2,
            fft_n=256,
        )
        assert result.n_time == 50

    def test_capacity_limits_window(self) -> None:
        result = compute_snapshot_window(
            count=500,
            capacity=100,
            sample_rate_hz=200,
            waveform_seconds=2,
            fft_n=256,
        )
        assert result.n_time == 100

    def test_needs_separate_fft_block_when_n_time_smaller(self) -> None:
        # count >= fft_n and n_time < fft_n → needs separate fft block
        result = compute_snapshot_window(
            count=512,
            capacity=512,
            sample_rate_hz=100,
            waveform_seconds=1,
            fft_n=256,
        )
        assert result.n_time == 100
        assert result.needs_separate_fft_block is True

    def test_separate_fft_block_true_when_small_window_large_count(self) -> None:
        # count >= fft_n but n_time < fft_n → needs separate fft block
        result = compute_snapshot_window(
            count=512,
            capacity=512,
            sample_rate_hz=10,
            waveform_seconds=2,
            fft_n=256,
        )
        assert result.n_time == 20
        assert result.needs_separate_fft_block is True

    def test_no_separate_fft_block_when_n_time_ge_fft_n(self) -> None:
        result = compute_snapshot_window(
            count=1000,
            capacity=1000,
            sample_rate_hz=200,
            waveform_seconds=2,
            fft_n=256,
        )
        assert result.n_time == 400
        assert result.needs_separate_fft_block is False

    def test_no_separate_fft_block_when_count_lt_fft_n(self) -> None:
        result = compute_snapshot_window(
            count=100,
            capacity=1000,
            sample_rate_hz=10,
            waveform_seconds=2,
            fft_n=256,
        )
        assert result.n_time == 20
        assert result.needs_separate_fft_block is False

    def test_minimum_window_is_one(self) -> None:
        result = compute_snapshot_window(
            count=5,
            capacity=100,
            sample_rate_hz=1,
            waveform_seconds=0,
            fft_n=256,
        )
        assert result.n_time >= 1
