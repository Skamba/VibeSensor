"""Domain coverage for hotspot confidence scoring and typed intensity summaries."""

from __future__ import annotations

import pytest

from vibesensor.domain.location_hotspot import (
    LocationHotspot,
    LocationHotspotRow,
    LocationIntensitySummary,
    StrengthBucketDistribution,
)
from vibesensor.summary.origin_fields import location_hotspot_from_payload


def _confidence(inputs: tuple[float, int, int]) -> float:
    dominance_ratio, location_count, total_samples = inputs
    return LocationHotspot.compute_confidence(
        dominance_ratio=dominance_ratio,
        location_count=location_count,
        total_samples=total_samples,
    )


class TestComputeConfidence:
    """LocationHotspot.compute_confidence staticmethod.

    confidence = dominance_component * location_component * (0.6 + 0.4 * sample_component),
    clamped to [0.05, 1.0]; dominance_component = (ratio - 1.0) / 0.5.
    """

    @pytest.mark.parametrize(
        ("dominance_ratio", "location_count", "total_samples", "expected"),
        [
            pytest.param(1.5, 1, 0, 0.6, id="zero-samples-keeps-sample-floor"),
            pytest.param(0.5, 1, 100, 0.05, id="minimum-floor"),
            pytest.param(1.0, 1, 50, 0.05, id="dominance-exactly-one"),
            pytest.param(10.0, 1, 1000, 1.0, id="maximum-cap"),
            pytest.param(1.25, 2, 10, 0.5 * (1.0 / 1.15), id="partial-dominance"),
        ],
    )
    def test_exact_values(
        self, dominance_ratio: float, location_count: int, total_samples: int, expected: float
    ) -> None:
        result = _confidence((dominance_ratio, location_count, total_samples))
        assert result == pytest.approx(expected, abs=0.001)

    def test_high_dominance_few_locations_is_confident(self) -> None:
        assert _confidence((1.6, 1, 20)) > 0.9
        assert _confidence((1.05, 6, 20)) < 0.2

    @pytest.mark.parametrize(
        ("stronger", "weaker"),
        [
            pytest.param((1.4, 1, 50), (1.4, 1, 3), id="fewer-samples-reduce-confidence"),
            pytest.param((1.4, 1, 20), (1.4, 5, 20), id="more-locations-reduce-confidence"),
        ],
    )
    def test_monotonic_in_samples_and_locations(
        self, stronger: tuple[float, int, int], weaker: tuple[float, int, int]
    ) -> None:
        assert _confidence(stronger) > _confidence(weaker)


