# ruff: noqa: E402
from __future__ import annotations

"""Findings ranking and analysis guardrail regressions:
- _ranking_score synced after engine alias suppression
- negligible confidence cap aligned with TIER_B_CEILING (0.40)
- steady_speed uses AND (not OR) for stddev and range
- HistoryDB.close() acquires lock
- JSONL serialization rejects NaN
- identify_client normalizes client_id
- _suppress_engine_aliases cap raised to 5
"""


import inspect
from pathlib import Path

import pytest

from vibesensor.analysis.helpers import _speed_stats
from vibesensor.analysis.order_analysis import (
    suppress_engine_aliases as _suppress_engine_aliases,
)
from vibesensor.routes.clients import create_client_routes
from vibesensor.runlog import append_jsonl_records


class TestRankingScoreSyncAfterSuppression:
    """Regression: _suppress_engine_aliases must update _ranking_score
    in the finding dict when suppressing confidence.
    """

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
                "vibesensor.history_db",
                fromlist=["HistoryDB"],
            ).HistoryDB.close,
        )
        assert "self._lock" in source, "close() must use self._lock"


class TestJsonlHandlesNan:
    """Regression: JSONL serialization must handle NaN/Infinity gracefully.

    Non-finite floats must be sanitised to JSON ``null`` so the output is
    always valid JSON.  Bare NaN/Infinity (produced by allow_nan=True) are
    invalid JSON and break downstream parsers.
    """

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(float("nan"), id="nan"),
            pytest.param(float("inf"), id="inf"),
        ],
    )
    def test_non_finite_falls_back(self, tmp_path: Path, value: float) -> None:
        out = tmp_path / "out.jsonl"
        append_jsonl_records(path=out, records=[{"value": value}])
        text = out.read_text()
        # Must be valid JSON — json.loads raises ValueError for bare NaN/Infinity
        import json as _json

        parsed = _json.loads(text.strip())
        assert parsed["value"] is None, (
            f"Non-finite float must serialise as null, got {parsed['value']!r}"
        )


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
                    "confidence_0_to_1": 0.8 - i * 0.1,
                    "_ranking_score": 0.9 - i * 0.1,
                    "key": f"wheel_{i}",
                },
            )
            for i in range(4)
        ]
        result = _suppress_engine_aliases(findings)
        assert len(result) == 4, f"Expected 4 findings (was capped at 3), got {len(result)}"
