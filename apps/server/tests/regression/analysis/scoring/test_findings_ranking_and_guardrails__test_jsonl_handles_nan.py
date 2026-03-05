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

from pathlib import Path

import pytest

from vibesensor.runlog import append_jsonl_records

_UNSEEDED_RANDOM_MODULES = [
    pytest.param("tests.processing.test_processing_extended", id="processing_extended"),
    pytest.param("tests.protocol.test_reset_buffer_flush", id="reset_buffer_flush"),
]


class TestJsonlHandlesNan:
    """Regression: JSONL serialization must handle NaN/Infinity gracefully."""

    @pytest.mark.parametrize(
        "value, expected_text",
        [
            pytest.param(float("nan"), "NaN", id="nan"),
            pytest.param(float("inf"), "Infinity", id="inf"),
        ],
    )
    def test_non_finite_falls_back(self, tmp_path: Path, value: float, expected_text: str) -> None:
        out = tmp_path / "out.jsonl"
        append_jsonl_records(path=out, records=[{"value": value}])
        assert expected_text in out.read_text()