class TestLocationHotspotValueObject:
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
            pytest.param(LocationHotspot(strongest_location=""), False, id="blank-location"),
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

    @pytest.mark.parametrize(
        ("hotspot", "expected"),
        [
            pytest.param(
                LocationHotspot(strongest_location="front_left", dominance_ratio=3.0),
                True,
                id="strong-separation",
            ),
            pytest.param(
                LocationHotspot(strongest_location="front_left", weak_spatial_separation=True),
                False,
                id="weak-spatial-separation",
            ),
            pytest.param(
                LocationHotspot(strongest_location="front_left", ambiguous=True),
                False,
                id="ambiguous-location",
            ),
        ],
    )
    def test_has_clear_separation_cases(self, hotspot: LocationHotspot, expected: bool) -> None:
        assert hotspot.has_clear_separation is expected

    @pytest.mark.parametrize(
        ("confidence", "expected"),
        [
            pytest.param(0.85, "high", id="high"),
            pytest.param(0.8, "high", id="high-threshold"),
            pytest.param(0.55, "medium", id="medium"),
            pytest.param(0.2, "low", id="low"),
            pytest.param(None, "low", id="missing-defaults-low"),
        ],
    )
    def test_confidence_band_uses_domain_thresholds(
        self,
        confidence: float | None,
        expected: str,
    ) -> None:
        assert LocationHotspot(localization_confidence=confidence).confidence_band == expected

    @pytest.mark.parametrize(
        ("alternatives", "expected"),
        [
            pytest.param(
                ("front_left", "front_right", "front_right", "rear_left"),
                ("front_right", "rear_left"),
                id="excludes-primary-and-dedupes",
            ),
            pytest.param((), (), id="no-alternatives"),
        ],
    )
    def test_supporting_locations_cases(
        self,
        alternatives: tuple[str, ...],
        expected: tuple[str, ...],
    ) -> None:
        hotspot = LocationHotspot(
            strongest_location="front_left",
            alternative_locations=alternatives,
        )
        assert hotspot.supporting_locations == expected

    @pytest.mark.parametrize(
        ("hotspot", "expected"),
        [
            pytest.param(
                LocationHotspot(strongest_location="front_left", dominance_ratio=3.0),
                "front_left",
                id="clear-location",
            ),
            pytest.param(
                LocationHotspot(
                    strongest_location="front_left",
                    ambiguous=True,
                    alternative_locations=("front_right",),
                ),
                "front_left / front_right",
                id="ambiguous-joins-supporting",
            ),
            pytest.param(
                LocationHotspot(
                    strongest_location="front_left",
                    weak_spatial_separation=True,
                    alternative_locations=("front_right",),
                ),
                "front_left / front_right",
                id="weak-separation-joins-supporting",
            ),
            pytest.param(LocationHotspot(strongest_location=""), "unknown", id="blank-location"),
        ],
    )
    def test_summary_location_cases(self, hotspot: LocationHotspot, expected: str) -> None:
        assert hotspot.summary_location == expected

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

    @pytest.mark.parametrize(
        ("alternative_location", "top_confidence", "alternative_confidence"),
        [
            pytest.param("rear_right", 0.9, 0.3, id="distant-second-finding"),
            pytest.param("front_left", 0.8, 0.75, id="same-location"),
            pytest.param("", 0.8, 0.75, id="blank-alternative"),
            pytest.param("rear_right", 0.0, 0.75, id="zero-top-confidence"),
        ],
    )
    def test_promote_near_tie_returns_same_hotspot_when_not_a_tie(
        self,
        alternative_location: str,
        top_confidence: float,
        alternative_confidence: float,
    ) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(strongest_location="front_left")
        promoted = hotspot.promote_near_tie(
            alternative_location=alternative_location,
            top_confidence=top_confidence,
            alternative_confidence=alternative_confidence,
        )
        assert promoted is hotspot

    @pytest.mark.parametrize(
        ("dominance_ratio", "weak", "location_count", "expected_weak"),
        [
            pytest.param(1.3, False, 3, True, id="below-three-location-threshold"),
            pytest.param(1.05, False, 2, True, id="below-baseline-threshold"),
            pytest.param(1.5, False, 3, False, id="above-three-location-threshold"),
            pytest.param(3.0, False, 2, False, id="strong-separation"),
            pytest.param(3.0, True, 2, True, id="already-weak-stays-weak"),
        ],
    )
    def test_with_adaptive_weak_spatial_cases(
        self,
        dominance_ratio: float,
        weak: bool,
        location_count: int,
        expected_weak: bool,
    ) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            dominance_ratio=dominance_ratio,
            weak_spatial_separation=weak,
        )
        result = hotspot.with_adaptive_weak_spatial(location_count)
        assert result.weak_spatial_separation is expected_weak
        if expected_weak == weak:
            assert result == hotspot

    def test_with_adaptive_weak_spatial_without_dominance_is_noop(self) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(strongest_location="front_left")
        assert hotspot.with_adaptive_weak_spatial(location_count=2) is hotspot


class TestLocationIntensitySummaryRows:
    def test_diagnostic_fields_prefer_usable_sample_metrics(self) -> None:
        summary = LocationIntensitySummary(
            location="front_left",
            sample_count=100,
            sample_coverage_ratio=0.9,
            sample_coverage_warning=False,
            usable_sample_count=80,
            usable_sample_coverage_ratio=0.75,
            usable_sample_coverage_warning=True,
        )
        assert summary.diagnostic_sample_count == 80
        assert summary.diagnostic_sample_coverage_ratio == 0.75
        assert summary.diagnostic_sample_coverage_warning is True

    def test_diagnostic_fields_fall_back_to_raw_sample_metrics(self) -> None:
        summary = LocationIntensitySummary(
            location="front_left",
            sample_count=100,
            sample_coverage_ratio=0.9,
            sample_coverage_warning=True,
        )
        assert summary.diagnostic_sample_count == 100
        assert summary.diagnostic_sample_coverage_ratio == 0.9
        assert summary.diagnostic_sample_coverage_warning is True

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            pytest.param({"sample_count": -1}, "sample_count", id="negative-samples"),
            pytest.param({"usable_sample_count": -1}, "usable_sample_count", id="negative-usable"),
            pytest.param(
                {"sample_coverage_ratio": 1.5}, "sample_coverage_ratio", id="sample-coverage-high"
            ),
            pytest.param(
                {"usable_sample_coverage_ratio": -0.1},
                "usable_sample_coverage_ratio",
                id="usable-coverage-low",
            ),
        ],
    )
    def test_invalid_sample_contract_rejected(
        self, overrides: dict[str, int | float], message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            LocationIntensitySummary(location="front_left", **overrides)

    def test_defaults_to_empty_typed_distribution(self) -> None:
        summary = LocationIntensitySummary(location="front-left")

        assert summary.strength_bucket_distribution == StrengthBucketDistribution()
        assert summary.strength_bucket_distribution.total == 0
        assert summary.phase_intensity is None

    def test_location_hotspot_row_defaults_to_db_unit(self) -> None:
        row = LocationHotspotRow(location="front-left", count=2, peak_value=18.0, mean_value=12.0)

        assert row.unit == "db"
