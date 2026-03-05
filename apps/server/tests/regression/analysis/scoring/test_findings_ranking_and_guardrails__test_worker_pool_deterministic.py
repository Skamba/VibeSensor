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


class TestWorkerPoolDeterministic:
    """Regression: test_worker_pool should use np.random.default_rng,
    not np.random.seed (global state mutation)."""

    def test_no_global_seed_in_source(self) -> None:
        import tests.app.test_worker_pool as mod

        source = inspect.getsource(mod)
        assert "np.random.seed" not in source, "Must use np.random.default_rng, not np.random.seed"
