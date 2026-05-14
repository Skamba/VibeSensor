"""Domain coverage for hotspot confidence scoring and typed intensity summaries."""

from __future__ import annotations

import pytest

from vibesensor.domain.location_hotspot import (
    LocationHotspot,
    LocationHotspotRow,
    LocationIntensitySummary,
    StrengthBucketDistribution,
)
from vibesensor.shared.boundaries.summary_fields.hotspot import (
    location_intensity_summary_from_mapping,
    phase_intensity_summary_from_mapping,
)
from vibesensor.shared.boundaries.summary_fields.origin import location_hotspot_from_payload


class TestComputeConfidence:
    """LocationHotspot.compute_confidence staticmethod."""

    def test_high_dominance_few_locations(self) -> None:
        result = LocationHotspot.compute_confidence(
            dominance_ratio=1.6,
            location_count=1,
            total_samples=20,
        )
        assert result > 0.9

    def test_low_dominance_many_locations(self) -> None:
        result = LocationHotspot.compute_confidence(
            dominance_ratio=1.05,
            location_count=6,
            total_samples=20,
        )
        assert result < 0.2

    def test_zero_samples_gives_minimum(self) -> None:
        result = LocationHotspot.compute_confidence(
            dominance_ratio=1.5,
            location_count=1,
            total_samples=0,
        )
        assert result == pytest.approx(0.6 * 1.0 * 1.0, abs=0.01)
        # dominance_component=1.0, location_component=1.0, sample_component=0.0
        # confidence = 1.0 * 1.0 * (0.6 + 0.4*0.0) = 0.6

    def test_minimum_floor(self) -> None:
        # dominance_ratio <= 1.0 → dominance_component = 0 → confidence → 0
        # but floor is 0.05
        result = LocationHotspot.compute_confidence(
            dominance_ratio=0.5,
            location_count=1,
            total_samples=100,
        )
        assert result == pytest.approx(0.05)

    def test_maximum_cap(self) -> None:
        result = LocationHotspot.compute_confidence(
            dominance_ratio=10.0,
            location_count=1,
            total_samples=1000,
        )
        assert result == pytest.approx(1.0)

    def test_dominance_exactly_one(self) -> None:
        # (1.0 - 1.0) / 0.5 = 0.0 → dominance_component = 0
        result = LocationHotspot.compute_confidence(
            dominance_ratio=1.0,
            location_count=1,
            total_samples=50,
        )
        assert result == pytest.approx(0.05)

    def test_partial_dominance(self) -> None:
        # dominance_ratio=1.25 → (0.25/0.5)=0.5
        # location_count=2 → 1/(1+0.15)=0.8696
        # total_samples=10 → sample_component=1.0
        # confidence = 0.5 * 0.8696 * 1.0 ≈ 0.4348
        result = LocationHotspot.compute_confidence(
            dominance_ratio=1.25,
            location_count=2,
            total_samples=10,
        )
        expected = 0.5 * (1.0 / 1.15) * (0.6 + 0.4 * 1.0)
        assert result == pytest.approx(expected, abs=0.001)

    def test_low_sample_count_reduces_confidence(self) -> None:
        high_samples = LocationHotspot.compute_confidence(
            dominance_ratio=1.4,
            location_count=1,
            total_samples=50,
        )
        low_samples = LocationHotspot.compute_confidence(
            dominance_ratio=1.4,
            location_count=1,
            total_samples=3,
        )
        assert high_samples > low_samples

    def test_more_locations_reduces_confidence(self) -> None:
        few = LocationHotspot.compute_confidence(
            dominance_ratio=1.4,
            location_count=1,
            total_samples=20,
        )
        many = LocationHotspot.compute_confidence(
            dominance_ratio=1.4,
            location_count=5,
            total_samples=20,
        )
        assert few > many


