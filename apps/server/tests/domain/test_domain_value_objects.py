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

from vibesensor.domain import (
    ConfidenceAssessment,
    Finding,
    FindingEvidence,
    LocationHotspot,
    RunAnalysisResult,
    RunSuitability,
    SpeedProfile,
    SuitabilityCheck,
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
        assert not LocationHotspot(
            strongest_location="FL wheel", ambiguous=True
        ).is_actionable

    def test_display_location(self) -> None:
        assert LocationHotspot(strongest_location="front_left").display_location == "Front Left"
        assert LocationHotspot(strongest_location="").display_location == "Unknown"
        assert LocationHotspot(strongest_location="unknown").display_location == "Unknown"

    def test_from_hotspot_dict_full(self) -> None:
        d = {
            "location": "FL wheel",
            "dominance_ratio": 0.75,
            "localization_confidence": 0.9,
            "weak_spatial_separation": True,
            "ambiguous_location": False,
            "alternative_locations": ["FR wheel", "RL wheel"],
        }
        h = LocationHotspot.from_hotspot_dict(d)
        assert h.strongest_location == "FL wheel"
        assert h.dominance_ratio == 0.75
        assert h.localization_confidence == 0.9
        assert h.weak_spatial_separation is True
        assert h.ambiguous is False
        assert h.alternative_locations == ("FR wheel", "RL wheel")

    def test_from_hotspot_dict_empty(self) -> None:
        h = LocationHotspot.from_hotspot_dict({})
        assert h.strongest_location == ""
        assert h.dominance_ratio is None

    def test_from_hotspot_dict_top_location_fallback(self) -> None:
        h = LocationHotspot.from_hotspot_dict({"top_location": "center"})
        assert h.strongest_location == "center"


# ── ConfidenceAssessment ─────────────────────────────────────────────────────


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
        assert sp.cruise_fraction == 0.0

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

    def test_from_stats_full(self) -> None:
        speed_stats = {
            "min_kmh": 30.0,
            "max_kmh": 90.0,
            "mean_kmh": 60.0,
            "stddev_kmh": 15.0,
            "steady_speed": True,
            "sample_count": 500,
        }
        phase_summary = {"has_cruise": True, "cruise_pct": 65.0}
        sp = SpeedProfile.from_stats(speed_stats, phase_summary)
        assert sp.min_kmh == 30.0
        assert sp.max_kmh == 90.0
        assert sp.mean_kmh == 60.0
        assert sp.steady_speed is True
        assert sp.has_cruise is True
        assert sp.cruise_fraction == pytest.approx(0.65)
        assert sp.sample_count == 500

    def test_from_stats_empty(self) -> None:
        sp = SpeedProfile.from_stats({})
        assert sp.min_kmh == 0.0
        assert sp.max_kmh == 0.0
        assert not sp.steady_speed

    def test_from_stats_no_phase(self) -> None:
        sp = SpeedProfile.from_stats({"min_kmh": 10, "max_kmh": 50})
        assert sp.has_cruise is False
        assert sp.cruise_fraction == 0.0


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
                SuitabilityCheck(check_key="b", state="fail", explanation="Too few samples"),
            )
        )
        assert rs.overall == "fail"
        assert not rs.is_usable
        assert len(rs.failed_checks) == 1
        assert rs.failed_checks[0].explanation == "Too few samples"

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
        rs = RunSuitability(
            checks=(SuitabilityCheck(check_key="test", state="pass"),)
        )
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
