"""Tests for domain value objects: FindingEvidence, LocationHotspot,
ConfidenceAssessment, SpeedProfile, RunSuitability.

These tests verify:
- Frozen immutability
- Boundary adapter (from_*) factories
- Domain query properties
- Edge cases (missing/partial/empty data)
"""

from __future__ import annotations

import dataclasses

import pytest

from vibesensor.boundaries.location_hotspot import location_hotspot_from_payload
from vibesensor.boundaries.vibration_origin import (
    origin_payload_from_finding,
    vibration_origin_from_payload,
)
from vibesensor.domain import (
    ConfidenceAssessment,
    Finding,
    FindingEvidence,
    LocationHotspot,
    RunAnalysisResult,
    RunSuitability,
    SpeedProfile,
    SuitabilityCheck,
    VibrationOrigin,
)

# ── FindingEvidence ──────────────────────────────────────────────────────────


class TestFindingEvidence:
    def test_frozen(self) -> None:
        e = FindingEvidence()
        with pytest.raises(dataclasses.FrozenInstanceError):
            e.match_rate = 0.5  # type: ignore[misc]

    def test_defaults(self) -> None:
        e = FindingEvidence()
        assert e.match_rate == 0.0
        assert e.snr_db is None
        assert e.presence_ratio == 0.0
        assert e.phase_confidences == ()
        assert e.vibration_strength_db is None

    def test_is_strong_true(self) -> None:
        e = FindingEvidence(match_rate=0.8, snr_db=10.0)
        assert e.is_strong

    def test_is_strong_false_low_match(self) -> None:
        e = FindingEvidence(match_rate=0.5, snr_db=10.0)
        assert not e.is_strong

    def test_is_strong_false_no_snr(self) -> None:
        e = FindingEvidence(match_rate=0.8, snr_db=None)
        assert not e.is_strong

    def test_is_consistent_true(self) -> None:
        e = FindingEvidence(burstiness=0.1, presence_ratio=0.7)
        assert e.is_consistent

    def test_is_consistent_false(self) -> None:
        e = FindingEvidence(burstiness=0.5, presence_ratio=0.3)
        assert not e.is_consistent

    def test_is_well_localized(self) -> None:
        e = FindingEvidence(spatial_concentration=0.8)
        assert e.is_well_localized
        e2 = FindingEvidence(spatial_concentration=0.3)
        assert not e2.is_well_localized

    def test_from_metrics_dict_full(self) -> None:
        d = {
            "match_rate": 0.85,
            "snr_db": 12.5,
            "presence_ratio": 0.7,
            "burstiness": 0.1,
            "spatial_concentration": 0.9,
            "frequency_correlation": 0.95,
            "speed_uniformity": 0.8,
            "spatial_uniformity": 0.7,
            "per_phase_confidence": {"cruise": 0.9, "accel": 0.6},
            "vibration_strength_db": 25.3,
        }
        e = FindingEvidence.from_metrics_dict(d)
        assert e.match_rate == 0.85
        assert e.snr_db == 12.5
        assert e.presence_ratio == 0.7
        assert e.burstiness == 0.1
        assert e.spatial_concentration == 0.9
        assert e.vibration_strength_db == 25.3
        assert ("accel", 0.6) in e.phase_confidences
        assert ("cruise", 0.9) in e.phase_confidences

    def test_from_metrics_dict_empty(self) -> None:
        e = FindingEvidence.from_metrics_dict({})
        assert e.match_rate == 0.0
        assert e.snr_db is None
        assert e.phase_confidences == ()

    def test_from_metrics_dict_snr_ratio_fallback(self) -> None:
        e = FindingEvidence.from_metrics_dict({"snr_ratio": 8.0})
        assert e.snr_db == 8.0


# ── LocationHotspot ──────────────────────────────────────────────────────────


