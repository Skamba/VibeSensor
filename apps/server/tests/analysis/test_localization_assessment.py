"""Tests for LocalizationAssessment – rich object for localization reasoning."""

from __future__ import annotations

from vibesensor.analysis._types import Finding
from vibesensor.analysis.summary_builder import LocalizationAssessment

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(**overrides: object) -> Finding:
    """Build a minimal Finding dict with location-relevant overrides."""
    base: Finding = {
        "finding_id": "F001",
        "suspected_source": "wheel/tire",
        "evidence_summary": "test",
        "frequency_hz_or_order": "1x wheel",
        "amplitude_metric": {"name": "rms", "value": 0.5, "units": "g", "definition": "rms"},
        "confidence": 0.75,
        "quick_checks": [],
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestClassification:
    def test_localized_with_known_location(self) -> None:
        finding = _make_finding(strongest_location="front_left")
        loc = LocalizationAssessment.from_finding(finding)
        assert loc.is_localized is True

    def test_not_localized_when_unknown(self) -> None:
        finding = _make_finding(strongest_location="unknown")
        loc = LocalizationAssessment.from_finding(finding)
        assert loc.is_localized is False

    def test_not_localized_when_empty(self) -> None:
        finding = _make_finding(strongest_location="")
        loc = LocalizationAssessment.from_finding(finding)
        assert loc.is_localized is False

    def test_diffuse_excitation(self) -> None:
        finding = _make_finding(diffuse_excitation=True)
        loc = LocalizationAssessment.from_finding(finding)
        assert loc.is_diffuse is True

    def test_not_diffuse_by_default(self) -> None:
        finding = _make_finding()
        loc = LocalizationAssessment.from_finding(finding)
        assert loc.is_diffuse is False

    def test_clear_separation_when_not_weak(self) -> None:
        finding = _make_finding(
            weak_spatial_separation=False,
            dominance_ratio=3.0,
        )
        loc = LocalizationAssessment.from_finding(finding)
        assert loc.has_clear_separation is True

    def test_no_clear_separation_when_weak(self) -> None:
        finding = _make_finding(weak_spatial_separation=True)
        loc = LocalizationAssessment.from_finding(finding)
        assert loc.has_clear_separation is False


# ---------------------------------------------------------------------------
# Location access
# ---------------------------------------------------------------------------


class TestLocationAccess:
    def test_primary_location(self) -> None:
        finding = _make_finding(strongest_location="rear_right")
        loc = LocalizationAssessment.from_finding(finding)
        assert loc.primary_location == "rear_right"

    def test_primary_defaults_to_unknown(self) -> None:
        finding = _make_finding()
        loc = LocalizationAssessment.from_finding(finding)
        assert loc.primary_location == "unknown"

    def test_supporting_locations_from_hotspot(self) -> None:
        finding = _make_finding(
            strongest_location="front_left",
            location_hotspot={
                "ambiguous_locations": ["front_left", "front_right"],
                "second_location": "rear_left",
            },
        )
        loc = LocalizationAssessment.from_finding(finding)
        supporting = loc.supporting_locations()
        assert "front_right" in supporting
        assert "rear_left" in supporting
        # primary should not be in supporting
        assert "front_left" not in supporting

    def test_supporting_locations_empty_when_no_hotspot(self) -> None:
        finding = _make_finding(strongest_location="front_left")
        loc = LocalizationAssessment.from_finding(finding)
        assert loc.supporting_locations() == []


# ---------------------------------------------------------------------------
# Confidence interpretation
# ---------------------------------------------------------------------------


class TestConfidenceBand:
    def test_high_confidence(self) -> None:
        finding = _make_finding(
            location_hotspot={"localization_confidence": 0.85},
        )
        loc = LocalizationAssessment.from_finding(finding)
        assert loc.confidence_band() == "high"

    def test_medium_confidence(self) -> None:
        finding = _make_finding(
            location_hotspot={"localization_confidence": 0.55},
        )
        loc = LocalizationAssessment.from_finding(finding)
        assert loc.confidence_band() == "medium"

    def test_low_confidence(self) -> None:
        finding = _make_finding(
            location_hotspot={"localization_confidence": 0.2},
        )
        loc = LocalizationAssessment.from_finding(finding)
        assert loc.confidence_band() == "low"

    def test_no_hotspot_defaults_to_low(self) -> None:
        finding = _make_finding()
        loc = LocalizationAssessment.from_finding(finding)
        assert loc.confidence_band() == "low"


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


class TestDisplayLocation:
    def test_simple_location(self) -> None:
        finding = _make_finding(
            strongest_location="front_left",
            dominance_ratio=3.0,
        )
        loc = LocalizationAssessment.from_finding(finding)
        assert loc.display_location() == "front_left"

    def test_ambiguous_location_shows_alternatives(self) -> None:
        finding = _make_finding(
            strongest_location="front_left",
            dominance_ratio=1.05,
            weak_spatial_separation=True,
            location_hotspot={
                "ambiguous_locations": ["front_left", "front_right"],
                "second_location": "",
                "location_count": 2,
            },
        )
        loc = LocalizationAssessment.from_finding(finding)
        display = loc.display_location()
        assert "front_left" in display
        assert "front_right" in display
        assert " / " in display


# ---------------------------------------------------------------------------
# Multi-finding enrichment
# ---------------------------------------------------------------------------


class TestEnrichFromSecondFinding:
    def test_close_confidence_promotes_ambiguity(self) -> None:
        top_finding = _make_finding(
            strongest_location="front_left",
            confidence=0.80,
        )
        second_finding = _make_finding(
            strongest_location="rear_right",
            confidence=0.60,
        )
        loc = LocalizationAssessment.from_finding(top_finding)
        loc.enrich_from_second_finding(second_finding, top_confidence=0.80)
        # 0.60 / 0.80 = 0.75 >= 0.7 → promotes ambiguity
        assert loc.has_clear_separation is False
        assert "rear_right" in loc.supporting_locations()

    def test_distant_confidence_preserves_state(self) -> None:
        top_finding = _make_finding(
            strongest_location="front_left",
            confidence=0.90,
            dominance_ratio=3.0,
        )
        second_finding = _make_finding(
            strongest_location="rear_right",
            confidence=0.30,
        )
        loc = LocalizationAssessment.from_finding(top_finding)
        loc.enrich_from_second_finding(second_finding, top_confidence=0.90)
        # 0.30 / 0.90 = 0.33 < 0.7 → no change
        assert "rear_right" not in loc.supporting_locations()

    def test_same_location_no_promotion(self) -> None:
        top_finding = _make_finding(
            strongest_location="front_left",
            confidence=0.80,
        )
        second_finding = _make_finding(
            strongest_location="front_left",
            confidence=0.75,
        )
        loc = LocalizationAssessment.from_finding(top_finding)
        loc.enrich_from_second_finding(second_finding, top_confidence=0.80)
        # Same location — no promotion
        assert loc.supporting_locations() == []
