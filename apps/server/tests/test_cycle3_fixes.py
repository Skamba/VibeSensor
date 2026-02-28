"""Tests for Cycle 3 fixes:
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


class TestRankingScoreSyncAfterSuppression:
    """Regression: _suppress_engine_aliases must update _ranking_score
    in the finding dict when suppressing confidence."""

    def test_ranking_score_updated(self) -> None:
        from vibesensor.analysis.findings import _suppress_engine_aliases

        findings = [
            (0.8, {
                "suspected_source": "wheel/tire",
                "confidence_0_to_1": 0.6,
                "_ranking_score": 0.8,
                "key": "wheel_1",
            }),
            (0.7, {
                "suspected_source": "engine",
                "confidence_0_to_1": 0.5,
                "_ranking_score": 0.7,
                "key": "engine_2",
            }),
        ]
        result = _suppress_engine_aliases(findings)
        engine_findings = [
            f for f in result
            if f.get("suspected_source") == "engine"
        ]
        for f in engine_findings:
            # _ranking_score must match suppressed tuple score
            assert f["_ranking_score"] == pytest.approx(
                0.7 * 0.60, abs=1e-9
            ), "_ranking_score must be updated after suppression"


class TestNegligibleCapAligned:
    """Regression: negligible-strength confidence cap must not exceed
    TIER_B_CEILING (0.40)."""

    def test_cap_value_in_source(self) -> None:
        import vibesensor.analysis.findings as fmod

        src = inspect.getsource(fmod)
        # The line that applies the negligible cap must use 0.40
        assert "min(confidence, 0.40)" in src, (
            "Negligible cap should be 0.40 (aligned with TIER_B_CEILING)"
        )


class TestSteadySpeedUsesAND:
    """Regression: steady_speed must require BOTH low stddev AND low range."""

    def test_high_stddev_low_range_not_steady(self) -> None:
        from vibesensor.analysis.helpers import _speed_stats

        # Alternating values: stddev > 2 but range could be small
        # This produces stddev ~1.98*sqrt(n/(n-1)) ≈ 3.95
        speeds = [50.0 + (i % 2) * 7.9 for i in range(50)]
        stats = _speed_stats(speeds)
        assert not stats["steady_speed"], (
            "High stddev should not be steady even with low range"
        )

    def test_both_low_is_steady(self) -> None:
        from vibesensor.analysis.helpers import _speed_stats

        speeds = [60.0 + 0.1 * (i % 3) for i in range(50)]
        stats = _speed_stats(speeds)
        assert stats["steady_speed"], "Both low stddev and range → steady"


class TestHistoryDbCloseLocked:
    """Regression: HistoryDB.close() must acquire the lock."""

    def test_close_acquires_lock(self) -> None:
        source = inspect.getsource(
            __import__(
                "vibesensor.history_db",
                fromlist=["HistoryDB"],
            ).HistoryDB.close
        )
        assert "self._lock" in source, "close() must use self._lock"


class TestJsonlRejectsNan:
    """Regression: JSONL serialization must reject NaN/Infinity."""

    def test_nan_raises(self) -> None:
        from vibesensor.runlog import append_jsonl_records

        record = {"value": float("nan")}
        with pytest.raises(ValueError):
            append_jsonl_records(
                path=pytest.importorskip("pathlib").Path("/dev/null"),
                records=[record],
            )

    def test_inf_raises(self) -> None:
        from vibesensor.runlog import append_jsonl_records

        record = {"value": float("inf")}
        with pytest.raises(ValueError):
            append_jsonl_records(
                path=pytest.importorskip("pathlib").Path("/dev/null"),
                records=[record],
            )


class TestIdentifyClientNormalized:
    """Regression: identify_client must normalize client_id before use."""

    def test_normalize_call_in_source(self) -> None:
        from vibesensor.api import create_router

        source = inspect.getsource(create_router)
        # Find the identify_client function body
        idx = source.index("identify_client")
        snippet = source[idx : idx + 500]
        assert "_normalize_client_id_or_400" in snippet, (
            "identify_client must call _normalize_client_id_or_400"
        )


class TestSuppressEngineAliasesCapRaised:
    """Regression: _suppress_engine_aliases cap should allow more than 3."""

    def test_cap_allows_4_findings(self) -> None:
        from vibesensor.analysis.findings import _suppress_engine_aliases

        findings = [
            (0.9 - i * 0.1, {
                "suspected_source": "wheel/tire",
                "confidence_0_to_1": 0.8 - i * 0.1,
                "_ranking_score": 0.9 - i * 0.1,
                "key": f"wheel_{i}",
            })
            for i in range(4)
        ]
        result = _suppress_engine_aliases(findings)
        assert len(result) == 4, (
            f"Expected 4 findings (was capped at 3), got {len(result)}"
        )


class TestWorkerPoolDeterministic:
    """Regression: test_worker_pool should use np.random.default_rng,
    not np.random.seed (global state mutation)."""

    def test_no_global_seed_in_source(self) -> None:
        import tests.test_worker_pool as mod

        source = inspect.getsource(mod)
        assert "np.random.seed" not in source, (
            "Must use np.random.default_rng, not np.random.seed"
        )