class TestLocationHotspot:
    def test_frozen(self) -> None:
        h = LocationHotspot()
        with pytest.raises(dataclasses.FrozenInstanceError):
            h.strongest_location = "foo"  # type: ignore[misc]

    def test_defaults(self) -> None:
        h = LocationHotspot()
        assert h.strongest_location == ""
        assert h.dominance_ratio is None
        assert not h.weak_spatial_separation
        assert not h.ambiguous
        assert h.alternative_locations == ()

    def test_is_well_localized_true(self) -> None:
        h = LocationHotspot(
            strongest_location="front_left",
            dominance_ratio=0.8,
            weak_spatial_separation=False,
            ambiguous=False,
        )
        assert h.is_well_localized

    def test_is_well_localized_false_unknown(self) -> None:
        h = LocationHotspot(strongest_location="unknown")
        assert not h.is_well_localized

    def test_is_well_localized_false_weak_spatial(self) -> None:
        h = LocationHotspot(
            strongest_location="front_left",
            weak_spatial_separation=True,
        )
        assert not h.is_well_localized

    def test_is_actionable(self) -> None:
        assert LocationHotspot(strongest_location="FL wheel").is_actionable
        assert not LocationHotspot(strongest_location="").is_actionable
        assert not LocationHotspot(strongest_location="unknown").is_actionable
        assert not LocationHotspot(strongest_location="FL wheel", ambiguous=True).is_actionable

    def test_display_location(self) -> None:
        assert LocationHotspot(strongest_location="front_left").display_location == "Front Left"
        assert LocationHotspot(strongest_location="").display_location == "Unknown"
        assert LocationHotspot(strongest_location="unknown").display_location == "Unknown"

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
        d = {
            "location": "FL wheel",
            "dominance_ratio": 0.75,
            "localization_confidence": 0.9,
            "weak_spatial_separation": True,
            "ambiguous_location": False,
            "alternative_locations": ["FR wheel", "RL wheel"],
        }
        h = location_hotspot_from_payload(d)
        assert h.strongest_location == "FL wheel"
        assert h.dominance_ratio == 0.75
        assert h.localization_confidence == 0.9
        assert h.weak_spatial_separation is True
        assert h.ambiguous is False
        assert h.alternative_locations == ("FR wheel", "RL wheel")

    def test_location_hotspot_from_payload_empty(self) -> None:
        h = location_hotspot_from_payload({})
        assert h.strongest_location == ""
        assert h.dominance_ratio is None

    def test_location_hotspot_from_payload_top_location_fallback(self) -> None:
        h = location_hotspot_from_payload({"top_location": "center"})
        assert h.strongest_location == "center"

    def test_location_hotspot_from_payload_prefers_top_location_identity(self) -> None:
        hotspot = location_hotspot_from_payload(
            {
                "location": "ambiguous location: Front Left / Front Right",
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

    def test_weak_spatial_threshold_baseline_for_none(self) -> None:
        assert LocationHotspot.weak_spatial_threshold(None) == LocationHotspot.WEAK_SPATIAL_BASELINE

    def test_weak_spatial_threshold_baseline_for_two_locations(self) -> None:
        assert LocationHotspot.weak_spatial_threshold(2) == pytest.approx(
            LocationHotspot.WEAK_SPATIAL_BASELINE
        )

    def test_weak_spatial_threshold_scales_up_per_additional_location(self) -> None:
        baseline = LocationHotspot.WEAK_SPATIAL_BASELINE
        assert LocationHotspot.weak_spatial_threshold(3) == pytest.approx(
            baseline * 1.1,
            rel=1e-6,
        )
        assert LocationHotspot.weak_spatial_threshold(4) == pytest.approx(
            baseline * 1.2,
            rel=1e-6,
        )

    def test_weak_spatial_threshold_clamps_below_two(self) -> None:
        baseline = LocationHotspot.WEAK_SPATIAL_BASELINE
        assert LocationHotspot.weak_spatial_threshold(1) == pytest.approx(baseline)
        assert LocationHotspot.weak_spatial_threshold(0) == pytest.approx(baseline)

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


# ── ConfidenceAssessment ─────────────────────────────────────────────────────


# ── VibrationOrigin ──────────────────────────────────────────────────────────


class TestVibrationOrigin:
    def test_from_analysis_inputs_preserves_typed_contract(self) -> None:
        hotspot = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            ambiguous=True,
            alternative_locations=["front_right"],
        )
        origin = VibrationOrigin.from_analysis_inputs(
            suspected_source=Finding(suspected_source="wheel/tire").suspected_source,
            hotspot=hotspot,
            dominance_ratio=1.05,
            speed_band="80-90 km/h",
            dominant_phase="acceleration",
            reason="ranked from wheel order evidence",
        )
        assert origin.is_ambiguous is True
        assert origin.summary_location == "front_left / front_right"
        assert origin.alternative_locations == ("front_right",)
        assert origin.weak_spatial_separation is True

    def test_vibration_origin_from_payload_uses_boundary_decode(self) -> None:
        origin = vibration_origin_from_payload(
            {
                "suspected_source": "wheel/tire",
                "strongest_speed_band": "80-90 km/h",
                "dominant_phase": "acceleration",
                "evidence_summary": "payload rationale",
                "dominance_ratio": 1.1,
                "location_hotspot": {
                    "top_location": "rear_left",
                    "ambiguous_location": True,
                    "ambiguous_locations": ["rear_left", "rear_right"],
                },
            }
        )
        assert origin.summary_location == "rear_left / rear_right"
        assert origin.alternative_locations == ("rear_right",)
        assert origin.speed_band == "80-90 km/h"
        assert origin.reason == "payload rationale"

    def test_origin_payload_from_finding_projects_canonical_boundary_shape(self) -> None:
        finding = Finding(
            finding_id="F001",
            suspected_source="wheel/tire",
            strongest_location="front_left",
            strongest_speed_band="80-90 km/h",
            dominance_ratio=1.05,
            weak_spatial_separation=True,
            location=LocationHotspot.from_analysis_inputs(
                strongest_location="front_left",
                ambiguous=True,
                alternative_locations=["front_right"],
                dominance_ratio=1.05,
            ),
            origin=VibrationOrigin.from_analysis_inputs(
                suspected_source=Finding(suspected_source="wheel/tire").suspected_source,
                hotspot=LocationHotspot.from_analysis_inputs(
                    strongest_location="front_left",
                    ambiguous=True,
                    alternative_locations=["front_right"],
                    dominance_ratio=1.05,
                ),
                dominance_ratio=1.05,
                speed_band="80-90 km/h",
                dominant_phase="acceleration",
                reason="domain rationale",
            ),
        )
        payload = origin_payload_from_finding(finding)
        assert payload["location"] == "Front Left / Front Right"
        assert payload["alternative_locations"] == ["front_right"]
        assert payload["suspected_source"] == "wheel/tire"
        assert payload["speed_band"] == "80-90 km/h"
        assert payload["dominant_phase"] == "acceleration"
        assert payload["explanation"] == (
            "domain rationale; speed band 80-90 km/h; dominant phase acceleration"
        )


class TestConfidenceAssessment:
    def test_frozen(self) -> None:
        ca = ConfidenceAssessment.assess(0.8)
        with pytest.raises(dataclasses.FrozenInstanceError):
            ca.raw_confidence = 0.5  # type: ignore[misc]

    def test_high_confidence(self) -> None:
        ca = ConfidenceAssessment.assess(0.85)
        assert ca.label_key == "CONFIDENCE_HIGH"
        assert ca.tone == "success"
        assert ca.tier == "C"
        assert ca.is_conclusive
        assert not ca.needs_more_data

    def test_medium_confidence(self) -> None:
        ca = ConfidenceAssessment.assess(0.55)
        assert ca.label_key == "CONFIDENCE_MEDIUM"
        assert ca.tone == "warn"
        assert ca.tier == "B"
        assert not ca.is_conclusive
        assert not ca.needs_more_data

    def test_low_confidence(self) -> None:
        ca = ConfidenceAssessment.assess(0.2)
        assert ca.label_key == "CONFIDENCE_LOW"
        assert ca.tone == "neutral"
        assert ca.tier == "A"
        assert not ca.is_conclusive
        assert ca.needs_more_data

    def test_negligible_strength_downgrade(self) -> None:
        ca = ConfidenceAssessment.assess(0.85, strength_band_key="negligible")
        assert ca.label_key == "CONFIDENCE_MEDIUM"
        assert ca.tone == "warn"
        assert ca.downgraded
        assert ca.tier == "B"

    def test_reference_gaps_affect_tier(self) -> None:
        ca = ConfidenceAssessment.assess(0.85, has_reference_gaps=True)
        assert ca.tier == "B"
        assert "Missing reference data" in ca.reason

    def test_reasons_combined(self) -> None:
        ca = ConfidenceAssessment.assess(
            0.85,
            steady_speed=False,
            has_reference_gaps=True,
            weak_spatial=True,
            sensor_count=1,
        )
        assert "Speed was not steady" in ca.reason
        assert "Missing reference data" in ca.reason
        assert "Vibration spread" in ca.reason
        assert "Single sensor" in ca.reason

    def test_no_reasons_when_all_good(self) -> None:
        ca = ConfidenceAssessment.assess(0.85, sensor_count=4)
        assert ca.reason == ""


# ── SpeedProfile ─────────────────────────────────────────────────────────────


class TestSpeedProfile:
    def test_frozen(self) -> None:
        sp = SpeedProfile()
        with pytest.raises(dataclasses.FrozenInstanceError):
            sp.min_kmh = 10.0  # type: ignore[misc]

    def test_defaults(self) -> None:
        sp = SpeedProfile()
        assert sp.min_kmh == 0.0
        assert sp.max_kmh == 0.0
        assert not sp.steady_speed
        assert not sp.has_cruise
        assert not sp.has_acceleration
        assert sp.cruise_fraction == 0.0
        assert sp.idle_fraction == 0.0
        assert sp.speed_unknown_fraction == 0.0

    def test_speed_range_kmh(self) -> None:
        sp = SpeedProfile(min_kmh=40.0, max_kmh=80.0)
        assert sp.speed_range_kmh == 40.0

    def test_is_adequate_for_diagnosis(self) -> None:
        assert SpeedProfile(sample_count=100, max_kmh=60.0).is_adequate_for_diagnosis
        assert not SpeedProfile(sample_count=5, max_kmh=60.0).is_adequate_for_diagnosis
        assert not SpeedProfile(sample_count=100, max_kmh=3.0).is_adequate_for_diagnosis

    def test_has_steady_cruise(self) -> None:
        assert SpeedProfile(has_cruise=True, cruise_fraction=0.5).has_steady_cruise
        assert not SpeedProfile(has_cruise=True, cruise_fraction=0.1).has_steady_cruise
        assert not SpeedProfile(has_cruise=False, cruise_fraction=0.5).has_steady_cruise

    def test_known_speed_fraction(self) -> None:
        assert SpeedProfile(speed_unknown_fraction=0.25).known_speed_fraction == pytest.approx(0.75)

    def test_driving_fraction(self) -> None:
        assert SpeedProfile(idle_fraction=0.2).driving_fraction == pytest.approx(0.8)

    def test_has_speed_variation_uses_acceleration_or_nonsteady_range(self) -> None:
        assert SpeedProfile(has_acceleration=True, steady_speed=True).has_speed_variation
        assert SpeedProfile(min_kmh=40.0, max_kmh=80.0, steady_speed=False).has_speed_variation
        assert not SpeedProfile(min_kmh=40.0, max_kmh=80.0, steady_speed=True).has_speed_variation

    def test_supports_variable_speed_diagnosis_requires_adequate_data(self) -> None:
        assert SpeedProfile(
            sample_count=100,
            max_kmh=80.0,
            has_acceleration=True,
        ).supports_variable_speed_diagnosis
        assert not SpeedProfile(
            sample_count=5,
            max_kmh=80.0,
            has_acceleration=True,
        ).supports_variable_speed_diagnosis

    def test_supports_steady_state_diagnosis_uses_cruise_or_steady_motion(self) -> None:
        assert SpeedProfile(
            sample_count=100,
            max_kmh=80.0,
            has_cruise=True,
            cruise_fraction=0.4,
        ).supports_steady_state_diagnosis
        assert SpeedProfile(
            sample_count=100,
            max_kmh=80.0,
            steady_speed=True,
            idle_fraction=0.1,
        ).supports_steady_state_diagnosis
        assert not SpeedProfile(
            sample_count=5,
            max_kmh=80.0,
            steady_speed=True,
            idle_fraction=0.1,
        ).supports_steady_state_diagnosis

    def test_from_stats_full(self) -> None:
        speed_stats = {
            "min_kmh": 30.0,
            "max_kmh": 90.0,
            "mean_kmh": 60.0,
            "stddev_kmh": 15.0,
            "steady_speed": True,
            "sample_count": 500,
        }
        phase_summary = {
            "has_cruise": True,
            "has_acceleration": True,
            "cruise_pct": 65.0,
            "idle_pct": 10.0,
            "speed_unknown_pct": 5.0,
        }
        sp = SpeedProfile.from_stats(speed_stats, phase_summary)
        assert sp.min_kmh == 30.0
        assert sp.max_kmh == 90.0
        assert sp.mean_kmh == 60.0
        assert sp.steady_speed is True
        assert sp.has_cruise is True
        assert sp.has_acceleration is True
        assert sp.cruise_fraction == pytest.approx(0.65)
        assert sp.idle_fraction == pytest.approx(0.10)
        assert sp.speed_unknown_fraction == pytest.approx(0.05)
        assert sp.known_speed_fraction == pytest.approx(0.95)
        assert sp.driving_fraction == pytest.approx(0.90)
        assert sp.supports_variable_speed_diagnosis
        assert sp.supports_steady_state_diagnosis
        assert sp.sample_count == 500

    def test_from_stats_empty(self) -> None:
        sp = SpeedProfile.from_stats({})
        assert sp.min_kmh == 0.0
        assert sp.max_kmh == 0.0
        assert not sp.steady_speed
        assert not sp.has_acceleration
        assert sp.known_speed_fraction == 1.0
        assert sp.driving_fraction == 1.0

    def test_from_stats_no_phase(self) -> None:
        sp = SpeedProfile.from_stats({"min_kmh": 10, "max_kmh": 50})
        assert sp.has_cruise is False
        assert sp.cruise_fraction == 0.0

    def test_from_stats_reads_phase_fallbacks_from_nested_phase_maps(self) -> None:
        sp = SpeedProfile.from_stats(
            {
                "min_kmh": 20,
                "max_kmh": 60,
                "sample_count": 50,
            },
            {
                "phase_counts": {"acceleration": 5, "cruise": 20},
                "phase_pcts": {"cruise": 40.0, "idle": 15.0, "speed_unknown": 20.0},
            },
        )
        assert sp.has_cruise is True
        assert sp.has_acceleration is True
        assert sp.cruise_fraction == pytest.approx(0.40)
        assert sp.idle_fraction == pytest.approx(0.15)
        assert sp.speed_unknown_fraction == pytest.approx(0.20)


# ── RunSuitability ───────────────────────────────────────────────────────────


class TestSuitabilityCheck:
    def test_frozen(self) -> None:
        c = SuitabilityCheck(check_key="test", state="pass")
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.state = "fail"  # type: ignore[misc]

    def test_properties(self) -> None:
        assert SuitabilityCheck(check_key="a", state="pass").passed
        assert not SuitabilityCheck(check_key="a", state="pass").failed
        assert SuitabilityCheck(check_key="a", state="fail").failed
        assert SuitabilityCheck(check_key="a", state="warn").is_warning


class TestRunSuitability:
    def test_frozen(self) -> None:
        rs = RunSuitability()
        with pytest.raises(dataclasses.FrozenInstanceError):
            rs.checks = ()  # type: ignore[misc]

    def test_overall_pass(self) -> None:
        rs = RunSuitability(
            checks=(
                SuitabilityCheck(check_key="a", state="pass"),
                SuitabilityCheck(check_key="b", state="pass"),
            )
        )
        assert rs.overall == "pass"
        assert rs.is_usable
        assert not rs.has_warnings

    def test_overall_caution(self) -> None:
        rs = RunSuitability(
            checks=(
                SuitabilityCheck(check_key="a", state="pass"),
                SuitabilityCheck(check_key="b", state="warn"),
            )
        )
        assert rs.overall == "caution"
        assert rs.is_usable
        assert rs.has_warnings

    def test_overall_fail(self) -> None:
        rs = RunSuitability(
            checks=(
                SuitabilityCheck(check_key="a", state="pass"),
                SuitabilityCheck(check_key="b", state="fail"),
            )
        )
        assert rs.overall == "fail"
        assert not rs.is_usable
        assert len(rs.failed_checks) == 1
        assert rs.failed_checks[0].check_key == "b"

    def test_empty_checks(self) -> None:
        rs = RunSuitability()
        assert rs.overall == "pass"
        assert rs.is_usable

    def test_from_checks(self) -> None:
        checks = [
            {"check_key": "speed_variation", "state": "pass", "explanation": "OK"},
            {"check_key": "sample_count", "state": "warn", "explanation": "Marginal"},
            {"check_key": "noise_floor", "state": "fail", "explanation": "Too noisy"},
        ]
        rs = RunSuitability.from_checks(checks)
        assert len(rs.checks) == 3
        assert rs.overall == "fail"
        assert rs.checks[0].check_key == "speed_variation"
        assert rs.checks[1].state == "warn"
        assert rs.checks[2].failed

    def test_evaluate_owns_thresholds_and_semantic_details(self) -> None:
        rs = RunSuitability.evaluate(
            steady_speed=True,
            speed_sufficient=True,
            sensor_count=2,
            reference_complete=False,
            sat_count=3,
            total_dropped=5,
            total_overflow=1,
        )
        states = {check.check_key: check.state for check in rs.checks}
        assert states == {
            "SUITABILITY_CHECK_SPEED_VARIATION": "warn",
            "SUITABILITY_CHECK_SENSOR_COVERAGE": "warn",
            "SUITABILITY_CHECK_REFERENCE_COMPLETENESS": "warn",
            "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS": "warn",
            "SUITABILITY_CHECK_FRAME_INTEGRITY": "warn",
        }
        details = {check.check_key: check.details_dict for check in rs.checks}
        assert details["SUITABILITY_CHECK_SATURATION_AND_OUTLIERS"] == {"sat_count": 3}
        assert details["SUITABILITY_CHECK_FRAME_INTEGRITY"] == {
            "total_dropped": 5,
            "total_overflow": 1,
        }

    def test_from_checks_empty(self) -> None:
        rs = RunSuitability.from_checks([])
        assert rs.overall == "pass"

    def test_from_checks_legacy_key(self) -> None:
        rs = RunSuitability.from_checks([{"check": "old_key", "state": "pass"}])
        assert rs.checks[0].check_key == "old_key"


# ── Integration: Finding with evidence/location ─────────────────────────────


class TestFindingWithValueObjects:
    def test_finding_with_evidence(self) -> None:
        e = FindingEvidence(match_rate=0.9, snr_db=15.0)
        f = Finding(
            finding_id="F001",
            suspected_source="wheel/tire",
            confidence=0.85,
            evidence=e,
        )
        assert f.evidence is not None
        assert f.evidence.is_strong
        assert f.evidence.match_rate == 0.9

    def test_finding_with_location(self) -> None:
        loc = LocationHotspot(
            strongest_location="FL wheel",
            dominance_ratio=0.8,
        )
        f = Finding(
            finding_id="F001",
            suspected_source="wheel/tire",
            confidence=0.85,
            location=loc,
        )
        assert f.location is not None
        assert f.location.is_well_localized
        assert f.location.display_location == "Fl Wheel"

    def test_finding_with_confidence_assessment(self) -> None:
        ca = ConfidenceAssessment.assess(0.85)
        f = Finding(
            finding_id="F001",
            suspected_source="wheel/tire",
            confidence=0.85,
            confidence_assessment=ca,
        )
        assert f.confidence_assessment is not None
        assert f.confidence_assessment.tier == "C"
        assert f.confidence_assessment.is_conclusive

    def test_finding_from_payload_extracts_evidence(self) -> None:
        payload = {
            "finding_id": "F001",
            "suspected_source": "wheel/tire",
            "confidence": 0.85,
            "evidence_metrics": {
                "match_rate": 0.9,
                "snr_db": 15.0,
                "presence_ratio": 0.7,
                "vibration_strength_db": 25.3,
            },
        }
        f = Finding.from_payload(payload)
        assert f.evidence is not None
        assert f.evidence.match_rate == 0.9
        assert f.evidence.snr_db == 15.0
        assert f.evidence.vibration_strength_db == 25.3

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
        assert f.vibration_strength_db == 25.3  # still extracted directly too

    def test_finding_from_payload_extracts_location(self) -> None:
        payload = {
            "finding_id": "F001",
            "suspected_source": "wheel/tire",
            "confidence": 0.85,
            "location_hotspot": {
                "location": "FL wheel",
                "dominance_ratio": 0.75,
                "weak_spatial_separation": False,
            },
        }
        f = Finding.from_payload(payload)
        assert f.location is not None
        assert f.location.strongest_location == "FL wheel"
        assert f.location.dominance_ratio == 0.75

    def test_finding_from_payload_preserves_top_location_identity(self) -> None:
        payload = {
            "finding_id": "F001",
            "suspected_source": "wheel/tire",
            "confidence": 0.85,
            "location_hotspot": {
                "location": "ambiguous location: Front Left / Front Right",
                "top_location": "Front Left",
                "ambiguous_location": True,
                "ambiguous_locations": ["Front Left", "Front Right"],
                "weak_spatial_separation": True,
            },
        }
        finding = Finding.from_payload(payload)
        assert finding.location is not None
        assert finding.location.strongest_location == "Front Left"
        assert not finding.location.is_actionable

    def test_finding_from_payload_no_evidence(self) -> None:
        payload = {"finding_id": "REF_SPEED", "severity": "reference"}
        f = Finding.from_payload(payload)
        assert f.evidence is None
        assert f.location is None

    def test_finding_defaults_none(self) -> None:
        f = Finding(finding_id="F001")
        assert f.evidence is None
        assert f.location is None
        assert f.confidence_assessment is None


# ── Integration: RunAnalysisResult with SpeedProfile/Suitability ────────────


class TestRunAnalysisResultWithValueObjects:
    def test_result_with_speed_profile(self) -> None:
        sp = SpeedProfile(min_kmh=40, max_kmh=80, steady_speed=True)
        result = RunAnalysisResult(
            run_id="test",
            findings=(),
            top_causes=(),
            speed_profile=sp,
        )
        assert result.speed_profile is not None
        assert result.speed_profile.steady_speed

    def test_result_with_suitability(self) -> None:
        rs = RunSuitability(checks=(SuitabilityCheck(check_key="test", state="pass"),))
        result = RunAnalysisResult(
            run_id="test",
            findings=(),
            top_causes=(),
            suitability=rs,
        )
        assert result.suitability is not None
        assert result.suitability.is_usable

    def test_from_summary_extracts_speed_profile(self) -> None:
        summary = {
            "run_id": "test-123",
            "findings": [],
            "top_causes": [],
            "speed_stats": {
                "min_kmh": 30.0,
                "max_kmh": 90.0,
                "mean_kmh": 60.0,
                "steady_speed": True,
                "sample_count": 500,
            },
            "phase_summary": {"has_cruise": True, "cruise_pct": 65.0},
        }
        result = RunAnalysisResult.from_summary(summary)
        assert result.speed_profile is not None
        assert result.speed_profile.min_kmh == 30.0
        assert result.speed_profile.steady_speed
        assert result.speed_profile.has_cruise
        assert result.speed_profile.cruise_fraction == pytest.approx(0.65)

    def test_from_summary_extracts_suitability(self) -> None:
        summary = {
            "run_id": "test-123",
            "findings": [],
            "top_causes": [],
            "run_suitability": [
                {"check_key": "speed", "state": "pass", "explanation": "OK"},
                {"check_key": "noise", "state": "warn", "explanation": "Marginal"},
            ],
        }
        result = RunAnalysisResult.from_summary(summary)
        assert result.suitability is not None
        assert result.suitability.overall == "caution"
        assert len(result.suitability.checks) == 2

    def test_from_summary_no_speed_stats(self) -> None:
        summary = {"run_id": "test-123", "findings": [], "top_causes": []}
        result = RunAnalysisResult.from_summary(summary)
        assert result.speed_profile is None
        assert result.suitability is None

    def test_defaults_none(self) -> None:
        result = RunAnalysisResult(
            run_id="test",
            findings=(),
            top_causes=(),
        )
        assert result.speed_profile is None
        assert result.suitability is None
