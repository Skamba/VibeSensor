"""Tests for buffer_capacity: overflow, clamping, and resize policy."""

from __future__ import annotations

import pytest

from vibesensor.infra.processing.buffer_capacity import (
    MAX_CLIENT_SAMPLE_RATE_HZ,
    ClampedRate,
    OverflowResult,
    clamp_sample_rate,
    compute_resize_capacity,
    evaluate_overflow,
)


class TestEvaluateOverflow:
    @pytest.mark.parametrize(
        ("chunk_size", "capacity", "expected"),
        [
            (100, 500, OverflowResult(keep_count=100, drop_count=0, start_offset=0)),
            (500, 500, OverflowResult(keep_count=500, drop_count=0, start_offset=0)),
            (700, 500, OverflowResult(keep_count=500, drop_count=200, start_offset=200)),
            (10, 1, OverflowResult(keep_count=1, drop_count=9, start_offset=9)),
            (0, 500, OverflowResult(keep_count=0, drop_count=0, start_offset=0)),
        ],
    )
    def test_expected_overflow_result(
        self,
        chunk_size: int,
        capacity: int,
        expected: OverflowResult,
    ) -> None:
        result = evaluate_overflow(chunk_size, capacity)
        assert result == expected

    def test_large_overflow(self) -> None:
        result = evaluate_overflow(10_000, 256)
        assert result.keep_count == 256
        assert result.drop_count == 10_000 - 256
        assert result.start_offset == 10_000 - 256


class TestClampSampleRate:
    @pytest.mark.parametrize(
        ("rate_hz", "max_rate", "expected"),
        [
            (500, MAX_CLIENT_SAMPLE_RATE_HZ, ClampedRate(rate_hz=500, was_clamped=False)),
            (
                MAX_CLIENT_SAMPLE_RATE_HZ,
                MAX_CLIENT_SAMPLE_RATE_HZ,
                ClampedRate(rate_hz=MAX_CLIENT_SAMPLE_RATE_HZ, was_clamped=False),
            ),
            (
                MAX_CLIENT_SAMPLE_RATE_HZ + 1000,
                MAX_CLIENT_SAMPLE_RATE_HZ,
                ClampedRate(rate_hz=MAX_CLIENT_SAMPLE_RATE_HZ, was_clamped=True),
            ),
            (0, MAX_CLIENT_SAMPLE_RATE_HZ, ClampedRate(rate_hz=1, was_clamped=True)),
            (-100, MAX_CLIENT_SAMPLE_RATE_HZ, ClampedRate(rate_hz=1, was_clamped=True)),
            (1, MAX_CLIENT_SAMPLE_RATE_HZ, ClampedRate(rate_hz=1, was_clamped=False)),
            (200, 100, ClampedRate(rate_hz=100, was_clamped=True)),
        ],
    )
    def test_expected_clamped_rate(
        self,
        rate_hz: int,
        max_rate: int,
        expected: ClampedRate,
    ) -> None:
        result = clamp_sample_rate(rate_hz, max_rate=max_rate)
        assert result == expected


class TestComputeResizeCapacity:
    def test_basic_computation(self) -> None:
        assert compute_resize_capacity(500, 2) == 1000

    def test_unit_seconds(self) -> None:
        assert compute_resize_capacity(1000, 1) == 1000

    def test_large_rate_and_window(self) -> None:
        assert compute_resize_capacity(4096, 10) == 40960
