"""Tests for confidence_label."""

from __future__ import annotations

from vibesensor.analysis.top_cause_selection import confidence_label

# ---------------------------------------------------------------------------
# Confidence label
# ---------------------------------------------------------------------------


class TestConfidenceLabel:
    def test_high(self) -> None:
        label_key, tone, pct = confidence_label(0.80)
        assert label_key == "CONFIDENCE_HIGH"
        assert tone == "success"
        assert pct == "80%"

    def test_medium(self) -> None:
        label_key, tone, _pct = confidence_label(0.50)
        assert label_key == "CONFIDENCE_MEDIUM"
        assert tone == "warn"

    def test_low(self) -> None:
        label_key, tone, _pct = confidence_label(0.10)
        assert label_key == "CONFIDENCE_LOW"
        assert tone == "neutral"

    def test_none_treated_as_zero(self) -> None:
        label_key, _tone, pct = confidence_label(None)
        assert label_key == "CONFIDENCE_LOW"
        assert pct == "0%"
