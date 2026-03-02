"""Tests for the findings subpackage structure and individual submodule contracts.

Validates that the refactoring from monolithic findings.py to the findings/
subpackage preserves all public APIs and that each submodule is independently
importable and testable.
"""

from __future__ import annotations

# ── Subpackage structure tests ──────────────────────────────────────────


class TestFindingsSubpackageStructure:
    """Verify the subpackage re-exports all expected symbols."""

    def test_all_public_symbols_accessible_from_package(self) -> None:
        """Every symbol previously available from findings.py must be accessible."""
        from vibesensor.analysis import findings

        expected = [
            "_build_findings",
            "_build_order_findings",
            "_build_persistent_peak_findings",
            "_classify_peak_type",
            "_compute_effective_match_rate",
            "_compute_order_confidence",
            "_detect_diffuse_excitation",
            "_phase_speed_breakdown",
            "_phase_to_str",
            "_reference_missing_finding",
            "_sensor_intensity_by_location",
            "_speed_bin_label",
            "_speed_breakdown",
            "_speed_profile_from_points",
            "_suppress_engine_aliases",
            "_weighted_percentile",
            "BASELINE_NOISE_SNR_THRESHOLD",
            "PERSISTENT_PEAK_MAX_FINDINGS",
            "PERSISTENT_PEAK_MIN_PRESENCE",
            "TRANSIENT_BURSTINESS_THRESHOLD",
        ]
        for name in expected:
            assert hasattr(findings, name), f"findings package missing re-export: {name}"

    def test_submodules_importable_independently(self) -> None:
        """Each submodule must be directly importable with expected symbols."""
        from vibesensor.analysis.findings import (  # noqa: F401
            _constants,
            builder,
            intensity,
            order_findings,
            persistent_findings,
            reference_checks,
            speed_profile,
        )

        # Verify key symbols exist in each submodule
        assert hasattr(builder, "_build_findings")
        assert hasattr(intensity, "_sensor_intensity_by_location")
        assert hasattr(order_findings, "_order_label")
        assert hasattr(speed_profile, "_speed_profile_from_points")
        assert hasattr(reference_checks, "_reference_missing_finding")
        assert hasattr(persistent_findings, "_build_persistent_peak_findings")

    def test_backward_compat_imports_via_analysis_findings(self) -> None:
        """Imports that worked with the old monolithic file must still work."""
        from vibesensor.analysis.findings import (
            _build_findings,
            _classify_peak_type,
            _compute_effective_match_rate,
            _sensor_intensity_by_location,
            _speed_breakdown,
            _weighted_percentile,
        )

        # Verify they are callable
        assert callable(_build_findings)
        assert callable(_classify_peak_type)
        assert callable(_compute_effective_match_rate)
        assert callable(_sensor_intensity_by_location)
        assert callable(_speed_breakdown)
        assert callable(_weighted_percentile)


# ── speed_profile tests ─────────────────────────────────────────────────


class TestPhaseToStr:
    """Test _phase_to_str helper."""

    def test_none_returns_none(self) -> None:
        from vibesensor.analysis.findings.speed_profile import _phase_to_str

        assert _phase_to_str(None) is None

    def test_enum_value(self) -> None:
        from vibesensor.analysis.findings.speed_profile import _phase_to_str
        from vibesensor.analysis.phase_segmentation import DrivingPhase

        assert _phase_to_str(DrivingPhase.CRUISE) == "cruise"

    def test_string_passthrough(self) -> None:
        from vibesensor.analysis.findings.speed_profile import _phase_to_str

        assert _phase_to_str("acceleration") == "acceleration"


class TestSpeedProfileFromPoints:
    """Test _speed_profile_from_points."""

    def test_empty_returns_none_tuple(self) -> None:
        from vibesensor.analysis.findings.speed_profile import _speed_profile_from_points

        result = _speed_profile_from_points([])
        assert result == (None, None, None)

    def test_single_point(self) -> None:
        from vibesensor.analysis.findings.speed_profile import _speed_profile_from_points

        peak, window, band = _speed_profile_from_points([(60.0, 0.05)])
        assert peak == 60.0

    def test_multiple_points_peak_is_highest_amplitude(self) -> None:
        from vibesensor.analysis.findings.speed_profile import _speed_profile_from_points

        points = [(50.0, 0.01), (70.0, 0.05), (90.0, 0.02)]
        peak, window, band = _speed_profile_from_points(points)
        assert peak == 70.0

    def test_negative_speed_filtered(self) -> None:
        from vibesensor.analysis.findings.speed_profile import _speed_profile_from_points

        points = [(-10.0, 0.05), (0.0, 0.03), (60.0, 0.02)]
        peak, _, _ = _speed_profile_from_points(points)
        assert peak == 60.0


# ── reference_checks tests ──────────────────────────────────────────────


class TestReferenceMissingFinding:
    """Test _reference_missing_finding builder."""

    def test_basic_structure(self) -> None:
        from vibesensor.analysis.findings.reference_checks import _reference_missing_finding

        finding = _reference_missing_finding(
            finding_id="REF_SPEED",
            suspected_source="unknown",
            evidence_summary="Speed missing",
            quick_checks=["Check GPS", "Re-run"],
        )
        assert finding["finding_id"] == "REF_SPEED"
        assert finding["finding_type"] == "reference"
        assert finding["suspected_source"] == "unknown"
        assert finding["confidence_0_to_1"] is None
        assert len(finding["quick_checks"]) <= 3

    def test_quick_checks_truncated_to_3(self) -> None:
        from vibesensor.analysis.findings.reference_checks import _reference_missing_finding

        finding = _reference_missing_finding(
            finding_id="REF_TEST",
            suspected_source="test",
            evidence_summary="Test",
            quick_checks=["a", "b", "c", "d", "e"],
        )
        assert len(finding["quick_checks"]) == 3


