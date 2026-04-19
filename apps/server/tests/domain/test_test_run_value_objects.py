"""Domain value-object tests for composed test-run state and segments."""

from __future__ import annotations

import dataclasses

import pytest

from vibesensor.domain import (
    ConfidenceAssessment,
    DrivingPhase,
    DrivingPhaseSegment,
    DrivingSegment,
    Finding,
    FindingEvidence,
    LocationHotspot,
    RunCapture,
    RunSetup,
    RunSuitability,
    Sensor,
    SpeedProfile,
    SuitabilityCheck,
    TestRun,
)
from vibesensor.shared.boundaries.analysis_payloads.reconstruction import (
    test_run_from_summary as reconstruct_test_run_from_summary,
)
from vibesensor.shared.boundaries.summary_fields.finding import (
    finding_from_payload,
)


def _make_test_run_finding(
    finding_id: str,
    *,
    suspected_source: str = "wheel/tire",
    confidence: float = 0.82,
    strongest_location: str | None = "front_left",
) -> Finding:
    return Finding(
        finding_id=finding_id,
        suspected_source=suspected_source,
        confidence=confidence,
        strongest_location=strongest_location,
    )


def _make_test_run(
    *,
    run_id: str = "run-1",
    findings: tuple[Finding, ...],
    top_causes: tuple[Finding, ...],
) -> TestRun:
    return TestRun(
        capture=RunCapture(run_id=run_id),
        findings=findings,
        top_causes=top_causes,
    )


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
        f = finding_from_payload(payload)
        assert f.evidence is not None
        assert f.evidence.match_rate == 0.9
        assert f.evidence.snr_db == 15.0
        assert f.evidence.vibration_strength_db == 25.3

        assert f.vibration_strength_db == 25.3  # still extracted directly too

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

    def test_finding_from_payload_extracts_location(self) -> None:
        payload = {
            "finding_id": "F001",
            "suspected_source": "wheel/tire",
            "confidence": 0.85,
            "location_hotspot": {
                "top_location": "FL wheel",
                "dominance_ratio": 0.75,
                "weak_spatial_separation": False,
            },
        }
        f = finding_from_payload(payload)
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
        finding = finding_from_payload(payload)
        assert finding.location is not None
        assert finding.location.strongest_location == "Front Left"
        assert not finding.location.is_actionable

    def test_finding_from_payload_no_evidence(self) -> None:
        payload = {"finding_id": "REF_SPEED", "severity": "reference"}
        f = finding_from_payload(payload)
        assert f.evidence is None
        assert f.location is None

    def test_finding_from_payload_populates_origin_and_signatures(self) -> None:
        payload = {
            "finding_id": "F001",
            "suspected_source": "wheel/tire",
            "confidence": 0.85,
            "strongest_speed_band": "80-90 km/h",
            "signatures_observed": ["1x wheel order", "2x wheel order"],
            "location_hotspot": {"top_location": "FL wheel", "dominance_ratio": 0.75},
        }
        finding = finding_from_payload(payload)
        assert finding.origin is not None
        assert len(finding.signatures) == 2
        assert finding.origin.display_location == "Fl Wheel"

    def test_finding_defaults_none(self) -> None:
        f = Finding(finding_id="F001")
        assert f.evidence is None
        assert f.location is None
        assert f.confidence_assessment is None


class TestTestRunTopCauseInvariant:
    def test_allows_exact_top_cause_subset(self) -> None:
        primary = _make_test_run_finding("F001")
        secondary = _make_test_run_finding("F002", suspected_source="engine")

        test_run = _make_test_run(
            findings=(primary, secondary),
            top_causes=(primary,),
        )

        assert test_run.top_causes == (primary,)

    def test_allows_derived_top_cause_with_same_identity(self) -> None:
        primary = _make_test_run_finding("F001")
        derived_top_cause = dataclasses.replace(
            primary,
            confidence_assessment=ConfidenceAssessment.assess(0.82),
        )

        test_run = _make_test_run(
            findings=(primary,),
            top_causes=(derived_top_cause,),
        )

        assert test_run.top_causes == (derived_top_cause,)

    def test_rejects_top_cause_without_matching_finding(self) -> None:
        finding = _make_test_run_finding("F001")
        unrelated = _make_test_run_finding("F999", suspected_source="engine")

        with pytest.raises(ValueError, match="subset or derivation of findings"):
            _make_test_run(findings=(finding,), top_causes=(unrelated,))

    def test_rejects_top_cause_when_findings_are_empty(self) -> None:
        top_cause = _make_test_run_finding("F001")

        with pytest.raises(ValueError, match="must be drawn from findings"):
            _make_test_run(findings=(), top_causes=(top_cause,))


