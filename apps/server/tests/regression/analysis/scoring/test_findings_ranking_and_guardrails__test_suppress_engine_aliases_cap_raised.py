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


class TestSuppressEngineAliasesCapRaised:
    """Regression: _suppress_engine_aliases cap should allow more than 3."""

    def test_cap_allows_4_findings(self) -> None:
        findings = [
            (
                0.9 - i * 0.1,
                {
                    "suspected_source": "wheel/tire",
                    "confidence_0_to_1": 0.8 - i * 0.1,
                    "_ranking_score": 0.9 - i * 0.1,
                    "key": f"wheel_{i}",
                },
            )
            for i in range(4)
        ]
        result = _suppress_engine_aliases(findings)
        assert len(result) == 4, f"Expected 4 findings (was capped at 3), got {len(result)}"
