"""Tests for LocationHotspot – domain object for spatial vibration reasoning.

Covers: from_analysis_inputs construction, promote_near_tie enrichment,
with_adaptive_weak_spatial threshold logic, classification queries,
summary_location display, and edge cases.
"""

from __future__ import annotations

from vibesensor.domain.diagnostics.location_hotspot import LocationHotspot

# ---------------------------------------------------------------------------
# Construction via from_analysis_inputs
# ---------------------------------------------------------------------------


class TestFromAnalysisInputs:
    def test_basic_construction(self) -> None:
        h = LocationHotspot.from_analysis_inputs(strongest_location="front_left")
        assert h.strongest_location == "front_left"
        assert h.dominance_ratio is None
        assert h.weak_spatial_separation is False
        assert h.ambiguous is False
        assert h.alternative_locations == ()

    def test_with_alternatives(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            alternative_locations=["front_right", "rear_left"],
        )
        assert h.alternative_locations == ("front_right", "rear_left")

    def test_filters_empty_alternatives(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            alternative_locations=["front_right", "", "rear_left"],
        )
        assert h.alternative_locations == ("front_right", "rear_left")

    def test_all_fields(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            dominance_ratio=2.5,
            localization_confidence=0.85,
            weak_spatial_separation=True,
            ambiguous=True,
            alternative_locations=["rear_right"],
        )
        assert h.dominance_ratio == 2.5
        assert h.localization_confidence == 0.85
        assert h.weak_spatial_separation is True
        assert h.ambiguous is True


# ---------------------------------------------------------------------------
# Classification queries
# ---------------------------------------------------------------------------


class TestClassification:
    def test_well_localized_with_known_location(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            dominance_ratio=2.0,
        )
        assert h.is_well_localized is True

    def test_not_well_localized_when_unknown(self) -> None:
        h = LocationHotspot.from_analysis_inputs(strongest_location="unknown")
        assert h.is_well_localized is False

    def test_not_well_localized_when_empty(self) -> None:
        h = LocationHotspot.from_analysis_inputs(strongest_location="")
        assert h.is_well_localized is False

    def test_actionable_with_known_location(self) -> None:
        h = LocationHotspot.from_analysis_inputs(strongest_location="front_left")
        assert h.is_actionable is True

    def test_not_actionable_when_ambiguous(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            ambiguous=True,
        )
        assert h.is_actionable is False

    def test_clear_separation_when_not_weak(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            dominance_ratio=3.0,
            weak_spatial_separation=False,
        )
        assert h.has_clear_separation is True

    def test_no_clear_separation_when_weak(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            weak_spatial_separation=True,
        )
        assert h.has_clear_separation is False

    def test_no_clear_separation_when_ambiguous(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            ambiguous=True,
        )
        assert h.has_clear_separation is False


# ---------------------------------------------------------------------------
# Location access
# ---------------------------------------------------------------------------


class TestLocationAccess:
    def test_supporting_locations_excludes_primary(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            alternative_locations=["front_left", "front_right", "rear_left"],
        )
        supporting = h.supporting_locations
        assert "front_right" in supporting
        assert "rear_left" in supporting
        assert "front_left" not in supporting

    def test_supporting_locations_empty_when_no_alternatives(self) -> None:
        h = LocationHotspot.from_analysis_inputs(strongest_location="front_left")
        assert h.supporting_locations == ()


# ---------------------------------------------------------------------------
# Confidence interpretation
# ---------------------------------------------------------------------------


class TestConfidenceBand:
    def test_high_confidence(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            localization_confidence=0.85,
        )
        assert h.confidence_band == "high"

    def test_medium_confidence(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            localization_confidence=0.55,
        )
        assert h.confidence_band == "medium"

    def test_low_confidence(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            localization_confidence=0.2,
        )
        assert h.confidence_band == "low"

    def test_no_confidence_defaults_to_low(self) -> None:
        h = LocationHotspot.from_analysis_inputs(strongest_location="front_left")
        assert h.confidence_band == "low"


