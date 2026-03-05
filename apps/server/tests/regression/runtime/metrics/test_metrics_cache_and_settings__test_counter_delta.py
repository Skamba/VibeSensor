"""Metrics cache, settings rollback, and counter-delta regressions."""

from __future__ import annotations

from vibesensor.analysis.helpers import counter_delta


class TestCounterDelta:
    """Test the shared counter_delta helper extracted from findings/summary."""

    def test_empty_list(self) -> None:
        assert counter_delta([]) == 0

    def test_single_value(self) -> None:
        assert counter_delta([5.0]) == 0

    def test_monotonic_increase(self) -> None:
        assert counter_delta([0.0, 1.0, 3.0, 6.0]) == 6

    def test_reset_ignored(self) -> None:
        # Counter resets (decreases) should be ignored, only increases counted
        assert counter_delta([0.0, 5.0, 2.0, 7.0]) == 10  # 5 + 0 + 5

    def test_all_same_value(self) -> None:
        assert counter_delta([3.0, 3.0, 3.0]) == 0

    def test_negative_values(self) -> None:
        assert counter_delta([-2.0, 0.0, 3.0]) == 5  # 2 + 3

    def test_float_precision(self) -> None:
        result = counter_delta([0.0, 0.1, 0.3])
        assert result == 0  # int truncation of 0.3