class TestLocationHotspotValueObject:
    def test_defaults(self) -> None:
        hotspot = LocationHotspot()
        assert hotspot.strongest_location == ""
        assert hotspot.dominance_ratio is None
        assert not hotspot.weak_spatial_separation
        assert not hotspot.ambiguous
        assert hotspot.alternative_locations == ()

    @pytest.mark.parametrize(
        ("hotspot", "expected"),
        [
            pytest.param(
                LocationHotspot(
                    strongest_location="front_left",
                    dominance_ratio=0.8,
                    weak_spatial_separation=False,
                    ambiguous=False,
                ),
                True,
                id="clear-location",
            ),
            pytest.param(
                LocationHotspot(strongest_location="unknown"),
                False,
                id="unknown-location",
            ),
            pytest.param(
                LocationHotspot(
                    strongest_location="front_left",
                    weak_spatial_separation=True,
                ),
                False,
                id="weak-spatial-separation",
            ),
        ],
    )
    def test_is_well_localized_cases(self, hotspot: LocationHotspot, expected: bool) -> None:
        assert hotspot.is_well_localized is expected

    @pytest.mark.parametrize(
        ("hotspot", "expected"),
        [
            pytest.param(LocationHotspot(strongest_location="FL wheel"), True, id="known-location"),
            pytest.param(LocationHotspot(strongest_location=""), False, id="blank-location"),
            pytest.param(
                LocationHotspot(strongest_location="unknown"),
                False,
                id="unknown-location",
            ),
            pytest.param(
                LocationHotspot(strongest_location="FL wheel", ambiguous=True),
                False,
                id="ambiguous-location",
            ),
        ],
    )
    def test_is_actionable_cases(self, hotspot: LocationHotspot, expected: bool) -> None:
        assert hotspot.is_actionable is expected

    @pytest.mark.parametrize(
        ("hotspot", "expected"),
        [
            pytest.param(
                LocationHotspot(strongest_location="front_left"),
                "Front Left",
                id="known-location",
            ),
            pytest.param(LocationHotspot(strongest_location=""), "Unknown", id="blank-location"),
            pytest.param(
                LocationHotspot(strongest_location="unknown"),
                "Unknown",
                id="unknown-location",
            ),
        ],
    )
    def test_display_location_cases(self, hotspot: LocationHotspot, expected: str) -> None:
        assert hotspot.display_location == expected

    def test_has_clear_separation_false_for_ambiguous_hotspot(self) -> None:
        hotspot = LocationHotspot(strongest_location="front_left", ambiguous=True)
        assert hotspot.has_clear_separation is False

    def test_confidence_band_uses_domain_thresholds(self) -> None:
        assert LocationHotspot(localization_confidence=0.8).confidence_band == "high"
        assert LocationHotspot(localization_confidence=0.55).confidence_band == "medium"
        assert LocationHotspot(localization_confidence=0.2).confidence_band == "low"

    def test_supporting_locations_excludes_primary_and_dedupes(self) -> None:
        hotspot = LocationHotspot(
            strongest_location="front_left",
            alternative_locations=("front_left", "front_right", "front_right", "rear_left"),
        )
        assert hotspot.supporting_locations == ("front_right", "rear_left")

    def test_summary_location_joins_supporting_locations_when_ambiguous(self) -> None:
        hotspot = LocationHotspot(
            strongest_location="front_left",
            ambiguous=True,
            alternative_locations=("front_right",),
        )
        assert hotspot.summary_location == "front_left / front_right"

    def test_location_hotspot_from_payload_full(self) -> None:
        hotspot = location_hotspot_from_payload(
            {
                "top_location": "FL wheel",
                "dominance_ratio": 0.75,
                "localization_confidence": 0.9,
                "weak_spatial_separation": True,
                "ambiguous_location": False,
                "ambiguous_locations": ["FR wheel", "RL wheel"],
            }
        )

        assert hotspot.strongest_location == "FL wheel"
        assert hotspot.dominance_ratio == 0.75
        assert hotspot.localization_confidence == 0.9
        assert hotspot.weak_spatial_separation is True
        assert hotspot.ambiguous is False
        assert hotspot.alternative_locations == ("FR wheel", "RL wheel")

    def test_location_hotspot_from_payload_empty(self) -> None:
        hotspot = location_hotspot_from_payload({})
        assert hotspot.strongest_location == ""
        assert hotspot.dominance_ratio is None

    def test_location_hotspot_from_payload_top_location_fallback(self) -> None:
        hotspot = location_hotspot_from_payload({"top_location": "center"})
        assert hotspot.strongest_location == "center"

    def test_location_hotspot_from_payload_prefers_top_location_identity(self) -> None:
        hotspot = location_hotspot_from_payload(
            {
                "top_location": "Front Left",
                "ambiguous_location": True,
                "ambiguous_locations": ["Front Left", "Front Right"],
            }
        )
        assert hotspot.strongest_location == "Front Left"
        assert hotspot.ambiguous is True
        assert hotspot.alternative_locations == ("Front Left", "Front Right")
        assert not hotspot.is_actionable
        assert not hotspot.is_well_localized

    @pytest.mark.parametrize(
        ("location_count", "expected"),
        [
            pytest.param(None, LocationHotspot.WEAK_SPATIAL_BASELINE, id="none-count"),
            pytest.param(2, LocationHotspot.WEAK_SPATIAL_BASELINE, id="two-locations"),
            pytest.param(1, LocationHotspot.WEAK_SPATIAL_BASELINE, id="one-location-clamped"),
            pytest.param(0, LocationHotspot.WEAK_SPATIAL_BASELINE, id="zero-location-clamped"),
            pytest.param(
                3,
                LocationHotspot.WEAK_SPATIAL_BASELINE * 1.1,
                id="three-locations-scaled",
            ),
            pytest.param(
                4,
                LocationHotspot.WEAK_SPATIAL_BASELINE * 1.2,
                id="four-locations-scaled",
            ),
        ],
    )
    def test_weak_spatial_threshold_cases(
        self,
        location_count: int | None,
        expected: float,
    ) -> None:
        assert LocationHotspot.weak_spatial_threshold(location_count) == pytest.approx(
            expected,
            rel=1e-6,
        )

    def test_weak_spatial_threshold_monotonically_increasing(self) -> None:
        thresholds = [LocationHotspot.weak_spatial_threshold(n) for n in range(2, 8)]
        for low, high in zip(thresholds, thresholds[1:], strict=False):
            assert high > low

    def test_from_analysis_inputs_full(self) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            dominance_ratio=2.5,
            localization_confidence=0.8,
            weak_spatial_separation=False,
            ambiguous=False,
            alternative_locations=["front_right"],
        )
        assert hotspot.strongest_location == "front_left"
        assert hotspot.dominance_ratio == pytest.approx(2.5)
        assert hotspot.localization_confidence == pytest.approx(0.8)
        assert hotspot.alternative_locations == ("front_right",)

    def test_from_analysis_inputs_defaults(self) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(strongest_location="rear_left")
        assert hotspot.strongest_location == "rear_left"
        assert hotspot.dominance_ratio is None
        assert hotspot.localization_confidence is None
        assert hotspot.alternative_locations == ()

    def test_from_analysis_inputs_filters_empty_alternatives(self) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(
            strongest_location="rear_right",
            alternative_locations=["rear_left", "", "front_left"],
        )
        assert hotspot.alternative_locations == ("rear_left", "front_left")

    def test_from_analysis_inputs_matches_direct_construction(self) -> None:
        direct = LocationHotspot(
            strongest_location="rear_right",
            dominance_ratio=1.8,
            localization_confidence=0.6,
            weak_spatial_separation=False,
            ambiguous=False,
            alternative_locations=("rear_left",),
        )
        via_factory = LocationHotspot.from_analysis_inputs(
            strongest_location="rear_right",
            dominance_ratio=1.8,
            localization_confidence=0.6,
            weak_spatial_separation=False,
            ambiguous=False,
            alternative_locations=["rear_left"],
        )
        assert via_factory == direct

    def test_from_analysis_inputs_near_tie_is_domain_owned(self) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            dominance_ratio=1.05,
            localization_confidence=0.35,
            weak_spatial_separation=True,
            ambiguous=True,
            alternative_locations=["front_right"],
        )
        assert hotspot.strongest_location == "front_left"
        assert hotspot.ambiguous is True
        assert hotspot.alternative_locations == ("front_right",)
        assert not hotspot.is_actionable
        assert not hotspot.is_well_localized

    def test_from_analysis_inputs_actionable_when_clear_and_known(self) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(
            strongest_location="rear_left",
            dominance_ratio=2.0,
            localization_confidence=0.9,
            weak_spatial_separation=False,
            ambiguous=False,
        )
        assert hotspot.is_actionable
        assert hotspot.is_well_localized

    def test_promote_near_tie_marks_hotspot_ambiguous(self) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(strongest_location="front_left")
        promoted = hotspot.promote_near_tie(
            alternative_location="rear_right",
            top_confidence=0.8,
            alternative_confidence=0.6,
        )
        assert promoted.ambiguous is True
        assert promoted.weak_spatial_separation is True
        assert promoted.supporting_locations == ("rear_right",)

    def test_promote_near_tie_ignores_distant_second_finding(self) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(strongest_location="front_left")
        promoted = hotspot.promote_near_tie(
            alternative_location="rear_right",
            top_confidence=0.9,
            alternative_confidence=0.3,
        )
        assert promoted == hotspot

    def test_with_adaptive_weak_spatial_promotes_below_threshold(self) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            dominance_ratio=1.3,
        )
        promoted = hotspot.with_adaptive_weak_spatial(3)
        assert promoted.weak_spatial_separation is True

    def test_with_adaptive_weak_spatial_leaves_strong_separation_unchanged(self) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            dominance_ratio=1.5,
        )
        promoted = hotspot.with_adaptive_weak_spatial(3)
        assert promoted == hotspot