# ── _constants tests ────────────────────────────────────────────────────


class TestSharedConstants:
    """Verify shared constants have expected values."""

    def test_negligible_strength_max_db(self) -> None:
        from vibesensor.analysis.findings._constants import _NEGLIGIBLE_STRENGTH_MAX_DB

        assert isinstance(_NEGLIGIBLE_STRENGTH_MAX_DB, float)
        assert _NEGLIGIBLE_STRENGTH_MAX_DB > 0

    def test_confidence_bounds(self) -> None:
        from vibesensor.analysis.findings._constants import _CONFIDENCE_CEILING, _CONFIDENCE_FLOOR

        assert _CONFIDENCE_FLOOR < _CONFIDENCE_CEILING
        assert _CONFIDENCE_FLOOR >= 0.0
        assert _CONFIDENCE_CEILING <= 1.0


# ── classify_peak_type tests ────────────────────────────────────────────


class TestClassifyPeakType:
    """Test _classify_peak_type classification logic."""

    def test_low_snr_is_baseline_noise(self) -> None:
        from vibesensor.analysis.findings.persistent_findings import _classify_peak_type

        assert _classify_peak_type(0.5, 2.0, snr=1.0) == "baseline_noise"

    def test_low_presence_is_transient(self) -> None:
        from vibesensor.analysis.findings.persistent_findings import _classify_peak_type

        assert _classify_peak_type(0.05, 2.0, snr=5.0) == "transient"

    def test_high_burstiness_is_transient(self) -> None:
        from vibesensor.analysis.findings.persistent_findings import _classify_peak_type

        assert _classify_peak_type(0.30, 6.0, snr=5.0) == "transient"

    def test_high_presence_low_burst_is_patterned(self) -> None:
        from vibesensor.analysis.findings.persistent_findings import _classify_peak_type

        assert _classify_peak_type(0.50, 2.0, snr=5.0) == "patterned"

    def test_moderate_presence_is_persistent(self) -> None:
        from vibesensor.analysis.findings.persistent_findings import _classify_peak_type

        assert _classify_peak_type(0.25, 3.5, snr=5.0) == "persistent"

    def test_high_spatial_uniformity_is_baseline_noise(self) -> None:
        from vibesensor.analysis.findings.persistent_findings import _classify_peak_type

        assert _classify_peak_type(0.70, 1.5, snr=5.0, spatial_uniformity=0.90) == "baseline_noise"


# ── order_findings tests ────────────────────────────────────────────────


class TestComputeEffectiveMatchRate:
    """Test _compute_effective_match_rate rescue logic."""

    def test_above_threshold_returns_original(self) -> None:
        from vibesensor.analysis.findings.order_findings import _compute_effective_match_rate

        rate, band, dominant = _compute_effective_match_rate(0.50, 0.25, {}, {}, {}, {})
        assert rate == 0.50
        assert band is None
        assert dominant is False

    def test_focused_speed_band_rescue(self) -> None:
        from vibesensor.analysis.findings.order_findings import _compute_effective_match_rate

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
        from vibesensor.analysis.findings.order_findings import _detect_diffuse_excitation

        is_diffuse, penalty = _detect_diffuse_excitation(
            {"front_left"}, {"front_left": 10}, {"front_left": 5}, []
        )
        assert not is_diffuse
        assert penalty == 1.0

    def test_uniform_multi_sensor_is_diffuse(self) -> None:
        from vibesensor.analysis.findings.order_findings import _detect_diffuse_excitation

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
        from vibesensor.analysis.findings.order_findings import _compute_order_confidence

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
        from vibesensor.analysis.findings.order_findings import _compute_order_confidence

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
        from vibesensor.analysis.findings.order_findings import _suppress_engine_aliases

        assert _suppress_engine_aliases([]) == []

    def test_engine_suppressed_when_wheel_stronger(self) -> None:
        from vibesensor.analysis.findings.order_findings import _suppress_engine_aliases

        findings = [
            (0.5, {"suspected_source": "wheel/tire", "confidence_0_to_1": 0.60}),
            (0.4, {"suspected_source": "engine", "confidence_0_to_1": 0.50}),
        ]
        result = _suppress_engine_aliases(findings)
        engine_results = [f for f in result if f["suspected_source"] == "engine"]
        if engine_results:
            assert engine_results[0]["confidence_0_to_1"] < 0.50


# ── intensity tests ─────────────────────────────────────────────────────


class TestSpeedBreakdown:
    """Test _speed_breakdown."""

    def test_empty_samples(self) -> None:
        from vibesensor.analysis.findings.intensity import _speed_breakdown

        assert _speed_breakdown([]) == []

    def test_single_speed_bin(self) -> None:
        from vibesensor.analysis.findings.intensity import _speed_breakdown

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
        from vibesensor.analysis.findings.intensity import _phase_speed_breakdown
        from vibesensor.analysis.phase_segmentation import DrivingPhase

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
        from vibesensor.analysis.findings.intensity import _sensor_intensity_by_location

        assert _sensor_intensity_by_location([]) == []

    def test_single_location(self) -> None:
        from vibesensor.analysis.findings.intensity import _sensor_intensity_by_location

        samples = [
            {"location": "front_left", "vibration_strength_db": 20.0},
            {"location": "front_left", "vibration_strength_db": 22.0},
        ]
        rows = _sensor_intensity_by_location(samples)
        assert len(rows) == 1
        assert rows[0]["location"] == "front_left"
        assert rows[0]["sample_count"] == 2
