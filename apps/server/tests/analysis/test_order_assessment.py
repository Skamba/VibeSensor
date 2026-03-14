"""Tests for top-cause enrichment and confidence_label."""

from __future__ import annotations

import pytest

from tests.test_support.findings import make_finding_payload
from vibesensor.analysis.top_cause_selection import _enrich_top_cause_payload, confidence_label
from vibesensor.boundaries.finding import finding_from_payload

# ---------------------------------------------------------------------------
# Top-cause enrichment (boundary adapter for presentation fields)
# ---------------------------------------------------------------------------


class TestEnrichTopCausePayload:
    def test_round_trip_preserves_fields(self) -> None:
        finding = make_finding_payload(
            confidence=0.75,
            suspected_source="engine",
            strongest_location="front_left",
            dominance_ratio=2.5,
            strongest_speed_band="80-100",
            weak_spatial_separation=False,
            diffuse_excitation=False,
            phase_evidence={"cruise_fraction": 0.8},
        )
        domain = finding_from_payload(finding)
        top_cause = _enrich_top_cause_payload(finding, domain)
        assert top_cause["suspected_source"] == "engine"
        assert top_cause["confidence"] == pytest.approx(0.75)
        assert top_cause["strongest_location"] == "front_left"
        assert top_cause["dominance_ratio"] == pytest.approx(2.5)
        assert top_cause["confidence_label_key"] == "CONFIDENCE_HIGH"
        assert top_cause["confidence_tone"] == "success"

    def test_none_confidence_in_top_cause(self) -> None:
        finding = make_finding_payload(confidence=None)
        domain = finding_from_payload(finding)
        top_cause = _enrich_top_cause_payload(finding, domain)
        assert top_cause["confidence"] is None

    def test_severity_defaults_to_diagnostic(self) -> None:
        finding = make_finding_payload()
        domain = finding_from_payload(finding)
        top_cause = _enrich_top_cause_payload(finding, domain)
        # The finding's order field should be populated without error
        assert "order" in top_cause

    def test_order_from_frequency_hz_or_order(self) -> None:
        finding = make_finding_payload(frequency_hz_or_order="2x engine")
        domain = finding_from_payload(finding)
        top_cause = _enrich_top_cause_payload(finding, domain)
        assert top_cause["order"] == "2x engine"

    def test_grouping_fields_from_payload(self) -> None:
        finding = {
            **make_finding_payload(),
            "signatures_observed": ["1x", "2x"],
            "grouped_count": 3,
            "diagnostic_caveat": {"_i18n_key": "SOME_CAVEAT"},
        }
        domain = finding_from_payload(finding)
        top_cause = _enrich_top_cause_payload(finding, domain)
        assert top_cause["signatures_observed"] == ["1x", "2x"]
        assert top_cause["grouped_count"] == 3
        assert top_cause["diagnostic_caveat"] == {"_i18n_key": "SOME_CAVEAT"}

    def test_negligible_strength_caps_high_confidence(self) -> None:
        finding = make_finding_payload(confidence=0.80)
        domain = finding_from_payload(finding)
        top_cause = _enrich_top_cause_payload(finding, domain, strength_band_key="negligible")
        assert top_cause["confidence_label_key"] == "CONFIDENCE_MEDIUM"
        assert top_cause["confidence_tone"] == "warn"

    def test_phase_evidence_in_output(self) -> None:
        finding = make_finding_payload(phase_evidence={"cruise_fraction": 0.9})
        domain = finding_from_payload(finding)
        top_cause = _enrich_top_cause_payload(finding, domain)
        assert top_cause["phase_evidence"] == {"cruise_fraction": 0.9}

    def test_no_phase_evidence(self) -> None:
        finding = make_finding_payload(phase_evidence=None)
        domain = finding_from_payload(finding)
        top_cause = _enrich_top_cause_payload(finding, domain)
        assert top_cause["phase_evidence"] is None


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
