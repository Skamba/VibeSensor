"""Tests for the findings modules structure and individual module contracts.

Validates that the findings_* modules are independently importable and
testable, and that each module exposes expected symbols.
"""

from __future__ import annotations

import pytest
from test_support.findings import make_finding, make_finding_payload

import vibesensor.use_cases.diagnostics.findings as findings_module
from vibesensor.domain import OrderMatchObservation
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.boundaries.summary_fields.finding import (
    finding_from_payload,
    finding_payload_from_domain,
)
from vibesensor.shared.constants.analysis import (
    CONFIDENCE_CEILING,
    CONFIDENCE_FLOOR,
    NEGLIGIBLE_STRENGTH_MAX_DB,
)
from vibesensor.use_cases.diagnostics._reference_findings import _reference_missing_finding
from vibesensor.use_cases.diagnostics.orders.heuristics import (
    detect_diffuse_excitation as _detect_diffuse_excitation,
)
from vibesensor.use_cases.diagnostics.orders.heuristics import (
    suppress_engine_aliases as _suppress_engine_aliases,
)
from vibesensor.use_cases.diagnostics.orders.match_rate import _compute_effective_match_rate
from vibesensor.use_cases.diagnostics.orders.settings import ORDER_CONFIDENCE_SETTINGS
from vibesensor.use_cases.diagnostics.orders.statistics import (
    compute_order_confidence as _compute_order_confidence,
)
from vibesensor.use_cases.diagnostics.phase_segmentation import DrivingPhase
from vibesensor.use_cases.diagnostics.signal_aggregation import (
    _phase_speed_breakdown,
    _sensor_intensity_by_location,
    _speed_breakdown,
)
from vibesensor.use_cases.diagnostics.speed_profile_helpers import (
    _phase_to_str,
    _speed_profile_from_points,
)

# -- Subpackage structure tests -----------------------------------------------


def test_findings_module_public_api_surface_stays_explicit() -> None:
    assert findings_module.__all__ == [
        "PeakFindingAnalyzer",
        "collect_order_frequencies",
        "finalize_findings",
        "prepare_analysis_samples",
    ]
    for exported_name in findings_module.__all__:
        assert hasattr(findings_module, exported_name)


def test_finding_payload_round_trip_preserves_consumer_fields() -> None:
    domain = finding_from_payload(
        make_finding_payload(
            finding_id="F_ROUNDTRIP",
            confidence=0.82,
            strongest_location="front-left wheel",
            confidence_label_key="CONFIDENCE_HIGH",
            confidence_tone="success",
            confidence_pct="82%",
            confidence_reason="Strong order evidence",
            phase_evidence={"cruise_fraction": 0.75, "phases_detected": ["cruise", "acceleration"]},
            matched_points=[
                {
                    "t_s": 1.25,
                    "speed_kmh": 72.0,
                    "predicted_hz": 48.0,
                    "matched_hz": 48.4,
                    "rel_error": 0.008,
                    "amp": 0.03,
                    "location": "front-left wheel",
                    "phase": "cruise",
                }
            ],
        )
    )

    payload = finding_payload_from_domain(domain)
    round_trip = finding_from_payload(payload)

    assert payload["finding_id"] == "F_ROUNDTRIP"
    assert payload["confidence_label_key"] == "CONFIDENCE_HIGH"
    assert payload["confidence_tone"] == "success"
    assert payload["confidence_pct"] == "82%"
    assert payload["phase_evidence"] == {
        "cruise_fraction": 0.75,
        "phases_detected": ["cruise", "acceleration"],
    }
    assert payload["matched_points"][0]["location"] == "front-left wheel"
    assert round_trip.confidence_assessment is not None
    assert round_trip.confidence_assessment.reason == "Strong order evidence"
    assert round_trip.phases_detected == ("cruise", "acceleration")
    assert round_trip.matched_points[0].location == "front-left wheel"
    assert round_trip.matched_points[0].phase == "cruise"


# -- speed_profile tests ------------------------------------------------------


class TestPhaseToStr:
    """Test _phase_to_str helper."""

    @pytest.mark.parametrize(
        ("input_val", "expected"),
        [
            pytest.param(None, None, id="none_returns_none"),
            pytest.param(DrivingPhase.CRUISE, "cruise", id="enum_value"),
            pytest.param("acceleration", "acceleration", id="string_passthrough"),
            pytest.param(7, "7", id="unsupported_scalar_stringified"),
        ],
    )
    def test_phase_to_str(self, input_val: object, expected: str | None) -> None:
        assert _phase_to_str(input_val) == expected

    def test_phase_to_str_uses_enum_like_value_for_future_phase_objects(self) -> None:
        class FuturePhase:
            value = "future_phase"

        assert _phase_to_str(FuturePhase()) == "future_phase"


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
        )
        assert finding.finding_id == "REF_SPEED"
        assert finding.is_reference is True
        assert str(finding.suspected_source) == "unknown"
        assert finding.confidence is None


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
            OrderMatchObservation(
                predicted_hz=50.0,
                matched_hz=50.5,
                rel_error=0.01,
                amp=0.03,
                location="front_left",
            ),
            OrderMatchObservation(
                predicted_hz=50.0,
                matched_hz=50.5,
                rel_error=0.01,
                amp=0.03,
                location="front_right",
            ),
        ]
        is_diffuse, penalty = _detect_diffuse_excitation(locs, possible, matched, points)
        assert is_diffuse
        assert penalty < 1.0


