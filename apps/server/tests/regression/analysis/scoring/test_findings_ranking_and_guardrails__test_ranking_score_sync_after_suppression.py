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

from vibesensor.analysis.findings import _suppress_engine_aliases

_UNSEEDED_RANDOM_MODULES = [
    pytest.param("tests.processing.test_processing_extended", id="processing_extended"),
    pytest.param("tests.protocol.test_reset_buffer_flush", id="reset_buffer_flush"),
]


class TestRankingScoreSyncAfterSuppression:
    """Regression: _suppress_engine_aliases must update _ranking_score
    in the finding dict when suppressing confidence."""

    def test_ranking_score_updated(self) -> None:
        findings = [
            (
                0.8,
                {
                    "suspected_source": "wheel/tire",
                    "confidence_0_to_1": 0.6,
                    "_ranking_score": 0.8,
                    "key": "wheel_1",
                },
            ),
            (
                0.7,
                {
                    "suspected_source": "engine",
                    "confidence_0_to_1": 0.5,
                    "_ranking_score": 0.7,
                    "key": "engine_2",
                },
            ),
        ]
        result = _suppress_engine_aliases(findings)
        engine_findings = [f for f in result if f.get("suspected_source") == "engine"]
        for f in engine_findings:
            assert f["_ranking_score"] == pytest.approx(0.7 * 0.60, abs=1e-9), (
                "_ranking_score must be updated after suppression"
            )
