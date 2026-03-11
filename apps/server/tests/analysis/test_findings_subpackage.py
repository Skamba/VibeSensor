"""Tests for the findings modules structure and individual module contracts.

Validates that the findings_* modules are independently importable and
testable, and that each module exposes expected symbols.
"""

from __future__ import annotations

from typing import get_type_hints

import pytest

from vibesensor.analysis._types import AmplitudeMetric, Finding, MatchedPoint
from vibesensor.analysis.findings import (
    _build_findings,
    _classify_peak_type,
    _phase_speed_breakdown,
    _phase_to_str,
    _reference_missing_finding,
    _sensor_intensity_by_location,
    _speed_breakdown,
    _speed_profile_from_points,
)
from vibesensor.analysis.order_analysis import (
    OrderMatchAccumulator,
    _compute_effective_match_rate,
    assemble_order_finding,
)
from vibesensor.analysis.order_analysis import (
    compute_order_confidence as _compute_order_confidence,
)
from vibesensor.analysis.order_analysis import (
    detect_diffuse_excitation as _detect_diffuse_excitation,
)
from vibesensor.analysis.order_analysis import (
    suppress_engine_aliases as _suppress_engine_aliases,
)
from vibesensor.analysis.phase_segmentation import DrivingPhase
from vibesensor.constants import (
    CONFIDENCE_CEILING,
    CONFIDENCE_FLOOR,
    NEGLIGIBLE_STRENGTH_MAX_DB,
)

# -- Subpackage structure tests -----------------------------------------------


class TestFindingsModuleStructure:
    """Verify the findings modules are independently importable."""

    def test_modules_importable_independently(self) -> None:
        """Consolidated findings module must be directly importable with expected symbols."""
        from vibesensor.analysis import (  # noqa: F401
            findings,
            order_analysis,
        )

        # Verify key symbols exist
        assert hasattr(findings, "_build_findings")
        assert hasattr(findings, "_sensor_intensity_by_location")
        assert hasattr(findings, "_reference_missing_finding")
        assert hasattr(findings, "_build_persistent_peak_findings")
        assert hasattr(order_analysis, "_build_order_findings")


class TestCanonicalFindingModel:
    """Guard the canonical finding model and its main builder return types."""

    def test_finding_typed_dict_exposes_core_contract(self) -> None:
        hints = get_type_hints(Finding)
        assert {
            "finding_id",
            "suspected_source",
            "evidence_summary",
            "frequency_hz_or_order",
            "amplitude_metric",
            "confidence",
            "quick_checks",
            "evidence_metrics",
            "phase_evidence",
        }.issubset(hints)
        assert hints["amplitude_metric"] == AmplitudeMetric
        assert hints["matched_points"] == list[MatchedPoint]

    def test_main_finding_builders_return_canonical_model(self) -> None:
        assert _build_findings.__annotations__["return"] == "list[Finding]"
        assert assemble_order_finding.__annotations__["return"] == "tuple[float, Finding]"
        assert get_type_hints(OrderMatchAccumulator)["matched_points"] == list[MatchedPoint]


# -- speed_profile tests ------------------------------------------------------


class TestPhaseToStr:
    """Test _phase_to_str helper."""

    @pytest.mark.parametrize(
        ("input_val", "expected"),
        [
            pytest.param(None, None, id="none_returns_none"),
            pytest.param(DrivingPhase.CRUISE, "cruise", id="enum_value"),
            pytest.param("acceleration", "acceleration", id="string_passthrough"),
        ],
    )
    def test_phase_to_str(self, input_val: object, expected: str | None) -> None:
        assert _phase_to_str(input_val) == expected


class TestSpeedProfileFromPoints:
    """Test _speed_profile_from_points."""

    def test_empty_returns_none_tuple(self) -> None:
        assert _speed_profile_from_points([]) == (None, None, None)

    def test_single_point(self) -> None:
        peak, window, band = _speed_profile_from_points([(60.0, 0.05)])
        assert peak == 60.0
        assert window is not None
        assert band == "60-70 km/h"

    def test_multiple_points_peak_is_highest_amplitude(self) -> None:
        points = [(50.0, 0.01), (70.0, 0.05), (90.0, 0.02)]
        peak, window, band = _speed_profile_from_points(points)
        assert peak == 70.0

    def test_negative_speed_filtered(self) -> None:
        points = [(-10.0, 0.05), (0.0, 0.03), (60.0, 0.02)]
        peak, _, _ = _speed_profile_from_points(points)
        assert peak == 60.0