# ---------------------------------------------------------------------------
# summary_location display
# ---------------------------------------------------------------------------


class TestSummaryLocation:
    def test_simple_location_with_clear_separation(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            dominance_ratio=3.0,
        )
        assert h.summary_location == "front_left"

    def test_ambiguous_location_shows_alternatives(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            weak_spatial_separation=True,
            alternative_locations=["front_right"],
        )
        location = h.summary_location
        assert "front_left" in location
        assert "front_right" in location
        assert " / " in location

    def test_defaults_to_unknown_when_empty(self) -> None:
        h = LocationHotspot.from_analysis_inputs(strongest_location="")
        assert h.summary_location == "unknown"


# ---------------------------------------------------------------------------
# promote_near_tie
# ---------------------------------------------------------------------------


class TestPromoteNearTie:
    def test_close_confidence_promotes_ambiguity(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            dominance_ratio=2.0,
        )
        promoted = h.promote_near_tie(
            alternative_location="rear_right",
            top_confidence=0.80,
            alternative_confidence=0.60,  # 0.75 >= 0.7 threshold
        )
        assert promoted.weak_spatial_separation is True
        assert promoted.ambiguous is True
        assert "rear_right" in promoted.alternative_locations

    def test_distant_confidence_preserves_state(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            dominance_ratio=3.0,
        )
        result = h.promote_near_tie(
            alternative_location="rear_right",
            top_confidence=0.90,
            alternative_confidence=0.30,  # 0.33 < 0.7 threshold
        )
        assert result is h  # unchanged — returns same object

    def test_same_location_no_promotion(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
        )
        result = h.promote_near_tie(
            alternative_location="front_left",
            top_confidence=0.80,
            alternative_confidence=0.75,
        )
        assert result is h

    def test_empty_alternative_no_promotion(self) -> None:
        h = LocationHotspot.from_analysis_inputs(strongest_location="front_left")
        result = h.promote_near_tie(
            alternative_location="",
            top_confidence=0.80,
            alternative_confidence=0.75,
        )
        assert result is h

    def test_zero_top_confidence_no_promotion(self) -> None:
        h = LocationHotspot.from_analysis_inputs(strongest_location="front_left")
        result = h.promote_near_tie(
            alternative_location="rear_right",
            top_confidence=0.0,
            alternative_confidence=0.75,
        )
        assert result is h


# ---------------------------------------------------------------------------
# with_adaptive_weak_spatial
# ---------------------------------------------------------------------------


class TestAdaptiveWeakSpatial:
    def test_low_dominance_becomes_weak(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            dominance_ratio=1.05,
        )
        result = h.with_adaptive_weak_spatial(location_count=2)
        assert result.weak_spatial_separation is True

    def test_high_dominance_stays_strong(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            dominance_ratio=3.0,
        )
        result = h.with_adaptive_weak_spatial(location_count=2)
        assert result.weak_spatial_separation is False

    def test_none_dominance_unchanged(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
        )
        result = h.with_adaptive_weak_spatial(location_count=2)
        assert result is h

    def test_already_weak_stays_weak(self) -> None:
        h = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            dominance_ratio=3.0,
            weak_spatial_separation=True,
        )
        result = h.with_adaptive_weak_spatial(location_count=2)
        assert result.weak_spatial_separation is True

    def test_threshold_scales_with_location_count(self) -> None:
        baseline = LocationHotspot.weak_spatial_threshold(2)
        three = LocationHotspot.weak_spatial_threshold(3)
        five = LocationHotspot.weak_spatial_threshold(5)
        assert three > baseline
        assert five > three

    def test_none_location_count_uses_baseline(self) -> None:
        assert LocationHotspot.weak_spatial_threshold(None) == LocationHotspot.WEAK_SPATIAL_BASELINE