class TestTestRunWithValueObjects:
    def test_result_with_speed_profile(self) -> None:
        sp = SpeedProfile(min_kmh=40, max_kmh=80, steady_speed=True)
        result = TestRun(
            capture=RunCapture(run_id="test"),
            findings=(),
            top_causes=(),
            speed_profile=sp,
        )
        assert result.speed_profile is not None
        assert result.speed_profile.steady_speed

    def test_result_with_suitability(self) -> None:
        rs = RunSuitability(checks=(SuitabilityCheck(check_key="test", state="pass"),))
        result = TestRun(
            capture=RunCapture(run_id="test"),
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
        result = reconstruct_test_run_from_summary(summary)
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
        result = reconstruct_test_run_from_summary(summary)
        assert result.suitability is not None
        assert result.suitability.overall == "caution"
        assert len(result.suitability.checks) == 2

    def test_from_summary_no_speed_stats(self) -> None:
        summary = {"run_id": "test-123", "findings": [], "top_causes": []}
        result = reconstruct_test_run_from_summary(summary)
        assert result.speed_profile is None
        assert result.suitability is None

    def test_defaults_none(self) -> None:
        result = TestRun(
            capture=RunCapture(run_id="test"),
            findings=(),
            top_causes=(),
        )
        assert result.speed_profile is None
        assert result.suitability is None


class TestTestRunSensors:
    @pytest.mark.parametrize(
        ("location_codes", "expected_count"),
        [
            pytest.param([], 0, id="default-empty"),
            pytest.param(["front_left_wheel", "rear_axle"], 2, id="two-sensors"),
            pytest.param(
                ["front_left_wheel", "rear_axle", "dashboard"],
                3,
                id="sensor-count-property",
            ),
        ],
    )
    def test_test_run_sensor_cases(
        self,
        location_codes: list[str],
        expected_count: int,
    ) -> None:
        if location_codes:
            sensors = Sensor.from_location_codes(location_codes)
            test_run = TestRun(
                capture=RunCapture(run_id="r1", setup=RunSetup(sensors=sensors)),
            )
        else:
            test_run = TestRun(capture=RunCapture(run_id="r1"))

        assert len(test_run.capture.setup.sensors) == expected_count
        assert test_run.sensor_count == expected_count


class TestDrivingSegment:
    """Tests for DrivingSegment diagnostic-usability semantics."""

    @pytest.mark.parametrize(
        ("segment", "expected"),
        [
            pytest.param(
                DrivingSegment(
                    phase=DrivingPhase.CRUISE,
                    start_idx=0,
                    end_idx=99,
                    sample_count=100,
                ),
                True,
                id="cruise-usable",
            ),
            pytest.param(
                DrivingSegment(
                    phase=DrivingPhase.IDLE,
                    start_idx=0,
                    end_idx=99,
                    sample_count=100,
                ),
                False,
                id="idle-not-usable",
            ),
            pytest.param(
                DrivingSegment(
                    phase=DrivingPhase.CRUISE,
                    start_idx=0,
                    end_idx=4,
                    sample_count=5,
                ),
                False,
                id="too-few-samples",
            ),
        ],
    )
    def test_diagnostic_usability_cases(self, segment: DrivingSegment, expected: bool) -> None:
        assert segment.is_diagnostically_usable is expected

    @pytest.mark.parametrize(
        ("segment", "expected"),
        [
            pytest.param(
                DrivingSegment(
                    phase=DrivingPhase.CRUISE,
                    start_idx=0,
                    end_idx=10,
                    start_t_s=1.0,
                    end_t_s=3.5,
                ),
                pytest.approx(2.5),
                id="with-timestamps",
            ),
            pytest.param(
                DrivingSegment(phase=DrivingPhase.CRUISE, start_idx=0, end_idx=10),
                None,
                id="without-timestamps",
            ),
        ],
    )
    def test_duration_s_cases(
        self,
        segment: DrivingSegment,
        expected: float | None,
    ) -> None:
        assert segment.duration_s == expected

    @pytest.mark.parametrize(
        ("phase", "expected"),
        [
            pytest.param(DrivingPhase.CRUISE, True, id="cruise"),
            pytest.param(DrivingPhase.ACCELERATION, False, id="acceleration"),
            pytest.param(DrivingPhase.IDLE, False, id="idle"),
        ],
    )
    def test_is_cruise_property_cases(self, phase: DrivingPhase, expected: bool) -> None:
        segment = DrivingSegment(phase=phase, start_idx=0, end_idx=10)
        assert segment.is_cruise is expected


class TestDrivingPhaseSegment:
    """Tests for DrivingPhaseSegment (per-phase-type summary)."""

    def test_construction_basic(self) -> None:
        seg = DrivingPhaseSegment(
            phase=DrivingPhase.CRUISE,
            duration_s=12.5,
            sample_count=250,
            speed_min_kmh=30.0,
            speed_max_kmh=80.0,
            fraction=0.6,
        )
        assert seg.phase is DrivingPhase.CRUISE
        assert seg.duration_s == 12.5
        assert seg.sample_count == 250
        assert seg.speed_min_kmh == 30.0
        assert seg.speed_max_kmh == 80.0
        assert seg.fraction == pytest.approx(0.6)

    def test_frozen_immutability(self) -> None:
        seg = DrivingPhaseSegment(phase=DrivingPhase.IDLE, duration_s=1.0, sample_count=10)
        with pytest.raises(dataclasses.FrozenInstanceError):
            seg.sample_count = 99

    def test_optional_speed_fields_default_none(self) -> None:
        seg = DrivingPhaseSegment(phase=DrivingPhase.ACCELERATION, duration_s=5.0, sample_count=100)
        assert seg.speed_min_kmh is None
        assert seg.speed_max_kmh is None

    def test_fraction_defaults_to_zero(self) -> None:
        seg = DrivingPhaseSegment(phase=DrivingPhase.DECELERATION, duration_s=2.0, sample_count=0)
        assert seg.fraction == 0.0

    def test_has_slots(self) -> None:
        assert hasattr(DrivingPhaseSegment, "__slots__")


class TestTestRunSegments:
    """Tests for TestRun segment aggregate queries."""

    def test_usable_segments_filters_idle(self) -> None:
        segments = (
            DrivingSegment(phase=DrivingPhase.CRUISE, start_idx=0, end_idx=49, sample_count=50),
            DrivingSegment(phase=DrivingPhase.IDLE, start_idx=50, end_idx=99, sample_count=50),
            DrivingSegment(
                phase=DrivingPhase.ACCELERATION, start_idx=100, end_idx=119, sample_count=20
            ),
        )
        tr = TestRun(
            capture=RunCapture(run_id="r1"),
            driving_segments=segments,
        )
        usable = tr.usable_segments
        assert len(usable) == 2
        assert all(s.phase is not DrivingPhase.IDLE for s in usable)

    def test_total_usable_samples(self) -> None:
        segments = (
            DrivingSegment(phase=DrivingPhase.CRUISE, start_idx=0, end_idx=49, sample_count=50),
            DrivingSegment(phase=DrivingPhase.IDLE, start_idx=50, end_idx=99, sample_count=50),
            DrivingSegment(phase=DrivingPhase.CRUISE, start_idx=100, end_idx=129, sample_count=30),
        )
        tr = TestRun(
            capture=RunCapture(run_id="r1"),
            driving_segments=segments,
        )
        assert tr.total_usable_samples == 80