# -- reference_checks tests ---------------------------------------------------


class TestReferenceMissingFinding:
    """Test _reference_missing_finding builder."""

    def test_basic_structure(self) -> None:
        finding = _reference_missing_finding(
            finding_id="REF_SPEED",
            suspected_source="unknown",
            evidence_summary="Speed missing",
            quick_checks=["Check GPS", "Re-run"],
        )
        assert finding["finding_id"] == "REF_SPEED"
        assert finding["finding_type"] == "reference"
        assert finding["suspected_source"] == "unknown"
        assert finding["confidence"] is None
        assert len(finding["quick_checks"]) <= 3

    def test_quick_checks_truncated_to_3(self) -> None:
        finding = _reference_missing_finding(
            finding_id="REF_TEST",
            suspected_source="test",
            evidence_summary="Test",
            quick_checks=["a", "b", "c", "d", "e"],
        )
        assert len(finding["quick_checks"]) == 3


# -- _constants tests ---------------------------------------------------------


class TestSharedConstants:
    """Verify shared constants have expected values."""

    def test_negligible_strength_max_db(self) -> None:
        assert isinstance(NEGLIGIBLE_STRENGTH_MAX_DB, float)
        assert NEGLIGIBLE_STRENGTH_MAX_DB > 0

    def test_confidence_bounds(self) -> None:
        assert CONFIDENCE_FLOOR < CONFIDENCE_CEILING
        assert CONFIDENCE_FLOOR >= 0.0
        assert CONFIDENCE_CEILING <= 1.0


# -- classify_peak_type tests -------------------------------------------------


class TestClassifyPeakType:
    """Test _classify_peak_type classification logic."""

    @pytest.mark.parametrize(
        ("presence_ratio", "burstiness", "snr", "spatial_uniformity", "expected"),
        [
            (0.5, 2.0, 1.0, None, "baseline_noise"),
            (0.05, 2.0, 5.0, None, "transient"),
            (0.30, 6.0, 5.0, None, "transient"),
            (0.50, 2.0, 5.0, None, "patterned"),
            (0.25, 3.5, 5.0, None, "persistent"),
            (0.70, 1.5, 5.0, 0.90, "baseline_noise"),
        ],
    )
    def test_classification_cases(
        self,
        presence_ratio: float,
        burstiness: float,
        snr: float,
        spatial_uniformity: float | None,
        expected: str,
    ) -> None:
        assert (
            _classify_peak_type(
                presence_ratio,
                burstiness,
                snr=snr,
                spatial_uniformity=spatial_uniformity,
            )
            == expected
        )


# -- order_findings tests -----------------------------------------------------


class TestComputeEffectiveMatchRate:
    """Test _compute_effective_match_rate rescue logic."""

    def test_above_threshold_returns_original(self) -> None:
        rate, band, dominant = _compute_effective_match_rate(0.50, 0.25, {}, {}, {}, {})
        assert rate == 0.50
        assert band is None
        assert dominant is False

    def test_focused_speed_band_rescue(self) -> None:
        rate, band, dominant = _compute_effective_match_rate(
            0.10,  # below threshold
            0.25,
            {"70-80 km/h": 10},
            {"70-80 km/h": 8},
            {},
            {},
        )
        assert rate >= 0.25
        assert band == "70-80 km/h"


class TestDetectDiffuseExcitation:
    """Test _detect_diffuse_excitation."""

    def test_single_location_not_diffuse(self) -> None:
        is_diffuse, penalty = _detect_diffuse_excitation(
            {"front_left"},
            {"front_left": 10},
            {"front_left": 5},
            [],
        )
        assert not is_diffuse
        assert penalty == 1.0

    def test_uniform_multi_sensor_is_diffuse(self) -> None:
        locs = {"front_left", "front_right"}
        possible = {"front_left": 10, "front_right": 10}
        matched = {"front_left": 5, "front_right": 5}
        points = [
            {"location": "front_left", "amp": 0.03},
            {"location": "front_right", "amp": 0.03},
        ]
        is_diffuse, penalty = _detect_diffuse_excitation(locs, possible, matched, points)
        assert is_diffuse
        assert penalty < 1.0


