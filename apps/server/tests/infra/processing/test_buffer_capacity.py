"""Tests for buffer_capacity: overflow, clamping, and resize policy."""

from __future__ import annotations

from vibesensor.infra.processing.buffer_capacity import (
    MAX_CLIENT_SAMPLE_RATE_HZ,
    ClampedRate,
    OverflowResult,
    clamp_sample_rate,
    compute_resize_capacity,
    evaluate_overflow,
)


class TestEvaluateOverflow:
    def test_chunk_fits_in_capacity(self) -> None:
        result = evaluate_overflow(100, 500)
        assert result == OverflowResult(keep_count=100, drop_count=0, start_offset=0)

    def test_chunk_exactly_fills_capacity(self) -> None:
        result = evaluate_overflow(500, 500)
        assert result == OverflowResult(keep_count=500, drop_count=0, start_offset=0)

    def test_chunk_exceeds_capacity(self) -> None:
        result = evaluate_overflow(700, 500)
        assert result == OverflowResult(keep_count=500, drop_count=200, start_offset=200)

    def test_single_sample_capacity(self) -> None:
        result = evaluate_overflow(10, 1)
        assert result == OverflowResult(keep_count=1, drop_count=9, start_offset=9)

    def test_zero_chunk_size(self) -> None:
        result = evaluate_overflow(0, 500)
        assert result == OverflowResult(keep_count=0, drop_count=0, start_offset=0)

    def test_large_overflow(self) -> None:
        result = evaluate_overflow(10_000, 256)
        assert result.keep_count == 256
        assert result.drop_count == 10_000 - 256
        assert result.start_offset == 10_000 - 256


class TestClampSampleRate:
    def test_rate_within_range(self) -> None:
        result = clamp_sample_rate(500)
        assert result == ClampedRate(rate_hz=500, was_clamped=False)

    def test_rate_at_maximum(self) -> None:
        result = clamp_sample_rate(MAX_CLIENT_SAMPLE_RATE_HZ)
        assert result == ClampedRate(rate_hz=MAX_CLIENT_SAMPLE_RATE_HZ, was_clamped=False)

    def test_rate_exceeds_maximum(self) -> None:
        result = clamp_sample_rate(MAX_CLIENT_SAMPLE_RATE_HZ + 1000)
        assert result == ClampedRate(rate_hz=MAX_CLIENT_SAMPLE_RATE_HZ, was_clamped=True)

    def test_rate_zero_clamped_to_one(self) -> None:
        result = clamp_sample_rate(0)
        assert result == ClampedRate(rate_hz=1, was_clamped=True)

    def test_negative_rate_clamped_to_one(self) -> None:
        result = clamp_sample_rate(-100)
        assert result == ClampedRate(rate_hz=1, was_clamped=True)

    def test_rate_one(self) -> None:
        result = clamp_sample_rate(1)
        assert result == ClampedRate(rate_hz=1, was_clamped=False)

    def test_custom_max_rate(self) -> None:
        result = clamp_sample_rate(200, max_rate=100)
        assert result == ClampedRate(rate_hz=100, was_clamped=True)


class TestComputeResizeCapacity:
    def test_basic_computation(self) -> None:
        assert compute_resize_capacity(500, 2) == 1000

    def test_unit_seconds(self) -> None:
        assert compute_resize_capacity(1000, 1) == 1000

    def test_large_rate_and_window(self) -> None:
        assert compute_resize_capacity(4096, 10) == 40960
