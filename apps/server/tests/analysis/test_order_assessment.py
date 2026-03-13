"""Tests for OrderAssessment – rich object for order-candidate interpretation."""

from __future__ import annotations

import pytest

from tests.test_support.findings import make_finding_payload
from vibesensor.analysis.top_cause_selection import OrderAssessment

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestFromFinding:
    def test_extracts_basic_fields(self) -> None:
        finding = make_finding_payload(confidence=0.82, suspected_source="engine")
        assessment = OrderAssessment.from_finding(finding)
        assert assessment.domain_finding.finding_id == "F_ORDER"
        assert assessment.domain_finding.suspected_source == "engine"
        assert assessment.domain_finding.confidence == pytest.approx(0.82)

    def test_none_confidence_preserved(self) -> None:
        finding = make_finding_payload(confidence=None)
        assessment = OrderAssessment.from_finding(finding)
        assert assessment.domain_finding.confidence is None
        assert assessment.domain_finding.effective_confidence == 0.0

    def test_severity_defaults_to_diagnostic(self) -> None:
        finding = make_finding_payload()
        assessment = OrderAssessment.from_finding(finding)
        assert assessment.severity_band() == "diagnostic"

    def test_order_extracted(self) -> None:
        finding = make_finding_payload(frequency_hz_or_order="2x engine")
        assessment = OrderAssessment.from_finding(finding)
        assert assessment.domain_finding.order == "2x engine"


# ---------------------------------------------------------------------------
# Actionability / surfacing
# ---------------------------------------------------------------------------


class TestActionability:
    def test_reference_finding(self) -> None:
        assessment = OrderAssessment.from_finding(make_finding_payload(finding_id="REF_SPEED"))
        assert assessment.domain_finding.is_reference is True
        assert assessment.domain_finding.should_surface is False

    def test_info_severity_does_not_surface(self) -> None:
        assessment = OrderAssessment.from_finding(make_finding_payload(severity="info"))
        assert assessment.domain_finding.should_surface is False

    def test_low_confidence_does_not_surface(self) -> None:
        assessment = OrderAssessment.from_finding(make_finding_payload(confidence=0.10))
        assert assessment.domain_finding.should_surface is False

    def test_actionable_wheel_tire(self) -> None:
        assessment = OrderAssessment.from_finding(
            make_finding_payload(suspected_source="wheel/tire"),
        )
        assert assessment.domain_finding.is_actionable is True

    def test_placeholder_source_without_location_not_actionable(self) -> None:
        assessment = OrderAssessment.from_finding(
            make_finding_payload(suspected_source="unknown_resonance", strongest_location=""),
        )
        assert assessment.domain_finding.is_actionable is False

    def test_placeholder_source_with_location_is_actionable(self) -> None:
        assessment = OrderAssessment.from_finding(
            make_finding_payload(
                suspected_source="unknown_resonance",
                strongest_location="front_left",
            ),
        )
        assert assessment.domain_finding.is_actionable is True

    def test_normal_diagnostic_surfaces(self) -> None:
        assessment = OrderAssessment.from_finding(
            make_finding_payload(confidence=0.55, severity="diagnostic"),
        )
        assert assessment.domain_finding.should_surface is True


# ---------------------------------------------------------------------------
# Ranking / comparison
# ---------------------------------------------------------------------------


class TestRanking:
    def test_rank_key_quantised(self) -> None:
        a = OrderAssessment.from_finding(make_finding_payload(confidence=0.751))
        b = OrderAssessment.from_finding(make_finding_payload(confidence=0.749))
        assert a.domain_finding.rank_key >= b.domain_finding.rank_key

    def test_phase_adjusted_score_with_cruise(self) -> None:
        finding = make_finding_payload(
            confidence=0.80,
            phase_evidence={"cruise_fraction": 1.0},
        )
        assessment = OrderAssessment.from_finding(finding)
        assert assessment.domain_finding.phase_adjusted_score == pytest.approx(0.80)

    def test_phase_adjusted_score_without_cruise(self) -> None:
        finding = make_finding_payload(confidence=0.80, phase_evidence=None)
        assessment = OrderAssessment.from_finding(finding)
        assert assessment.domain_finding.phase_adjusted_score == pytest.approx(0.68)

    def test_is_stronger_than(self) -> None:
        strong = OrderAssessment.from_finding(
            make_finding_payload(confidence=0.90, phase_evidence={"cruise_fraction": 1.0}),
        )
        weak = OrderAssessment.from_finding(
            make_finding_payload(confidence=0.30, phase_evidence=None),
        )
        assert strong.domain_finding.is_stronger_than(weak.domain_finding)
        assert not weak.domain_finding.is_stronger_than(strong.domain_finding)


# ---------------------------------------------------------------------------
# Certainty banding
# ---------------------------------------------------------------------------


class TestCertaintyBand:
    def test_high_confidence(self) -> None:
        assessment = OrderAssessment.from_finding(make_finding_payload(confidence=0.80))
        label_key, tone, pct = assessment.certainty_band()
        assert label_key == "CONFIDENCE_HIGH"
        assert tone == "success"
        assert pct == "80%"

    def test_medium_confidence(self) -> None:
        assessment = OrderAssessment.from_finding(make_finding_payload(confidence=0.50))
        label_key, tone, _pct = assessment.certainty_band()
        assert label_key == "CONFIDENCE_MEDIUM"
        assert tone == "warn"

    def test_negligible_strength_caps_high(self) -> None:
        assessment = OrderAssessment.from_finding(make_finding_payload(confidence=0.80))
        label_key, tone, _pct = assessment.certainty_band(strength_band_key="negligible")
        assert label_key == "CONFIDENCE_MEDIUM"
        assert tone == "warn"


# ---------------------------------------------------------------------------
# TopCause serialisation
# ---------------------------------------------------------------------------


class TestToTopCause:
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
        assessment = OrderAssessment.from_finding(finding)
        top_cause = assessment.to_top_cause()
        assert top_cause["suspected_source"] == "engine"
        assert top_cause["confidence"] == pytest.approx(0.75)
        assert top_cause["strongest_location"] == "front_left"
        assert top_cause["dominance_ratio"] == pytest.approx(2.5)
        assert top_cause["confidence_label_key"] == "CONFIDENCE_HIGH"
        assert top_cause["confidence_tone"] == "success"

    def test_none_confidence_in_top_cause(self) -> None:
        finding = make_finding_payload(confidence=None)
        assessment = OrderAssessment.from_finding(finding)
        top_cause = assessment.to_top_cause()
        assert top_cause["confidence"] is None