class TestLocationIntensitySummaryRows:
    def test_boundary_codec_parses_typed_nested_values(self) -> None:
        summary = location_intensity_summary_from_mapping(
            {
                "location": "rear-left",
                "sample_count": 8,
                "sample_coverage_ratio": 0.75,
                "p95_intensity_db": 18.0,
                "strength_bucket_distribution": {
                    "total": 8,
                    "counts": {"l0": 2, "l1": 6},
                    "percent_time_l0": 25.0,
                    "percent_time_l1": 75.0,
                },
                "phase_intensity": {
                    "cruise": {
                        "count": 3,
                        "mean_intensity_db": 12.0,
                        "max_intensity_db": 18.0,
                    },
                },
            },
        )

        assert summary.location == "rear-left"
        assert summary.strength_bucket_distribution.total == 8
        assert summary.strength_bucket_distribution.counts["l1"] == 6
        assert summary.diagnostic_sample_count == 8
        assert summary.phase_intensity is not None
        assert summary.phase_intensity["cruise"].max_intensity_db == 18.0

    def test_strength_bucket_distribution_defaults_to_typed_object(self) -> None:
        summary = LocationIntensitySummary(location="front-left")

        assert isinstance(summary.strength_bucket_distribution, StrengthBucketDistribution)
        assert summary.strength_bucket_distribution.total == 0

    def test_location_hotspot_row_defaults_to_db_unit(self) -> None:
        row = LocationHotspotRow(location="front-left", count=2, peak_value=18.0, mean_value=12.0)

        assert row.unit == "db"

    def test_phase_intensity_summary_boundary_codec(self) -> None:
        phase = phase_intensity_summary_from_mapping(
            {
                "count": 5,
                "mean_intensity_db": 10.0,
                "max_intensity_db": 16.0,
            },
        )

        assert phase.count == 5
        assert phase.mean_intensity_db == 10.0
