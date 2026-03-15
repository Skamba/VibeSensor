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

from vibesensor.shared.boundaries.finding import finding_from_payload
from vibesensor.shared.boundaries.finding_evidence import finding_evidence_from_metrics
from vibesensor.shared.boundaries.location_hotspot import location_hotspot_from_payload
from vibesensor.shared.boundaries.run_suitability import run_suitability_from_payload
from vibesensor.shared.boundaries.speed_profile import speed_profile_from_stats
from vibesensor.shared.boundaries.vibration_origin import (
    origin_payload_from_finding,
    vibration_origin_from_payload,
)
from vibesensor.domain import (
    ConfidenceAssessment,
    ConfigurationSnapshot,
    Diagnosis,
    DiagnosticCase,
    DiagnosticCaseEpistemicRule,
    DiagnosticReasoning,
    DrivingPhase,
    DrivingSegment,
    Finding,
    FindingEvidence,
    Hypothesis,
    HypothesisStatus,
    LocationHotspot,
    RunCapture,
    RunSuitability,
    Sensor,
    SensorPlacement,
    SpeedProfile,
    SuitabilityCheck,
    TestRun,
    VibrationOrigin,
    VibrationSource,
)
from vibesensor.domain import (
    RecommendedAction as DomainRecommendedAction,
)
from vibesensor.domain import (
    TestPlan as DomainTestPlan,
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
    hypotheses: tuple[Hypothesis, ...] = (),
    findings: tuple[Finding, ...],
    top_causes: tuple[Finding, ...],
) -> TestRun:
    return TestRun(
        capture=RunCapture(run_id=run_id),
        reasoning=DiagnosticReasoning(hypotheses=hypotheses),
        findings=findings,
        top_causes=top_causes,
    )


