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

from vibesensor.routes.clients import create_client_routes

_UNSEEDED_RANDOM_MODULES = [
    pytest.param("tests.processing.test_processing_extended", id="processing_extended"),
    pytest.param("tests.protocol.test_reset_buffer_flush", id="reset_buffer_flush"),
]


class TestIdentifyClientNormalized:
    """Regression: identify_client must normalize client_id before use."""

    def test_normalize_call_in_source(self) -> None:
        source = inspect.getsource(create_client_routes)
        idx = source.index("identify_client")
        snippet = source[idx : idx + 500]
        assert "normalize_client_id_or_400" in snippet, (
            "identify_client must call normalize_client_id_or_400"
        )