class TestComputeOrderConfidence:
    """Test _compute_order_confidence clamping and modifiers."""

    def test_confidence_clamped_to_bounds(self) -> None:
        # Maximum possible inputs
        conf = _compute_order_confidence(
            effective_match_rate=1.0,
            error_score=1.0,
            corr_val=1.0,
            snr_score=1.0,
            absolute_strength_db=40.0,
            localization_confidence=1.0,
            weak_spatial_separation=False,
            dominance_ratio=2.0,
            constant_speed=False,
            steady_speed=False,
            matched=100,
            corroborating_locations=3,
            phases_with_evidence=3,
            is_diffuse_excitation=False,
            diffuse_penalty=1.0,
            n_connected_locations=3,
        )
        assert 0.08 <= conf <= 0.97

    def test_confidence_minimum_inputs(self) -> None:
        conf = _compute_order_confidence(
            effective_match_rate=0.0,
            error_score=0.0,
            corr_val=0.0,
            snr_score=0.0,
            absolute_strength_db=0.0,
            localization_confidence=0.0,
            weak_spatial_separation=True,
            dominance_ratio=1.0,
            constant_speed=True,
            steady_speed=True,
            matched=1,
            corroborating_locations=0,
            phases_with_evidence=0,
            is_diffuse_excitation=True,
            diffuse_penalty=0.65,
            n_connected_locations=1,
        )
        assert conf == 0.08  # floor


class TestSuppressEngineAliases:
    """Test _suppress_engine_aliases filtering."""

    def test_empty_findings(self) -> None:
        assert _suppress_engine_aliases([]) == []

    def test_engine_suppressed_when_wheel_stronger(self) -> None:
        input_findings = [
            (0.5, {"suspected_source": "wheel/tire", "confidence": 0.60}),
            (0.4, {"suspected_source": "engine", "confidence": 0.50}),
        ]
        result = _suppress_engine_aliases(input_findings)
        engine_results = [f for f in result if f["suspected_source"] == "engine"]
        if engine_results:
            assert engine_results[0]["confidence"] < 0.50

    def test_engine_suppression_normalizes_source_tokens(self) -> None:
        input_findings = [
            (0.5, {"suspected_source": " Wheel/Tire ", "confidence": 0.60}),
            (0.4, {"suspected_source": " ENGINE ", "confidence": 0.50}),
        ]
        result = _suppress_engine_aliases(input_findings)
        engine_results = [
            f for f in result if str(f["suspected_source"]).strip().lower() == "engine"
        ]
        if engine_results:
            assert engine_results[0]["confidence"] < 0.50


# -- intensity tests ----------------------------------------------------------


class TestSpeedBreakdown:
    """Test _speed_breakdown."""

    def test_empty_samples(self) -> None:
        assert _speed_breakdown([]) == []

    def test_single_speed_bin(self) -> None:
        samples = [
            {"speed_kmh": 65.0, "vibration_strength_db": 20.0},
            {"speed_kmh": 68.0, "vibration_strength_db": 22.0},
        ]
        rows = _speed_breakdown(samples)
        assert len(rows) == 1
        assert rows[0]["count"] == 2


class TestPhaseSpeedBreakdown:
    """Test _phase_speed_breakdown."""

    def test_single_phase(self) -> None:
        samples = [
            {"speed_kmh": 60.0, "vibration_strength_db": 18.0},
            {"speed_kmh": 65.0, "vibration_strength_db": 20.0},
        ]
        phases = [DrivingPhase.CRUISE, DrivingPhase.CRUISE]
        rows = _phase_speed_breakdown(samples, phases)
        cruise_rows = [r for r in rows if r["phase"] == "cruise"]
        assert len(cruise_rows) == 1
        assert cruise_rows[0]["count"] == 2


class TestSensorIntensityByLocation:
    """Test _sensor_intensity_by_location."""

    def test_empty_samples(self) -> None:
        assert _sensor_intensity_by_location([]) == []

    def test_single_location(self) -> None:
        samples = [
            {"location": "front_left", "vibration_strength_db": 20.0},
            {"location": "front_left", "vibration_strength_db": 22.0},
        ]
        rows = _sensor_intensity_by_location(samples)
        assert len(rows) == 1
        assert rows[0]["location"] == "front_left"
        assert rows[0]["sample_count"] == 2
