"""Findings ranking and analysis guardrail regressions:
- _ranking_score synced after engine alias suppression
- negligible confidence cap aligned with TIER_B_CEILING (0.40)
- steady_speed uses AND (not OR) for stddev and range
- HistoryDB.close() acquires lock
- JSONL serialization rejects NaN
- identify_client normalizes client_id
- _suppress_engine_aliases cap raised to 5
"""

from __future__ import annotations

import pytest

from vibesensor.analysis.helpers import _speed_stats

_UNSEEDED_RANDOM_MODULES = [
    pytest.param("tests.processing.test_processing_extended", id="processing_extended"),
    pytest.param("tests.protocol.test_reset_buffer_flush", id="reset_buffer_flush"),
]


class TestSteadySpeedUsesAND:
    """Regression: steady_speed must require BOTH low stddev AND low range."""

    def test_high_stddev_low_range_not_steady(self) -> None:
        speeds = [50.0 + (i % 2) * 7.9 for i in range(50)]
        assert not _speed_stats(speeds)["steady_speed"], (
            "High stddev should not be steady even with low range"
        )

    def test_both_low_is_steady(self) -> None:
        speeds = [60.0 + 0.1 * (i % 3) for i in range(50)]
        assert _speed_stats(speeds)["steady_speed"], "Both low stddev and range → steady"