class TestComputeOrderConfidence:
    """Test _compute_order_confidence clamping and modifiers."""

    _BASE_INPUTS = {
        "effective_match_rate": 0.70,
        "error_score": 0.80,
        "corr_val": 0.60,
        "snr_score": 0.75,
        "absolute_strength_db": 20.0,
        "localization_confidence": 0.60,
        "weak_spatial_separation": False,
        "dominance_ratio": 1.2,
        "constant_speed": False,
        "steady_speed": False,
        "matched": 20,
        "corroborating_locations": 2,
        "phases_with_evidence": 2,
        "is_diffuse_excitation": False,
        "diffuse_penalty": 1.0,
        "n_connected_locations": 3,
    }

    def test_confidence_increases_with_stronger_match_evidence(self) -> None:
        weaker = _compute_order_confidence(
            **{**self._BASE_INPUTS, "effective_match_rate": 0.35},
        )
        stronger = _compute_order_confidence(
            **{**self._BASE_INPUTS, "effective_match_rate": 0.85},
        )

        assert stronger > weaker
        assert CONFIDENCE_FLOOR <= weaker <= CONFIDENCE_CEILING
        assert CONFIDENCE_FLOOR <= stronger <= CONFIDENCE_CEILING

    def test_negligible_strength_cap_reduces_same_signal_to_cap(self) -> None:
        capped = _compute_order_confidence(
            **{**self._BASE_INPUTS, "absolute_strength_db": NEGLIGIBLE_STRENGTH_MAX_DB - 1.0},
        )
        uncapped = _compute_order_confidence(
            **{**self._BASE_INPUTS, "absolute_strength_db": NEGLIGIBLE_STRENGTH_MAX_DB + 5.0},
        )

        assert capped <= ORDER_CONFIDENCE_SETTINGS.negligible_strength_confidence_cap
        assert uncapped > capped

    def test_constant_and_steady_speed_penalties_apply_in_order(self) -> None:
        baseline = _compute_order_confidence(
            **self._BASE_INPUTS,
        )
        steady = _compute_order_confidence(
            **{**self._BASE_INPUTS, "steady_speed": True},
        )
        constant = _compute_order_confidence(
            **{**self._BASE_INPUTS, "constant_speed": True},
        )

        assert baseline > steady > constant

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
            (0.5, make_finding(suspected_source="wheel/tire", confidence=0.60, ranking_score=0.5)),
            (0.4, make_finding(suspected_source="engine", confidence=0.50, ranking_score=0.4)),
        ]
        result = _suppress_engine_aliases(input_findings)
        engine_results = [f for f in result if str(f.suspected_source) == "engine"]
        if engine_results:
            assert engine_results[0].effective_confidence < 0.50

    def test_engine_suppression_normalizes_source_tokens(self) -> None:
        input_findings = [
            (
                0.5,
                make_finding(
                    suspected_source=" Wheel/Tire ",
                    confidence=0.60,
                    ranking_score=0.5,
                ),
            ),
            (0.4, make_finding(suspected_source=" ENGINE ", confidence=0.50, ranking_score=0.4)),
        ]
        result = _suppress_engine_aliases(input_findings)
        engine_results = [f for f in result if str(f.suspected_source).strip().lower() == "engine"]
        if engine_results:
            assert engine_results[0].effective_confidence < 0.50


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
        rows = _speed_breakdown(sensor_frames_from_mappings(samples))
        assert len(rows) == 1
        assert rows[0].count == 2


class TestPhaseSpeedBreakdown:
    """Test _phase_speed_breakdown."""

    def test_single_phase(self) -> None:
        samples = [
            {"speed_kmh": 60.0, "vibration_strength_db": 18.0},
            {"speed_kmh": 65.0, "vibration_strength_db": 20.0},
        ]
        phases = [DrivingPhase.CRUISE, DrivingPhase.CRUISE]
        rows = _phase_speed_breakdown(sensor_frames_from_mappings(samples), phases)
        cruise_rows = [r for r in rows if r.phase == "cruise"]
        assert len(cruise_rows) == 1
        assert cruise_rows[0].count == 2


class TestSensorIntensityByLocation:
    """Test _sensor_intensity_by_location."""

    def test_empty_samples(self) -> None:
        assert _sensor_intensity_by_location([]) == []

    def test_single_location(self) -> None:
        samples = [
            {"location": "front_left", "vibration_strength_db": 20.0},
            {"location": "front_left", "vibration_strength_db": 22.0},
        ]
        rows = _sensor_intensity_by_location(sensor_frames_from_mappings(samples))
        assert len(rows) == 1
        assert rows[0].location == "front_left"
        assert rows[0].sample_count == 2