def _make_hypothesis(
    hypothesis_id: str,
    *,
    support_score: float,
    contradiction_score: float = 0.0,
    status: HypothesisStatus = HypothesisStatus.SUPPORTED,
    signature_keys: tuple[str, ...] = (),
) -> Hypothesis:
    return Hypothesis(
        hypothesis_id=hypothesis_id,
        source="engine",
        support_score=support_score,
        contradiction_score=contradiction_score,
        status=status,
        signature_keys=signature_keys,
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
        e = finding_evidence_from_metrics(d)
        assert e.match_rate == 0.85
        assert e.snr_db == 12.5
        assert e.presence_ratio == 0.7
        assert e.burstiness == 0.1
        assert e.spatial_concentration == 0.9
        assert e.vibration_strength_db == 25.3
        assert ("accel", 0.6) in e.phase_confidences
        assert ("cruise", 0.9) in e.phase_confidences

    def test_from_metrics_dict_empty(self) -> None:
        e = finding_evidence_from_metrics({})
        assert e.match_rate == 0.0
        assert e.snr_db is None
        assert e.phase_confidences == ()

    def test_from_metrics_dict_snr_ratio_fallback(self) -> None:
        e = finding_evidence_from_metrics({"snr_ratio": 8.0})
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

    def test_origin_payload_from_finding_uses_fallback_when_no_origin(self) -> None:
        """When a Finding has no origin or location, the fallback payload is returned."""
        finding = Finding(finding_id="F002", suspected_source="unknown")
        fallback = {"location": "rear_right", "suspected_source": "suspension"}
        payload = origin_payload_from_finding(finding, fallback)
        assert payload["location"] == "rear_right"
        assert payload["suspected_source"] == "suspension"

    def test_from_finding_returns_existing_origin(self) -> None:
        """from_finding() returns the finding's origin when already set."""
        existing_origin = VibrationOrigin.from_analysis_inputs(
            suspected_source=VibrationSource.WHEEL_TIRE,
            dominance_ratio=1.2,
            speed_band="80-90 km/h",
            reason="pre-existing",
        )
        finding = Finding(
            finding_id="F001",
            suspected_source="wheel/tire",
            origin=existing_origin,
        )
        result = VibrationOrigin.from_finding(finding)
        assert result is existing_origin

    def test_from_finding_constructs_from_location_hotspot(self) -> None:
        """from_finding() constructs origin from hotspot when no origin is set."""
        hotspot = LocationHotspot.from_analysis_inputs(
            strongest_location="front_left",
            ambiguous=False,
        )
        finding = Finding(
            finding_id="F002",
            suspected_source="wheel/tire",
            strongest_speed_band="80-90 km/h",
            dominance_ratio=1.3,
            location=hotspot,
        )
        result = VibrationOrigin.from_finding(finding)
        assert result is not None
        assert result.hotspot is hotspot
        assert result.suspected_source == VibrationSource.WHEEL_TIRE
        assert result.speed_band == "80-90 km/h"
        assert result.dominance_ratio == 1.3

    def test_from_finding_constructs_from_strongest_location(self) -> None:
        """from_finding() constructs minimal origin from strongest_location."""
        finding = Finding(
            finding_id="F003",
            suspected_source="engine",
            strongest_location="rear",
            strongest_speed_band="60-70 km/h",
            dominance_ratio=0.9,
        )
        result = VibrationOrigin.from_finding(finding)
        assert result is not None
        assert result.hotspot is None
        assert result.suspected_source == VibrationSource.ENGINE
        assert result.speed_band == "60-70 km/h"

    def test_from_finding_returns_none_when_no_data(self) -> None:
        """from_finding() returns None for a finding with no origin data."""
        finding = Finding(finding_id="F004", suspected_source="unknown")
        assert VibrationOrigin.from_finding(finding) is None

    def test_suspected_vibration_origin_is_boundary_type(self) -> None:
        """SuspectedVibrationOrigin is importable from boundaries, not analysis."""
        from vibesensor.shared.boundaries.vibration_origin import SuspectedVibrationOrigin

        origin: SuspectedVibrationOrigin = {
            "location": "front_left",
            "suspected_source": "wheel/tire",
        }
        assert origin["location"] == "front_left"


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


class TestRecommendedAction:
    def test_render_queries_normalize_blank_optional_fields(self) -> None:
        action = DomainRecommendedAction(
            action_id="inspect_mount",
            what="  ACTION_ENGINE_MOUNTS_WHAT  ",
            why="   ",
            confirm=" movement increases ",
            falsify="  ",
            eta=" 15-30 min ",
        )

        assert action.instruction == "ACTION_ENGINE_MOUNTS_WHAT"
        assert action.rationale is None
        assert action.confirmation_signal == "movement increases"
        assert action.falsification_signal is None
        assert action.estimated_duration == "15-30 min"
        assert action.has_supporting_detail is True

    def test_render_queries_report_no_supporting_detail(self) -> None:
        action = DomainRecommendedAction(
            action_id="inspect_mount",
            what="ACTION_ENGINE_MOUNTS_WHAT",
        )

        assert action.rationale is None
        assert action.confirmation_signal is None
        assert action.falsification_signal is None
        assert action.estimated_duration is None
        assert action.has_supporting_detail is False


class TestTestPlan:
    def test_supports_case_completion_without_pending_actions(self) -> None:
        plan = DomainTestPlan()

        assert plan.has_actions is False
        assert plan.supports_case_completion is True
        assert plan.is_complete is True
        assert plan.needs_more_data() is False

    def test_pending_actions_do_not_imply_more_data(self) -> None:
        plan = DomainTestPlan(
            actions=(
                DomainRecommendedAction(
                    action_id="wheel_balance_and_runout",
                    what="ACTION_WHEEL_BALANCE_WHAT",
                ),
            ),
        )

        assert plan.has_actions is True
        assert plan.supports_case_completion is True
        assert plan.is_complete is False
        assert plan.needs_more_data() is False

    def test_requires_additional_data_blocks_case_completion(self) -> None:
        plan = DomainTestPlan(
            actions=(
                DomainRecommendedAction(
                    action_id="general_mechanical_inspection",
                    what="COLLECT_A_LONGER_RUN_WITH_STABLE_DRIVING_CONDITIONS",
                ),
            ),
            requires_additional_data=True,
        )

        assert plan.supports_case_completion is False
        assert plan.needs_more_data() is True


class TestDiagnosticCase:
    def test_case_complete_when_findings_exist_and_plan_supports_completion(self) -> None:
        f = Finding(suspected_source="engine", confidence=0.74)
        case = DiagnosticCase(
            case_id="case-1",
            diagnoses=(
                Diagnosis.from_finding_group(
                    ("engine", None),
                    (f,),
                    DiagnosticCaseEpistemicRule.UNRESOLVED_SUPPORT,
                ),
            ),
            test_plan=DomainTestPlan(
                actions=(
                    DomainRecommendedAction(
                        action_id="engine_mounts_and_accessories",
                        what="ACTION_ENGINE_MOUNTS_WHAT",
                    ),
                ),
            ),
        )

        assert case.is_complete is True
        assert case.needs_more_data is False

    def test_case_incomplete_when_test_plan_requires_more_data(self) -> None:
        f = Finding(suspected_source="wheel/tire", confidence=0.81)
        case = DiagnosticCase(
            case_id="case-2",
            diagnoses=(
                Diagnosis.from_finding_group(
                    ("wheel/tire", None),
                    (f,),
                    DiagnosticCaseEpistemicRule.UNRESOLVED_SUPPORT,
                ),
            ),
            test_plan=DomainTestPlan(requires_additional_data=True),
        )

        assert case.is_complete is False
        assert case.needs_more_data is True

    def test_hypothesis_epistemic_rules_mark_strengthening(self) -> None:
        case = DiagnosticCase(
            case_id="case-strengthening",
            test_runs=(
                _make_test_run(
                    run_id="run-1",
                    hypotheses=(_make_hypothesis("hyp-engine", support_score=0.42),),
                    findings=(),
                    top_causes=(),
                ),
                _make_test_run(
                    run_id="run-2",
                    hypotheses=(_make_hypothesis("hyp-engine", support_score=0.76),),
                    findings=(),
                    top_causes=(),
                ),
            ),
        )

        assert (
            case.hypothesis_epistemic_rules()["hyp-engine"]
            is DiagnosticCaseEpistemicRule.STRENGTHENING
        )

    def test_hypothesis_epistemic_rules_mark_weakening(self) -> None:
        case = DiagnosticCase(
            case_id="case-weakening",
            test_runs=(
                _make_test_run(
                    run_id="run-1",
                    hypotheses=(_make_hypothesis("hyp-engine", support_score=0.83),),
                    findings=(),
                    top_causes=(),
                ),
                _make_test_run(
                    run_id="run-2",
                    hypotheses=(_make_hypothesis("hyp-engine", support_score=0.51),),
                    findings=(),
                    top_causes=(),
                ),
            ),
        )

        assert (
            case.hypothesis_epistemic_rules()["hyp-engine"] is DiagnosticCaseEpistemicRule.WEAKENING
        )

    def test_hypothesis_epistemic_rules_mark_contradiction(self) -> None:
        case = DiagnosticCase(
            case_id="case-contradiction",
            test_runs=(
                _make_test_run(
                    run_id="run-1",
                    hypotheses=(_make_hypothesis("hyp-engine", support_score=0.74),),
                    findings=(),
                    top_causes=(),
                ),
                _make_test_run(
                    run_id="run-2",
                    hypotheses=(
                        _make_hypothesis(
                            "hyp-engine",
                            support_score=0.15,
                            contradiction_score=0.82,
                            status=HypothesisStatus.REJECTED,
                        ),
                    ),
                    findings=(),
                    top_causes=(),
                ),
            ),
        )

        assert (
            case.hypothesis_epistemic_rules()["hyp-engine"]
            is DiagnosticCaseEpistemicRule.CONTRADICTION
        )

    def test_hypothesis_epistemic_rules_mark_retirement(self) -> None:
        case = DiagnosticCase(
            case_id="case-retirement",
            test_runs=(
                _make_test_run(
                    run_id="run-1",
                    hypotheses=(_make_hypothesis("hyp-engine", support_score=0.69),),
                    findings=(),
                    top_causes=(),
                ),
                _make_test_run(
                    run_id="run-2",
                    hypotheses=(
                        _make_hypothesis(
                            "hyp-engine",
                            support_score=0.0,
                            status=HypothesisStatus.RETIRED,
                        ),
                    ),
                    findings=(),
                    top_causes=(),
                ),
            ),
        )

        assert (
            case.hypothesis_epistemic_rules()["hyp-engine"]
            is DiagnosticCaseEpistemicRule.RETIREMENT
        )

    def test_hypothesis_epistemic_rules_mark_unresolved_support(self) -> None:
        case = DiagnosticCase(
            case_id="case-unresolved",
            test_runs=(
                _make_test_run(
                    run_id="run-1",
                    hypotheses=(
                        _make_hypothesis(
                            "hyp-engine",
                            support_score=0.18,
                            status=HypothesisStatus.CANDIDATE,
                            signature_keys=("order-1",),
                        ),
                    ),
                    findings=(),
                    top_causes=(),
                ),
                _make_test_run(
                    run_id="run-2",
                    hypotheses=(
                        _make_hypothesis(
                            "hyp-engine",
                            support_score=0.24,
                            status=HypothesisStatus.INCONCLUSIVE,
                            signature_keys=("order-1", "phase-cruise"),
                        ),
                    ),
                    findings=(),
                    top_causes=(),
                ),
            ),
        )

        assert (
            case.hypothesis_epistemic_rules()["hyp-engine"]
            is DiagnosticCaseEpistemicRule.UNRESOLVED_SUPPORT
        )

    def test_classify_finding_sequence_marks_strengthening(self) -> None:
        rule = DiagnosticCase.classify_finding_sequence(
            (
                _make_test_run_finding("F001", confidence=0.44),
                _make_test_run_finding("F002", confidence=0.79),
            )
        )

        assert rule is DiagnosticCaseEpistemicRule.STRENGTHENING

    def test_classify_finding_sequence_marks_contradiction(self) -> None:
        rule = DiagnosticCase.classify_finding_sequence(
            (
                _make_test_run_finding("F001", suspected_source="wheel/tire"),
                _make_test_run_finding(
                    "F002",
                    suspected_source="driveline",
                    strongest_location="center",
                ),
            )
        )

        assert rule is DiagnosticCaseEpistemicRule.CONTRADICTION

    def test_classify_finding_sequence_marks_unresolved_support(self) -> None:
        rule = DiagnosticCase.classify_finding_sequence(
            (
                _make_test_run_finding(
                    "F001",
                    suspected_source="unknown",
                    strongest_location="unknown",
                ),
                _make_test_run_finding(
                    "F002",
                    suspected_source="unknown",
                    strongest_location="unknown",
                ),
            )
        )

        assert rule is DiagnosticCaseEpistemicRule.UNRESOLVED_SUPPORT


class TestDiagnosticCaseReconcile:
    def test_reconcile_latest_wins_over_best_score(self) -> None:
        """Latest run's hypothesis is kept, even if an earlier run had higher support_score."""
        case = DiagnosticCase.start()
        case = case.add_run(
            _make_test_run(
                run_id="run-1",
                hypotheses=(_make_hypothesis("hyp-engine", support_score=0.90),),
                findings=(),
                top_causes=(),
            ),
        )
        case = case.add_run(
            _make_test_run(
                run_id="run-2",
                hypotheses=(_make_hypothesis("hyp-engine", support_score=0.45),),
                findings=(),
                top_causes=(),
            ),
        )

        assert len(case.hypotheses) == 1
        assert case.hypotheses[0].support_score == 0.45

    def test_reconcile_excludes_retired_hypotheses(self) -> None:
        """A hypothesis RETIRED in the latest run must be absent from case.hypotheses."""
        case = DiagnosticCase.start()
        case = case.add_run(
            _make_test_run(
                run_id="run-1",
                hypotheses=(_make_hypothesis("hyp-engine", support_score=0.72),),
                findings=(),
                top_causes=(),
            ),
        )
        case = case.add_run(
            _make_test_run(
                run_id="run-2",
                hypotheses=(
                    _make_hypothesis(
                        "hyp-engine",
                        support_score=0.0,
                        status=HypothesisStatus.RETIRED,
                    ),
                ),
                findings=(),
                top_causes=(),
            ),
        )

        assert len(case.hypotheses) == 0

    def test_reconcile_finding_latest_wins(self) -> None:
        """Latest run's finding is kept, even if an earlier run had higher confidence."""
        high_finding = _make_test_run_finding("F001", confidence=0.95)
        low_finding = _make_test_run_finding("F002", confidence=0.40)
        case = DiagnosticCase.start()
        case = case.add_run(
            _make_test_run(
                run_id="run-1",
                findings=(high_finding,),
                top_causes=(high_finding,),
            ),
        )
        case = case.add_run(
            _make_test_run(
                run_id="run-2",
                findings=(low_finding,),
                top_causes=(low_finding,),
            ),
        )

        assert len(case.diagnoses) == 1
        assert case.diagnoses[0].representative_finding.finding_id == "F002"
        assert case.diagnoses[0].representative_finding.confidence == 0.40

    def test_reconcile_action_lowest_priority_wins(self) -> None:
        """Action merge picks the lowest priority for a given action_id."""
        action_high = DomainRecommendedAction(
            action_id="inspect_tires", what="Inspect tires", priority=50
        )
        action_low = DomainRecommendedAction(
            action_id="inspect_tires", what="Inspect tires v2", priority=10
        )
        plan = DomainTestPlan(actions=(action_high,))

        case = DiagnosticCase.start(test_plan=plan)
        case = case.add_run(
            _make_test_run(
                run_id="run-1",
                hypotheses=(),
                findings=(),
                top_causes=(),
            ),
        )
        case = case.add_run(
            TestRun(
                capture=RunCapture(run_id="run-2"),
                findings=(),
                top_causes=(),
                test_plan=DomainTestPlan(actions=(action_low,)),
            ),
        )

        matching = [a for a in case.recommended_actions if a.action_id == "inspect_tires"]
        assert len(matching) == 1
        assert matching[0].priority == 10

    def test_reconcile_multi_run_integration(self) -> None:
        """Three-run scenario: retired hypothesis excluded, latest findings kept, actions merged."""
        hyp_engine_r1 = _make_hypothesis("hyp-engine", support_score=0.60)
        hyp_tire_r1 = _make_hypothesis("hyp-tire", support_score=0.40)
        finding_tire_r1 = _make_test_run_finding(
            "F001", suspected_source="wheel/tire", confidence=0.80
        )
        action_r1 = DomainRecommendedAction(
            action_id="check_tires", what="Check tires", priority=30
        )

        hyp_engine_r2 = _make_hypothesis(
            "hyp-engine", support_score=0.0, status=HypothesisStatus.RETIRED
        )
        hyp_tire_r2 = _make_hypothesis("hyp-tire", support_score=0.65)
        finding_tire_r2 = _make_test_run_finding(
            "F002", suspected_source="wheel/tire", confidence=0.55
        )
        action_r2 = DomainRecommendedAction(
            action_id="check_tires", what="Check tires", priority=20
        )

        hyp_tire_r3 = _make_hypothesis("hyp-tire", support_score=0.78)
        finding_tire_r3 = _make_test_run_finding(
            "F003", suspected_source="wheel/tire", confidence=0.70
        )
        action_r3 = DomainRecommendedAction(
            action_id="rotate_wheels", what="Rotate wheels", priority=40
        )

        case = DiagnosticCase.start()
        case = case.add_run(
            TestRun(
                capture=RunCapture(run_id="run-1"),
                reasoning=DiagnosticReasoning(hypotheses=(hyp_engine_r1, hyp_tire_r1)),
                findings=(finding_tire_r1,),
                top_causes=(finding_tire_r1,),
                test_plan=DomainTestPlan(actions=(action_r1,)),
            ),
        )
        case = case.add_run(
            TestRun(
                capture=RunCapture(run_id="run-2"),
                reasoning=DiagnosticReasoning(hypotheses=(hyp_engine_r2, hyp_tire_r2)),
                findings=(finding_tire_r2,),
                top_causes=(finding_tire_r2,),
                test_plan=DomainTestPlan(actions=(action_r2,)),
            ),
        )
        case = case.add_run(
            TestRun(
                capture=RunCapture(run_id="run-3"),
                reasoning=DiagnosticReasoning(hypotheses=(hyp_tire_r3,)),
                findings=(finding_tire_r3,),
                top_causes=(finding_tire_r3,),
                test_plan=DomainTestPlan(actions=(action_r3,)),
            ),
        )

        # hyp-engine is RETIRED → excluded; only hyp-tire remains
        hyp_ids = [h.hypothesis_id for h in case.hypotheses]
        assert "hyp-engine" not in hyp_ids
        assert "hyp-tire" in hyp_ids
        assert case.hypotheses[0].support_score == 0.78  # latest run

        # Finding: latest run's finding kept (F003, confidence=0.70)
        assert len(case.diagnoses) == 1
        assert case.diagnoses[0].representative_finding.finding_id == "F003"
        assert case.diagnoses[0].representative_finding.confidence == 0.70

        # Actions: check_tires picks lowest priority (20), rotate_wheels (40) also present
        action_ids = {a.action_id for a in case.recommended_actions}
        assert "check_tires" in action_ids
        assert "rotate_wheels" in action_ids
        check_tires = next(a for a in case.recommended_actions if a.action_id == "check_tires")
        assert check_tires.priority == 20


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
        sp = speed_profile_from_stats(speed_stats, phase_summary)
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
        sp = speed_profile_from_stats({})
        assert sp.min_kmh == 0.0
        assert sp.max_kmh == 0.0
        assert not sp.steady_speed
        assert not sp.has_acceleration
        assert sp.known_speed_fraction == 1.0
        assert sp.driving_fraction == 1.0

    def test_from_stats_no_phase(self) -> None:
        sp = speed_profile_from_stats({"min_kmh": 10, "max_kmh": 50})
        assert sp.has_cruise is False
        assert sp.cruise_fraction == 0.0

    def test_from_stats_reads_phase_fallbacks_from_nested_phase_maps(self) -> None:
        sp = speed_profile_from_stats(
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

    @pytest.mark.parametrize(
        "check_key,state,details,expected_key",
        [
            ("SUITABILITY_CHECK_SPEED_VARIATION", "pass", (), "SUITABILITY_SPEED_VARIATION_PASS"),
            ("SUITABILITY_CHECK_SPEED_VARIATION", "warn", (), "SUITABILITY_SPEED_VARIATION_WARN"),
            ("SUITABILITY_CHECK_SENSOR_COVERAGE", "pass", (), "SUITABILITY_SENSOR_COVERAGE_PASS"),
            ("SUITABILITY_CHECK_SENSOR_COVERAGE", "warn", (), "SUITABILITY_SENSOR_COVERAGE_WARN"),
            (
                "SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
                "pass",
                (),
                "SUITABILITY_REFERENCE_COMPLETENESS_PASS",
            ),
            (
                "SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
                "warn",
                (),
                "SUITABILITY_REFERENCE_COMPLETENESS_WARN",
            ),
            (
                "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                "pass",
                (),
                "SUITABILITY_SATURATION_PASS",
            ),
            (
                "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                "warn",
                (("sat_count", 3),),
                "SUITABILITY_SATURATION_WARN",
            ),
            ("SUITABILITY_CHECK_FRAME_INTEGRITY", "pass", (), "SUITABILITY_FRAME_INTEGRITY_PASS"),
            (
                "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "warn",
                (("total_dropped", 2), ("total_overflow", 1)),
                "SUITABILITY_FRAME_INTEGRITY_WARN",
            ),
            (
                "SUITABILITY_CHECK_ANALYSIS_SAMPLING",
                "warn",
                (("stride", 4),),
                "SUITABILITY_ANALYSIS_SAMPLING_STRIDE_WARNING",
            ),
        ],
    )
    def test_explanation_i18n_ref(
        self,
        check_key: str,
        state: str,
        details: tuple,
        expected_key: str,
    ) -> None:
        c = SuitabilityCheck(check_key=check_key, state=state, details=details)
        ref = c.explanation_i18n_ref()
        assert isinstance(ref, dict)
        assert ref["_i18n_key"] == expected_key

    def test_explanation_i18n_ref_saturation_warn_includes_sat_count(self) -> None:
        c = SuitabilityCheck(
            check_key="SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
            state="warn",
            details=(("sat_count", 5),),
        )
        ref = c.explanation_i18n_ref()
        assert isinstance(ref, dict)
        assert ref["sat_count"] == 5

    def test_explanation_i18n_ref_frame_integrity_warn_includes_counts(self) -> None:
        c = SuitabilityCheck(
            check_key="SUITABILITY_CHECK_FRAME_INTEGRITY",
            state="warn",
            details=(("total_dropped", 10), ("total_overflow", 3)),
        )
        ref = c.explanation_i18n_ref()
        assert isinstance(ref, dict)
        assert ref["total_dropped"] == 10
        assert ref["total_overflow"] == 3

    def test_explanation_i18n_ref_stride_includes_stride(self) -> None:
        c = SuitabilityCheck(
            check_key="SUITABILITY_CHECK_ANALYSIS_SAMPLING",
            state="warn",
            details=(("stride", 4),),
        )
        ref = c.explanation_i18n_ref()
        assert isinstance(ref, dict)
        assert ref["stride"] == "4"

    def test_explanation_i18n_ref_stride_no_details_returns_empty(self) -> None:
        c = SuitabilityCheck(
            check_key="SUITABILITY_CHECK_ANALYSIS_SAMPLING",
            state="warn",
        )
        assert c.explanation_i18n_ref() == ""

    def test_explanation_i18n_ref_unknown_key_returns_empty(self) -> None:
        c = SuitabilityCheck(check_key="UNKNOWN_CHECK", state="warn")
        assert c.explanation_i18n_ref() == ""


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
        rs = run_suitability_from_payload(checks)
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
        rs = run_suitability_from_payload([])
        assert rs.overall == "pass"

    def test_from_checks_legacy_key(self) -> None:
        rs = run_suitability_from_payload([{"check": "old_key", "state": "pass"}])
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
        f = finding_from_payload(payload)
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

    def test_finding_defaults_none(self) -> None:
        f = Finding(finding_id="F001")
        assert f.evidence is None
        assert f.location is None
        assert f.confidence_assessment is None


# ── Integration: TestRun with SpeedProfile/Suitability ──────────────────────


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
        from vibesensor.shared.boundaries.diagnostic_case import test_run_from_summary

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
        result = test_run_from_summary(summary)
        assert result.speed_profile is not None
        assert result.speed_profile.min_kmh == 30.0
        assert result.speed_profile.steady_speed
        assert result.speed_profile.has_cruise
        assert result.speed_profile.cruise_fraction == pytest.approx(0.65)

    def test_from_summary_extracts_suitability(self) -> None:
        from vibesensor.shared.boundaries.diagnostic_case import test_run_from_summary

        summary = {
            "run_id": "test-123",
            "findings": [],
            "top_causes": [],
            "run_suitability": [
                {"check_key": "speed", "state": "pass", "explanation": "OK"},
                {"check_key": "noise", "state": "warn", "explanation": "Marginal"},
            ],
        }
        result = test_run_from_summary(summary)
        assert result.suitability is not None
        assert result.suitability.overall == "caution"
        assert len(result.suitability.checks) == 2

    def test_from_summary_no_speed_stats(self) -> None:
        from vibesensor.shared.boundaries.diagnostic_case import test_run_from_summary

        summary = {"run_id": "test-123", "findings": [], "top_causes": []}
        result = test_run_from_summary(summary)
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


class TestDiagnosticCaseCompleteness:
    """Tests for strengthened is_complete, has_usable_evidence, evidence_gaps."""

    @staticmethod
    def _actionable_finding() -> Finding:
        return Finding(
            finding_id="F001",
            suspected_source=VibrationSource.WHEEL_TIRE,
            confidence=0.82,
            strongest_location="front_left",
        )

    @staticmethod
    def _non_actionable_finding() -> Finding:
        return Finding(
            finding_id="F002",
            suspected_source=VibrationSource.UNKNOWN,
            confidence=0.50,
        )

    @staticmethod
    def _passing_suitability() -> RunSuitability:
        return RunSuitability(
            checks=(SuitabilityCheck(check_key="SUITABILITY_CHECK_SPEED_VARIATION", state="pass"),)
        )

    @staticmethod
    def _failing_suitability() -> RunSuitability:
        return RunSuitability(
            checks=(SuitabilityCheck(check_key="SUITABILITY_CHECK_SPEED_VARIATION", state="fail"),)
        )

    def _make_case(
        self,
        *,
        findings: tuple[Finding, ...] = (),
        suitability: RunSuitability | None = None,
        test_plan: DomainTestPlan | None = None,
        include_run: bool = True,
    ) -> DiagnosticCase:
        runs: tuple[TestRun, ...] = ()
        if include_run:
            runs = (
                TestRun(
                    capture=RunCapture(run_id="run-1"),
                    findings=findings,
                    top_causes=tuple(f for f in findings if f.is_actionable),
                    suitability=suitability,
                ),
            )
        return DiagnosticCase(
            case_id="case-1",
            diagnoses=tuple(
                Diagnosis.from_finding_group(
                    (
                        f.source_normalized,
                        f.strongest_location
                        if not Finding.is_unknown_location(f.strongest_location)
                        else None,
                    ),
                    (f,),
                    DiagnosticCaseEpistemicRule.UNRESOLVED_SUPPORT,
                )
                for f in findings
            ),
            test_runs=runs,
            test_plan=test_plan or DomainTestPlan(),
        )

    def test_complete_with_actionable_findings(self) -> None:
        case = self._make_case(
            findings=(self._actionable_finding(),),
            suitability=self._passing_suitability(),
        )
        assert case.is_complete is True
        assert case.has_usable_evidence is True
        assert case.evidence_gaps == ()

    def test_incomplete_without_findings(self) -> None:
        case = self._make_case(
            findings=(),
            suitability=self._passing_suitability(),
        )
        assert case.is_complete is False
        assert case.has_usable_evidence is False
        assert "no_findings" in case.evidence_gaps

    def test_incomplete_with_non_actionable_findings_only(self) -> None:
        case = self._make_case(
            findings=(self._non_actionable_finding(),),
            suitability=self._passing_suitability(),
        )
        assert case.is_complete is False
        assert case.has_usable_evidence is False
        assert "no_actionable_findings" in case.evidence_gaps

    def test_incomplete_when_primary_run_unusable(self) -> None:
        case = self._make_case(
            findings=(self._actionable_finding(),),
            suitability=self._failing_suitability(),
        )
        assert case.is_complete is False
        assert case.has_usable_evidence is False
        assert "primary_run_unusable" in case.evidence_gaps

    def test_complete_when_suitability_absent(self) -> None:
        case = self._make_case(
            findings=(self._actionable_finding(),),
            suitability=None,
        )
        assert case.is_complete is True
        assert case.has_usable_evidence is True
        assert case.evidence_gaps == ()

    def test_evidence_gaps_includes_additional_data(self) -> None:
        case = self._make_case(
            findings=(self._actionable_finding(),),
            suitability=self._passing_suitability(),
            test_plan=DomainTestPlan(requires_additional_data=True),
        )
        assert case.is_complete is False
        assert "additional_data_required" in case.evidence_gaps


class TestConfigurationSnapshot:
    """Tests for ConfigurationSnapshot construction, freezing, and case attachment."""

    def test_from_metadata_extracts_typed_fields(self) -> None:
        md = {
            "sensor_model": "MPU6050",
            "firmware_version": "1.2.3",
            "raw_sample_rate_hz": 100.0,
            "feature_interval_s": 0.5,
            "final_drive_ratio": 3.73,
            "tire_width_mm": 205,
            "tire_aspect_pct": 55,
            "rim_in": 16,
        }
        snap = ConfigurationSnapshot.from_metadata(md)
        assert snap.sensor_model == "MPU6050"
        assert snap.firmware_version == "1.2.3"
        assert snap.raw_sample_rate_hz == 100.0
        assert snap.feature_interval_s == 0.5
        assert snap.final_drive_ratio == 3.73
        assert snap.tire_spec is not None

    def test_from_metadata_with_empty_dict(self) -> None:
        snap = ConfigurationSnapshot.from_metadata({})
        assert snap.sensor_model is None
        assert snap.firmware_version is None
        assert snap.raw_sample_rate_hz is None
        assert snap.feature_interval_s is None
        assert snap.final_drive_ratio is None

    def test_from_metadata_coerces_string_floats(self) -> None:
        md = {
            "raw_sample_rate_hz": "100.0",
            "feature_interval_s": "0.5",
            "final_drive_ratio": "3.73",
        }
        snap = ConfigurationSnapshot.from_metadata(md)
        assert snap.raw_sample_rate_hz == 100.0
        assert snap.feature_interval_s == 0.5
        assert snap.final_drive_ratio == 3.73

    def test_metadata_is_frozen(self) -> None:
        from types import MappingProxyType

        snap = ConfigurationSnapshot.from_metadata({"sensor_model": "MPU6050"})
        assert isinstance(snap.metadata, MappingProxyType)
        with pytest.raises(TypeError):
            snap.metadata["new_key"] = "value"  # type: ignore[index]

    def test_empty_snapshot_equality(self) -> None:
        assert ConfigurationSnapshot() == ConfigurationSnapshot()

    def test_from_metadata_preserves_raw_metadata(self) -> None:
        md = {"sensor_model": "MPU6050", "custom_key": "custom_value"}
        snap = ConfigurationSnapshot.from_metadata(md)
        assert snap.metadata["sensor_model"] == "MPU6050"
        assert snap.metadata["custom_key"] == "custom_value"

    def test_case_snapshot_accessible_via_capture(self) -> None:
        snap_a = ConfigurationSnapshot.from_metadata({"sensor_model": "MPU6050"})
        snap_b = ConfigurationSnapshot.from_metadata({"sensor_model": "BMI270"})

        from vibesensor.domain import RunSetup

        finding = Finding(suspected_source="wheel/tire", confidence=0.8)
        case = DiagnosticCase(case_id="case-snap")
        case = case.add_run(
            TestRun(
                capture=RunCapture(run_id="r1", setup=RunSetup(configuration_snapshot=snap_a)),
                findings=(finding,),
                top_causes=(finding,),
            )
        )
        case = case.add_run(
            TestRun(
                capture=RunCapture(run_id="r2", setup=RunSetup(configuration_snapshot=snap_b)),
                findings=(finding,),
                top_causes=(finding,),
            )
        )
        assert case.test_runs[0].capture.setup.configuration_snapshot == snap_a
        assert case.test_runs[1].capture.setup.configuration_snapshot == snap_b


# ── Sensor ───────────────────────────────────────────────────────────────────


class TestSensor:
    def test_from_location_codes_creates_sensors(self) -> None:
        sensors = Sensor.from_location_codes(["front_left_wheel", "rear_axle"])
        assert len(sensors) == 2
        assert sensors[0].sensor_id == "front_left_wheel"
        assert sensors[0].placement is not None
        assert sensors[0].placement.code == "front_left_wheel"
        assert sensors[1].sensor_id == "rear_axle"
        assert sensors[1].placement is not None
        assert sensors[1].placement.code == "rear_axle"

    def test_from_location_codes_empty(self) -> None:
        sensors = Sensor.from_location_codes([])
        assert sensors == ()

    def test_sensor_equality(self) -> None:
        placement = SensorPlacement.from_code("front_left_wheel")
        a = Sensor(sensor_id="front_left_wheel", placement=placement)
        b = Sensor(sensor_id="front_left_wheel", placement=placement)
        assert a == b


# ── TestRun sensors ──────────────────────────────────────────────────────────


class TestTestRunSensors:
    def test_test_run_default_sensors_empty(self) -> None:
        tr = TestRun(
            capture=RunCapture(run_id="r1"),
        )
        assert tr.capture.setup.sensors == ()
        assert tr.sensor_count == 0

    def test_test_run_with_sensors(self) -> None:
        from vibesensor.domain import RunSetup

        sensors = Sensor.from_location_codes(["front_left_wheel", "rear_axle"])
        tr = TestRun(
            capture=RunCapture(run_id="r1", setup=RunSetup(sensors=sensors)),
        )
        assert len(tr.capture.setup.sensors) == 2
        assert tr.sensor_count == 2

    def test_test_run_sensor_count_property(self) -> None:
        from vibesensor.domain import RunSetup

        sensors = Sensor.from_location_codes(["front_left_wheel", "rear_axle", "dashboard"])
        tr = TestRun(
            capture=RunCapture(run_id="r1", setup=RunSetup(sensors=sensors)),
        )
        assert tr.sensor_count == len(sensors)


class TestDrivingSegment:
    """Tests for DrivingSegment diagnostic-usability semantics."""

    def test_cruise_segment_is_usable(self) -> None:
        seg = DrivingSegment(phase=DrivingPhase.CRUISE, start_idx=0, end_idx=99, sample_count=100)
        assert seg.is_diagnostically_usable is True

    def test_idle_segment_is_not_usable(self) -> None:
        seg = DrivingSegment(phase=DrivingPhase.IDLE, start_idx=0, end_idx=99, sample_count=100)
        assert seg.is_diagnostically_usable is False

    def test_segment_with_few_samples_is_not_usable(self) -> None:
        seg = DrivingSegment(phase=DrivingPhase.CRUISE, start_idx=0, end_idx=4, sample_count=5)
        assert seg.is_diagnostically_usable is False

    def test_duration_with_timestamps(self) -> None:
        seg = DrivingSegment(
            phase=DrivingPhase.CRUISE,
            start_idx=0,
            end_idx=10,
            start_t_s=1.0,
            end_t_s=3.5,
        )
        assert seg.duration_s == pytest.approx(2.5)

    def test_duration_without_timestamps(self) -> None:
        seg = DrivingSegment(phase=DrivingPhase.CRUISE, start_idx=0, end_idx=10)
        assert seg.duration_s is None

    def test_is_cruise_property(self) -> None:
        cruise = DrivingSegment(phase=DrivingPhase.CRUISE, start_idx=0, end_idx=10)
        accel = DrivingSegment(phase=DrivingPhase.ACCELERATION, start_idx=0, end_idx=10)
        idle = DrivingSegment(phase=DrivingPhase.IDLE, start_idx=0, end_idx=10)
        assert cruise.is_cruise is True
        assert accel.is_cruise is False
        assert idle.is_cruise is False


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
