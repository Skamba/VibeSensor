"""Unit tests for pure analysis entry helpers.

Covers:
- confidence_label: label/tone/pct_text for 0-1 confidence value
- normalize_lang: minimal language normalisation for summary building
- select_top_causes: grouping, drop-off, max_causes

These functions are exercised indirectly by the full pipeline but were
missing direct unit tests that pin their contracts.
"""

from __future__ import annotations

import pytest

from vibesensor.analysis.strength_labels import (
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
)
from vibesensor.analysis.top_cause_selection import confidence_label, select_top_causes
from vibesensor.report_i18n import normalize_lang

# ---------------------------------------------------------------------------
# confidence_label
# ---------------------------------------------------------------------------


class TestConfidenceLabel:
    """Direct unit tests for confidence_label pure function."""

    def test_high_threshold_yields_success_tone(self) -> None:
        """Conf >= HIGH_THRESHOLD → CONFIDENCE_HIGH and 'success' tone."""
        label, tone, pct = confidence_label(CONFIDENCE_HIGH_THRESHOLD)
        assert label == "CONFIDENCE_HIGH"
        assert tone == "success"

    def test_medium_threshold_yields_warn_tone(self) -> None:
        """Conf in [MEDIUM, HIGH) → CONFIDENCE_MEDIUM and 'warn' tone."""
        mid = (CONFIDENCE_MEDIUM_THRESHOLD + CONFIDENCE_HIGH_THRESHOLD) / 2
        label, tone, _ = confidence_label(mid)
        assert label == "CONFIDENCE_MEDIUM"
        assert tone == "warn"

    def test_below_medium_yields_neutral_tone(self) -> None:
        """Conf < MEDIUM_THRESHOLD → CONFIDENCE_LOW and 'neutral' tone."""
        label, tone, _ = confidence_label(CONFIDENCE_MEDIUM_THRESHOLD - 0.01)
        assert label == "CONFIDENCE_LOW"
        assert tone == "neutral"

    def test_none_input_treated_as_zero(self) -> None:
        """None confidence falls back to 0 → CONFIDENCE_LOW."""
        label, tone, pct = confidence_label(None)
        assert label == "CONFIDENCE_LOW"
        assert pct == "0%"

    def test_pct_text_format_is_integer_percent(self) -> None:
        """pct_text should be e.g. '82%', not '0.82%' or '82.0%'."""
        _, _, pct = confidence_label(0.82)
        assert pct == "82%"

    def test_pct_text_clamps_to_100(self) -> None:
        """Values > 1.0 should yield '100%', not '150%'."""
        _, _, pct = confidence_label(1.5)
        assert pct == "100%"

    def test_return_type_is_three_strings(self) -> None:
        """Return value must be a 3-tuple of str."""
        result = confidence_label(0.5)
        assert len(result) == 3
        assert all(isinstance(v, str) for v in result)

    def test_negligible_band_caps_high_to_medium(self) -> None:
        """strength_band_key='negligible' must reduce HIGH → MEDIUM."""
        label, tone, _ = confidence_label(
            CONFIDENCE_HIGH_THRESHOLD + 0.05,
            strength_band_key="negligible",
        )
        assert label == "CONFIDENCE_MEDIUM"
        assert tone == "warn"

    def test_negligible_band_does_not_affect_medium(self) -> None:
        """strength_band_key='negligible' only caps HIGH, not MEDIUM already."""
        mid = (CONFIDENCE_MEDIUM_THRESHOLD + CONFIDENCE_HIGH_THRESHOLD) / 2
        label, tone, _ = confidence_label(mid, strength_band_key="negligible")
        assert label == "CONFIDENCE_MEDIUM"

    def test_non_negligible_band_leaves_high_intact(self) -> None:
        """An unrelated band key must not suppress a HIGH label."""
        label, tone, _ = confidence_label(
            CONFIDENCE_HIGH_THRESHOLD + 0.05,
            strength_band_key="strong",
        )
        assert label == "CONFIDENCE_HIGH"


# ---------------------------------------------------------------------------
# normalize_lang
# ---------------------------------------------------------------------------


class TestNormalizeLangInSummary:
    """Tests for the normalize_lang helper used by summary building.

    This is a separate implementation from vibesensor.report_i18n.normalize_lang
    and must behave consistently.
    """

    @pytest.mark.parametrize(
        "input_lang",
        ["en", "EN", "english", "", None, "fr", 42],
        ids=["en", "EN_upper", "long_en", "empty", "none", "fr_defaults", "int"],
    )
    def test_non_nl_returns_en(self, input_lang: object) -> None:
        assert normalize_lang(input_lang) == "en"

    @pytest.mark.parametrize(
        "input_lang",
        ["nl", "NL", "nl-NL", "nl_BE"],
        ids=["nl_lower", "NL_upper", "nl-NL", "nl_BE"],
    )
    def test_nl_prefix_returns_nl(self, input_lang: str) -> None:
        assert normalize_lang(input_lang) == "nl"


# ---------------------------------------------------------------------------
# select_top_causes
# ---------------------------------------------------------------------------


def _make_finding(
    source: str,
    confidence: float,
    finding_id: str = "F_WHEEL",
    severity: str = "diagnostic",
) -> dict:
    return {
        "finding_id": finding_id,
        "suspected_source": source,
        "confidence": confidence,
        "severity": severity,
    }


class TestSelectTopCauses:
    """Direct unit tests for select_top_causes grouping and drop-off."""

    def test_empty_findings_returns_empty(self) -> None:
        assert select_top_causes([]) == []

    def test_below_min_confidence_findings_excluded(self) -> None:
        """Findings below ORDER_MIN_CONFIDENCE (0.25) must be filtered."""
        findings = [_make_finding("wheel", 0.10)]
        assert select_top_causes(findings) == []

    def test_info_severity_excluded(self) -> None:
        """Info-severity findings must not appear in top causes."""
        findings = [_make_finding("wheel", 0.90, severity="info")]
        assert select_top_causes(findings) == []

    def test_ref_finding_excluded(self) -> None:
        """Findings whose ID starts with REF_ must be excluded."""
        findings = [_make_finding("baseline", 0.95, finding_id="REF_BASELINE")]
        assert select_top_causes(findings) == []

    def test_respects_max_causes_limit(self) -> None:
        """At most max_causes findings are returned."""
        findings = [
            _make_finding("wheel", 0.90),
            _make_finding("tire", 0.85),
            _make_finding("brake", 0.80),
            _make_finding("engine", 0.75),
        ]
        result = select_top_causes(findings, max_causes=2)
        assert len(result) <= 2

    def test_best_per_source_group_selected(self) -> None:
        """Two findings for the same source → only the higher-confidence one.

        select_top_causes maps suspected_source → 'source' in its output.
        """
        findings = [
            _make_finding("wheel", 0.90),
            _make_finding("wheel", 0.60),
            _make_finding("tire", 0.80),
        ]
        result = select_top_causes(findings, max_causes=3)
        # Output uses 'source', not 'suspected_source'
        sources = [f.get("source") for f in result]
        # "wheel" should appear exactly once (best representative)
        assert sources.count("wheel") == 1

    def test_returns_list_of_dicts(self) -> None:
        """Return value must be a list of dicts."""
        findings = [_make_finding("wheel", 0.80)]
        result = select_top_causes(findings)
        assert isinstance(result, list)
        assert all(isinstance(f, dict) for f in result)
