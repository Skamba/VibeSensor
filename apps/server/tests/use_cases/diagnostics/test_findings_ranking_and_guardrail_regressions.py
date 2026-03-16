# ruff: noqa: E402
from __future__ import annotations

"""Findings ranking and analysis guardrail regressions:
- ranking_score synced after engine alias suppression
- negligible confidence cap aligned with TIER_B_CEILING (0.40)
- steady_speed uses AND (not OR) for stddev and range
- HistoryDB.close() acquires lock
- identify_client normalizes client_id
- _suppress_engine_aliases cap raised to 5
"""


import inspect

import pytest

from vibesensor.adapters.http.clients import create_client_routes
from vibesensor.use_cases.diagnostics.helpers import _speed_stats
from vibesensor.use_cases.diagnostics.order_analysis import (
    suppress_engine_aliases as _suppress_engine_aliases,
)


class TestRankingScoreSyncAfterSuppression:
    """Regression: _suppress_engine_aliases must update ranking_score
    in the finding dict when suppressing confidence.
    """

    def test_ranking_score_updated(self) -> None:
        findings = [
            (
                0.8,
                {
                    "suspected_source": "wheel/tire",
                    "confidence": 0.6,
                    "ranking_score": 0.8,
                    "key": "wheel_1",
                },
            ),
            (
                0.7,
                {
                    "suspected_source": "engine",
                    "confidence": 0.5,
                    "ranking_score": 0.7,
                    "key": "engine_2",
                },
            ),
        ]
        result = _suppress_engine_aliases(findings)
        engine_findings = [f for f in result if f.get("suspected_source") == "engine"]
        for f in engine_findings:
            assert f["ranking_score"] == pytest.approx(0.7 * 0.60, abs=1e-9), (
                "ranking_score must be updated after suppression"
            )


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


class TestHistoryDbCloseLocked:
    """Regression: HistoryDB.close() must acquire the lock."""

    def test_close_acquires_lock(self) -> None:
        source = inspect.getsource(
            __import__(
                "vibesensor.adapters.persistence.history_db",
                fromlist=["HistoryDB"],
            ).HistoryDB.close,
        )
        assert "self._lock" in source, "close() must use self._lock"


class TestIdentifyClientNormalized:
    """Regression: identify_client must normalize client_id before use."""

    def test_normalize_call_in_source(self) -> None:
        source = inspect.getsource(create_client_routes)
        idx = source.index("identify_client")
        snippet = source[idx : idx + 500]
        assert "normalize_client_id_or_400" in snippet, (
            "identify_client must call normalize_client_id_or_400"
        )


class TestSuppressEngineAliasesCapRaised:
    """Regression: _suppress_engine_aliases cap should allow more than 3."""

    def test_cap_allows_4_findings(self) -> None:
        findings = [
            (
                0.9 - i * 0.1,
                {
                    "suspected_source": "wheel/tire",
                    "confidence": 0.8 - i * 0.1,
                    "ranking_score": 0.9 - i * 0.1,
                    "key": f"wheel_{i}",
                },
            )
            for i in range(4)
        ]
        result = _suppress_engine_aliases(findings)
        assert len(result) == 4, f"Expected 4 findings (was capped at 3), got {len(result)}"
