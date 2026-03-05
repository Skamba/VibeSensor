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

import inspect

import pytest

import vibesensor.analysis.findings.order_findings as order_findings_mod

_UNSEEDED_RANDOM_MODULES = [
    pytest.param("tests.processing.test_processing_extended", id="processing_extended"),
    pytest.param("tests.protocol.test_reset_buffer_flush", id="reset_buffer_flush"),
]


class TestNegligibleCapAligned:
    """Regression: negligible-strength confidence cap must not exceed
    TIER_B_CEILING (0.40)."""

    def test_order_cap_value_in_source(self) -> None:
        src = inspect.getsource(order_findings_mod)
        assert "min(confidence, 0.40)" in src, (
            "Negligible cap should be 0.40 (aligned with TIER_B_CEILING)"
        )
