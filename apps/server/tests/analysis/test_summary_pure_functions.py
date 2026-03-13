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

from tests.test_support.findings import make_finding_payload
from vibesensor.analysis.strength_labels import (
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
)
from vibesensor.domain import Finding
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


class TestSelectTopCauses:
    """Direct unit tests for select_top_causes grouping and drop-off."""

    def test_empty_findings_returns_empty(self) -> None:
        payloads, domain_findings = select_top_causes([])
        assert payloads == []
        assert domain_findings == ()

    def test_below_min_confidence_findings_excluded(self) -> None:
        """Findings below ORDER_MIN_CONFIDENCE (0.25) must be filtered."""
        findings = [make_finding_payload(suspected_source="wheel/tire", confidence=0.10)]
        payloads, domain_findings = select_top_causes(findings)
        assert payloads == []
        assert domain_findings == ()

    def test_info_severity_excluded(self) -> None:
        """Info-severity findings must not appear in top causes."""
        findings = [
            make_finding_payload(suspected_source="wheel/tire", confidence=0.90, severity="info"),
        ]
        payloads, _ = select_top_causes(findings)
        assert payloads == []

    def test_ref_finding_excluded(self) -> None:
        """Findings whose ID starts with REF_ must be excluded."""
        findings = [
            make_finding_payload(
                suspected_source="baseline",
                confidence=0.95,
                finding_id="REF_BASELINE",
            ),
        ]
        payloads, _ = select_top_causes(findings)
        assert payloads == []

    def test_respects_max_causes_limit(self) -> None:
        """At most max_causes findings are returned."""
        findings = [
            make_finding_payload(suspected_source="wheel/tire", confidence=0.90),
            make_finding_payload(suspected_source="driveline", confidence=0.85),
            make_finding_payload(suspected_source="engine", confidence=0.80),
            make_finding_payload(suspected_source="body resonance", confidence=0.75),
        ]
        payloads, domain_findings = select_top_causes(findings, max_causes=2)
        assert len(payloads) <= 2
        assert len(domain_findings) <= 2

    def test_best_per_source_group_selected(self) -> None:
        """Two findings for the same source → only the higher-confidence one."""
        findings = [
            make_finding_payload(suspected_source="wheel/tire", confidence=0.90),
            make_finding_payload(suspected_source="wheel/tire", confidence=0.60),
            make_finding_payload(suspected_source="engine", confidence=0.80),
        ]
        payloads, domain_findings = select_top_causes(findings, max_causes=3)
        sources = [f.get("suspected_source") for f in payloads]
        # "wheel/tire" should appear exactly once (best representative)
        assert sources.count("wheel/tire") == 1
        # Domain findings correspond 1:1
        assert len(domain_findings) == len(payloads)

    def test_returns_list_of_dicts(self) -> None:
        """Return value must be a list of dicts."""
        findings = [make_finding_payload(suspected_source="wheel/tire", confidence=0.80)]
        payloads, domain_findings = select_top_causes(findings)
        assert isinstance(payloads, list)
        assert all(isinstance(f, dict) for f in payloads)
        assert all(isinstance(d, Finding) for d in domain_findings)
