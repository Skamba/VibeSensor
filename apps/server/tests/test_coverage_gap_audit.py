"""Coverage-gap audit: top 10 untested critical code paths.

This file addresses the top 10 coverage gaps identified by systematic
cross-referencing of public/private functions in:
  - apps/server/vibesensor/analysis/findings.py
  - apps/server/vibesensor/analysis/summary.py
  - apps/server/vibesensor/metrics_log.py
  - apps/server/vibesensor/processing.py
against all test files in apps/server/tests/.

Each class documents the gap, its severity, and provides working tests.
"""

from __future__ import annotations

import math
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Finding 1: _compute_order_confidence  (findings.py:504)
# SEVERITY: CRITICAL
# WHY: Core confidence-scoring algorithm with 18+ tuning parameters, multiple
#      conditional penalties/boosts, and clamped 0.08–0.97 output.  Every PDF
#      report hinges on its output.  Zero direct unit tests.
# ---------------------------------------------------------------------------


class TestComputeOrderConfidence:
    """Direct unit tests for _compute_order_confidence."""

    @staticmethod
    def _call(**overrides: Any) -> float:
        from vibesensor.analysis.findings import _compute_order_confidence

        defaults: dict[str, Any] = {
            "effective_match_rate": 0.60,
            "error_score": 0.80,
            "corr_val": 0.50,
            "snr_score": 0.60,
            "absolute_strength_db": 20.0,
            "localization_confidence": 0.70,
            "weak_spatial_separation": False,
            "dominance_ratio": 2.0,
            "constant_speed": False,
            "steady_speed": False,
            "matched": 30,
            "corroborating_locations": 2,
            "phases_with_evidence": 2,
            "is_diffuse_excitation": False,
            "diffuse_penalty": 1.0,
            "n_connected_locations": 3,
            "no_wheel_sensors": False,
            "path_compliance": 1.0,
        }
        defaults.update(overrides)
        return _compute_order_confidence(**defaults)

    def test_baseline_returns_moderate_confidence(self) -> None:
        conf = self._call()
        assert 0.30 < conf < 0.90, f"Baseline defaults produced unexpected {conf}"

    def test_output_clamped_low(self) -> None:
        """All-zero inputs should clamp to the 0.08 floor."""
        conf = self._call(
            effective_match_rate=0.0,
            error_score=0.0,
            corr_val=0.0,
            snr_score=0.0,
            absolute_strength_db=0.0,
            localization_confidence=0.0,
            matched=0,
            corroborating_locations=0,
            phases_with_evidence=0,
        )
        assert conf == pytest.approx(0.08, abs=0.001)

    def test_output_clamped_high(self) -> None:
        """Perfect inputs should clamp to the 0.97 ceiling."""
        conf = self._call(
            effective_match_rate=1.0,
            error_score=1.0,
            corr_val=1.0,
            snr_score=1.0,
            absolute_strength_db=40.0,
            localization_confidence=1.0,
            matched=100,
            corroborating_locations=4,
            phases_with_evidence=4,
        )
        assert conf == pytest.approx(0.97, abs=0.001)

    def test_negligible_strength_caps_at_045(self) -> None:
        """absolute_strength_db below negligible threshold should cap confidence."""
        conf = self._call(absolute_strength_db=5.0)
        assert conf <= 0.45 + 0.001

    def test_weak_spatial_penalty_applied(self) -> None:
        normal = self._call(weak_spatial_separation=False)
        weak = self._call(weak_spatial_separation=True)
        assert weak < normal, "weak_spatial_separation should reduce confidence"

    def test_constant_speed_penalty(self) -> None:
        normal = self._call(constant_speed=False)
        const = self._call(constant_speed=True)
        assert const < normal, "constant_speed should reduce confidence"

    def test_diffuse_excitation_penalty(self) -> None:
        normal = self._call(is_diffuse_excitation=False)
        diffuse = self._call(is_diffuse_excitation=True, diffuse_penalty=0.75)
        assert diffuse < normal, "diffuse_excitation should reduce confidence"

    def test_single_sensor_scale(self) -> None:
        multi = self._call(n_connected_locations=3)
        single = self._call(n_connected_locations=1)
        assert single < multi, "single sensor should scale down"

    def test_path_compliance_shifts_weights(self) -> None:
        """Higher path_compliance should shift weight from corr to match."""
        stiff = self._call(path_compliance=1.0, corr_val=0.0, effective_match_rate=0.80)
        compliant = self._call(path_compliance=1.5, corr_val=0.0, effective_match_rate=0.80)
        assert compliant >= stiff - 0.02

    def test_corroborating_locations_boost(self) -> None:
        base = self._call(corroborating_locations=1)
        boosted = self._call(corroborating_locations=3)
        assert boosted > base, "3+ corroborating locations should boost confidence"

    def test_light_strength_penalty(self) -> None:
        """absolute_strength_db in the 'light' band (8–16 dB) should apply 0.80 penalty."""
        strong = self._call(absolute_strength_db=25.0)
        light = self._call(absolute_strength_db=12.0)
        assert light < strong, "Light-strength band should reduce confidence"


# ---------------------------------------------------------------------------
# Finding 2: _detect_diffuse_excitation  (findings.py:454)
# SEVERITY: HIGH
# WHY: Determines whether vibration is localized or diffuse across sensors.
#      Misclassification silently penalizes genuine fault confidence by up to
#      35%.  Zero direct unit tests.
# ---------------------------------------------------------------------------


class TestDetectDiffuseExcitation:
    """Direct unit tests for _detect_diffuse_excitation."""

    def test_single_sensor_returns_not_diffuse(self) -> None:
        from vibesensor.analysis.findings import _detect_diffuse_excitation

        is_diff, penalty = _detect_diffuse_excitation(
            connected_locations={"front_left"},
            possible_by_location={"front_left": 20},
            matched_by_location={"front_left": 15},
            matched_points=[{"location": "front_left", "amp": 0.1}] * 15,
        )
        assert not is_diff
        assert penalty == 1.0

    def test_uniform_rates_uniform_amplitude_is_diffuse(self) -> None:
        from vibesensor.analysis.findings import _detect_diffuse_excitation

        locs = {"front_left", "front_right", "rear"}
        possible = {loc: 30 for loc in locs}
        matched = {loc: 20 for loc in locs}
        pts = [{"location": loc, "amp": 0.05} for loc in locs for _ in range(20)]
        is_diff, penalty = _detect_diffuse_excitation(locs, possible, matched, pts)
        assert is_diff, "Uniform rates + uniform amplitude should be diffuse"
        assert penalty < 1.0

    def test_dominant_amplitude_is_not_diffuse(self) -> None:
        from vibesensor.analysis.findings import _detect_diffuse_excitation

        locs = {"front_left", "rear"}
        possible = {"front_left": 20, "rear": 20}
        matched = {"front_left": 15, "rear": 14}
        pts = [{"location": "front_left", "amp": 0.30}] * 15 + [
            {"location": "rear", "amp": 0.05}
        ] * 14
        is_diff, penalty = _detect_diffuse_excitation(locs, possible, matched, pts)
        assert not is_diff, "Strong amplitude dominance should NOT be diffuse"

    def test_insufficient_samples_per_location(self) -> None:
        from vibesensor.analysis.findings import _detect_diffuse_excitation

        locs = {"front_left", "rear"}
        possible = {"front_left": 2, "rear": 2}
        matched = {"front_left": 2, "rear": 2}
        pts = [{"location": "front_left", "amp": 0.05}] * 2
        is_diff, penalty = _detect_diffuse_excitation(locs, possible, matched, pts)
        assert not is_diff, "Too few samples should not trigger diffuse"

    def test_empty_matched_points(self) -> None:
        from vibesensor.analysis.findings import _detect_diffuse_excitation

        locs = {"a", "b"}
        is_diff, penalty = _detect_diffuse_excitation(
            locs, {"a": 20, "b": 20}, {"a": 15, "b": 15}, []
        )
        # With no amplitude data, amplitude check defaults to uniform
        assert isinstance(is_diff, bool)
        assert penalty <= 1.0


# ---------------------------------------------------------------------------
# Finding 3: _suppress_engine_aliases  (findings.py:602)
# SEVERITY: HIGH
# WHY: Silently reduces engine-finding confidence when a stronger wheel
#      finding exists.  Could mask real engine faults or over-suppress.
#      Zero direct unit tests.
# ---------------------------------------------------------------------------


class TestSuppressEngineAliases:
    """Direct unit tests for _suppress_engine_aliases."""

    @staticmethod
    def _make_finding(source: str, conf: float, rank: float = 1.0) -> dict[str, object]:
        return {
            "suspected_source": source,
            "confidence_0_to_1": conf,
            "finding_id": "F_ORDER",
        }

    def test_no_wheel_no_suppression(self) -> None:
        from vibesensor.analysis.findings import _suppress_engine_aliases

        findings = [
            (1.0, self._make_finding("engine", 0.60)),
            (0.5, self._make_finding("driveshaft", 0.40)),
        ]
        result = _suppress_engine_aliases(findings)
        assert any(f.get("suspected_source") == "engine" for f in result), (
            "Engine finding should survive when no wheel finding exists"
        )

    def test_engine_suppressed_by_stronger_wheel(self) -> None:
        from vibesensor.analysis.findings import _suppress_engine_aliases

        findings = [
            (1.0, self._make_finding("wheel/tire", 0.70)),
            (0.8, self._make_finding("engine", 0.65)),
        ]
        result = _suppress_engine_aliases(findings)
        engine_findings = [f for f in result if f.get("suspected_source") == "engine"]
        if engine_findings:
            assert float(engine_findings[0]["confidence_0_to_1"]) < 0.65

    def test_strong_engine_not_suppressed(self) -> None:
        from vibesensor.analysis.findings import _suppress_engine_aliases

        findings = [
            (0.3, self._make_finding("wheel/tire", 0.30)),
            (1.0, self._make_finding("engine", 0.90)),
        ]
        result = _suppress_engine_aliases(findings)
        engine_findings = [f for f in result if f.get("suspected_source") == "engine"]
        assert engine_findings, "Strong engine should survive weak wheel"

    def test_empty_input(self) -> None:
        from vibesensor.analysis.findings import _suppress_engine_aliases

        assert _suppress_engine_aliases([]) == []

    def test_output_capped_at_5(self) -> None:
        from vibesensor.analysis.findings import _suppress_engine_aliases

        findings = [(i, self._make_finding("wheel/tire", 0.50 + i * 0.05)) for i in range(7)]
        result = _suppress_engine_aliases(findings)
        assert len(result) <= 5


# ---------------------------------------------------------------------------
# Finding 4: _build_run_suitability_checks  (summary.py:600)
# SEVERITY: HIGH
# WHY: Constructs the data-quality checklist visible in every PDF report.
#      Logic for speed variation, sensor coverage, reference completeness,
#      saturation, and frame integrity checks has zero direct tests.
# ---------------------------------------------------------------------------


class TestBuildRunSuitabilityChecks:
    """Direct unit tests for _build_run_suitability_checks."""

    def test_all_pass(self) -> None:
        from vibesensor.analysis.summary import _build_run_suitability_checks

        checks = _build_run_suitability_checks(
            language="en",
            steady_speed=False,
            speed_sufficient=True,
            sensor_ids={"s1", "s2", "s3"},
            reference_complete=True,
            sat_count=0,
            samples=[],
        )
        assert all(c["state"] == "pass" for c in checks), (
            f"All checks should pass: {[c['check_key'] for c in checks if c['state'] != 'pass']}"
        )

    def test_speed_variation_warn_when_steady(self) -> None:
        from vibesensor.analysis.summary import _build_run_suitability_checks

        checks = _build_run_suitability_checks(
            language="en",
            steady_speed=True,
            speed_sufficient=True,
            sensor_ids={"s1", "s2", "s3"},
            reference_complete=True,
            sat_count=0,
            samples=[],
        )
        speed_check = next(
            c for c in checks if c["check_key"] == "SUITABILITY_CHECK_SPEED_VARIATION"
        )
        assert speed_check["state"] == "warn"

    def test_sensor_coverage_warn_below_3(self) -> None:
        from vibesensor.analysis.summary import _build_run_suitability_checks

        checks = _build_run_suitability_checks(
            language="en",
            steady_speed=False,
            speed_sufficient=True,
            sensor_ids={"s1"},
            reference_complete=True,
            sat_count=0,
            samples=[],
        )
        sensor_check = next(
            c for c in checks if c["check_key"] == "SUITABILITY_CHECK_SENSOR_COVERAGE"
        )
        assert sensor_check["state"] == "warn"

    def test_saturation_warn(self) -> None:
        from vibesensor.analysis.summary import _build_run_suitability_checks

        checks = _build_run_suitability_checks(
            language="en",
            steady_speed=False,
            speed_sufficient=True,
            sensor_ids={"s1", "s2", "s3"},
            reference_complete=True,
            sat_count=5,
            samples=[],
        )
        sat_check = next(
            c for c in checks if c["check_key"] == "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS"
        )
        assert sat_check["state"] == "warn"

    def test_frame_integrity_with_dropped_frames(self) -> None:
        from vibesensor.analysis.summary import _build_run_suitability_checks

        samples: list[dict[str, Any]] = [
            {"client_id": "c1", "frames_dropped_total": 0},
            {"client_id": "c1", "frames_dropped_total": 10},
        ]
        checks = _build_run_suitability_checks(
            language="en",
            steady_speed=False,
            speed_sufficient=True,
            sensor_ids={"s1", "s2", "s3"},
            reference_complete=True,
            sat_count=0,
            samples=samples,
        )
        frame_check = next(
            c for c in checks if c["check_key"] == "SUITABILITY_CHECK_FRAME_INTEGRITY"
        )
        assert frame_check["state"] == "warn"

    def test_reference_incomplete(self) -> None:
        from vibesensor.analysis.summary import _build_run_suitability_checks

        checks = _build_run_suitability_checks(
            language="en",
            steady_speed=False,
            speed_sufficient=True,
            sensor_ids={"s1", "s2", "s3"},
            reference_complete=False,
            sat_count=0,
            samples=[],
        )
        ref_check = next(
            c for c in checks if c["check_key"] == "SUITABILITY_CHECK_REFERENCE_COMPLETENESS"
        )
        assert ref_check["state"] == "warn"


# ---------------------------------------------------------------------------
# Finding 5: _build_phase_timeline  (summary.py:396)
# SEVERITY: MEDIUM-HIGH
# WHY: Constructs the per-phase timeline shown in UI and PDF.  Bug here
#      misrepresents which driving phases had fault evidence.  Zero tests.
# ---------------------------------------------------------------------------


class TestBuildPhaseTimeline:
    """Direct unit tests for _build_phase_timeline."""

    def test_empty_segments_returns_empty(self) -> None:
        from vibesensor.analysis.summary import _build_phase_timeline

        assert _build_phase_timeline([], [], "en") == []

    def test_basic_segment_output(self) -> None:
        from vibesensor.analysis.phase_segmentation import DrivingPhase
        from vibesensor.analysis.summary import _build_phase_timeline

        class FakeSeg:
            def __init__(self, phase: DrivingPhase, start: float, end: float) -> None:
                self.phase = phase
                self.start_t_s = start
                self.end_t_s = end
                self.speed_min_kmh = 40.0
                self.speed_max_kmh = 80.0

        segs = [
            FakeSeg(DrivingPhase.CRUISE, 0.0, 30.0),
            FakeSeg(DrivingPhase.ACCELERATION, 30.0, 45.0),
        ]
        findings: list[dict[str, object]] = [
            {
                "finding_id": "F001",
                "confidence_0_to_1": 0.60,
                "phase_evidence": {"phases_detected": ["cruise"]},
            }
        ]
        entries = _build_phase_timeline(segs, findings, "en")
        assert len(entries) == 2
        assert entries[0]["phase"] == "cruise"
        assert entries[0]["has_fault_evidence"] is True
        assert entries[1]["has_fault_evidence"] is False

    def test_ref_findings_ignored(self) -> None:
        """REF_ findings should not mark phases as having fault evidence."""
        from vibesensor.analysis.phase_segmentation import DrivingPhase
        from vibesensor.analysis.summary import _build_phase_timeline

        class FakeSeg:
            def __init__(self) -> None:
                self.phase = DrivingPhase.CRUISE
                self.start_t_s = 0.0
                self.end_t_s = 10.0
                self.speed_min_kmh = 50.0
                self.speed_max_kmh = 60.0

        findings: list[dict[str, object]] = [
            {
                "finding_id": "REF_SPEED",
                "confidence_0_to_1": 0.90,
                "phase_evidence": {"phases_detected": ["cruise"]},
            }
        ]
        entries = _build_phase_timeline([FakeSeg()], findings, "en")
        assert entries[0]["has_fault_evidence"] is False

    def test_low_confidence_finding_ignored(self) -> None:
        """Findings below ORDER_MIN_CONFIDENCE should not contribute."""
        from vibesensor.analysis.phase_segmentation import DrivingPhase
        from vibesensor.analysis.summary import _build_phase_timeline

        class FakeSeg:
            def __init__(self) -> None:
                self.phase = DrivingPhase.CRUISE
                self.start_t_s = 0.0
                self.end_t_s = 10.0
                self.speed_min_kmh = 50.0
                self.speed_max_kmh = 60.0

        findings: list[dict[str, object]] = [
            {
                "finding_id": "F001",
                "confidence_0_to_1": 0.01,  # below ORDER_MIN_CONFIDENCE
                "phase_evidence": {"phases_detected": ["cruise"]},
            }
        ]
        entries = _build_phase_timeline([FakeSeg()], findings, "en")
        assert entries[0]["has_fault_evidence"] is False


# ---------------------------------------------------------------------------
# Finding 6: _compute_accel_statistics  (summary.py:524)
# SEVERITY: MEDIUM-HIGH
# WHY: Computes saturation detection, per-axis mean/variance, and magnitude.
#      Saturation miscounting silently breaks the suitability checklist.
#      Zero direct tests.
# ---------------------------------------------------------------------------


class TestComputeAccelStatistics:
    """Direct unit tests for _compute_accel_statistics."""

    def test_empty_samples(self) -> None:
        from vibesensor.analysis.summary import _compute_accel_statistics

        result = _compute_accel_statistics([], "ADXL345")
        assert result["sat_count"] == 0
        assert result["accel_x_vals"] == []
        assert result["accel_mag_vals"] == []

    def test_basic_values(self) -> None:
        from vibesensor.analysis.summary import _compute_accel_statistics

        samples: list[dict[str, Any]] = [
            {
                "accel_x_g": 0.1,
                "accel_y_g": 0.2,
                "accel_z_g": 1.0,
                "vibration_strength_db": 12.0,
            }
        ]
        result = _compute_accel_statistics(samples, "ADXL345")
        assert len(result["accel_x_vals"]) == 1
        assert result["accel_x_vals"][0] == pytest.approx(0.1)
        assert len(result["accel_mag_vals"]) == 1
        expected_mag = math.sqrt(0.1**2 + 0.2**2 + 1.0**2)
        assert result["accel_mag_vals"][0] == pytest.approx(expected_mag, rel=1e-3)

    def test_saturation_detected_near_limit(self) -> None:
        from vibesensor.analysis.summary import _compute_accel_statistics

        # ADXL345 has ±16g limit; 98% threshold = 15.68g
        samples: list[dict[str, Any]] = [
            {"accel_x_g": 15.7, "accel_y_g": 0.0, "accel_z_g": 0.0},
        ]
        result = _compute_accel_statistics(samples, "ADXL345")
        assert result["sat_count"] >= 1, "Near-limit value should count as saturation"

    def test_missing_axes_handled(self) -> None:
        from vibesensor.analysis.summary import _compute_accel_statistics

        samples: list[dict[str, Any]] = [{"accel_x_g": 0.5}]
        result = _compute_accel_statistics(samples, "unknown")
        assert len(result["accel_x_vals"]) == 1
        assert result["accel_y_vals"] == []
        assert result["accel_mag_vals"] == []  # can't compute magnitude without all 3

    def test_unknown_sensor_no_saturation_check(self) -> None:
        """When sensor_limit is None, no saturation counting should occur."""
        from vibesensor.analysis.summary import _compute_accel_statistics

        samples: list[dict[str, Any]] = [
            {"accel_x_g": 999.0, "accel_y_g": 999.0, "accel_z_g": 999.0},
        ]
        result = _compute_accel_statistics(samples, "totally_unknown_sensor")
        # With unknown sensor, sensor_limit should be None → sat_count = 0
        if result["sensor_limit"] is None:
            assert result["sat_count"] == 0


# ---------------------------------------------------------------------------
# Finding 7: _phase_ranking_score  (summary.py:177)
# SEVERITY: MEDIUM
# WHY: Multiplier used inside select_top_causes to rank findings by phase
#      evidence.  Incorrect weighting silently re-orders top causes in
#      the report.  Not directly tested.
# ---------------------------------------------------------------------------


class TestPhaseRankingScore:
    """Direct unit tests for _phase_ranking_score."""

    def test_no_phase_evidence(self) -> None:
        from vibesensor.analysis.summary import _phase_ranking_score

        score = _phase_ranking_score({"confidence_0_to_1": 0.80})
        # No phase_evidence → cruise_fraction=0 → multiplier=0.85
        assert score == pytest.approx(0.80 * 0.85, rel=1e-3)

    def test_full_cruise_phase(self) -> None:
        from vibesensor.analysis.summary import _phase_ranking_score

        finding: dict[str, object] = {
            "confidence_0_to_1": 0.80,
            "phase_evidence": {"cruise_fraction": 1.0},
        }
        score = _phase_ranking_score(finding)
        assert score == pytest.approx(0.80 * 1.0, rel=1e-3)

    def test_half_cruise(self) -> None:
        from vibesensor.analysis.summary import _phase_ranking_score

        finding: dict[str, object] = {
            "confidence_0_to_1": 0.80,
            "phase_evidence": {"cruise_fraction": 0.50},
        }
        score = _phase_ranking_score(finding)
        expected = 0.80 * (0.85 + 0.15 * 0.50)
        assert score == pytest.approx(expected, rel=1e-3)

    def test_none_confidence(self) -> None:
        from vibesensor.analysis.summary import _phase_ranking_score

        score = _phase_ranking_score({"confidence_0_to_1": None})
        assert score == 0.0

    def test_missing_confidence_key(self) -> None:
        from vibesensor.analysis.summary import _phase_ranking_score

        score = _phase_ranking_score({})
        assert score == 0.0


# ---------------------------------------------------------------------------
# Finding 8: MetricsLogger._extract_strength_data  (metrics_log.py:429)
# SEVERITY: MEDIUM-HIGH
# WHY: Parses nested dicts from processor output to extract vibration_strength_db,
#      strength_bucket, top_peaks.  Complex dict traversal with multiple fallback
#      paths.  Zero direct tests.
# ---------------------------------------------------------------------------


class TestExtractStrengthData:
    """Direct unit tests for MetricsLogger._extract_strength_data."""

    def test_empty_metrics(self) -> None:
        from vibesensor.metrics_log import MetricsLogger

        strength, db, bucket, peak, floor, peaks = MetricsLogger._extract_strength_data({})
        assert strength == {}
        assert db is None
        assert bucket is None
        assert peaks == []

    def test_top_level_strength_metrics(self) -> None:
        from vibesensor.metrics_log import MetricsLogger

        metrics: dict[str, object] = {
            "strength_metrics": {
                "vibration_strength_db": 18.5,
                "strength_bucket": "l3",
                "peak_amp_g": 0.02,
                "noise_floor_amp_g": 0.001,
                "top_peaks": [{"hz": 45.0, "amp": 0.015}],
            }
        }
        strength, db, bucket, peak, floor, peaks = MetricsLogger._extract_strength_data(metrics)
        assert db == pytest.approx(18.5)
        assert bucket == "l3"
        assert len(peaks) == 1
        assert peaks[0]["hz"] == pytest.approx(45.0)

    def test_nested_combined_fallback(self) -> None:
        from vibesensor.metrics_log import MetricsLogger

        metrics: dict[str, object] = {
            "combined": {
                "strength_metrics": {
                    "vibration_strength_db": 12.0,
                    "strength_bucket": "l2",
                    "top_peaks": [],
                }
            }
        }
        strength, db, bucket, _, _, _ = MetricsLogger._extract_strength_data(metrics)
        assert db == pytest.approx(12.0)
        assert bucket == "l2"

    def test_invalid_peak_data_filtered(self) -> None:
        from vibesensor.metrics_log import MetricsLogger

        metrics: dict[str, object] = {
            "strength_metrics": {
                "vibration_strength_db": 10.0,
                "top_peaks": [
                    {"hz": float("nan"), "amp": 0.01},  # nan hz
                    {"hz": 50.0, "amp": float("inf")},  # inf amp
                    {"hz": -1.0, "amp": 0.01},  # negative hz
                    {"hz": 50.0, "amp": 0.01},  # valid
                    "not_a_dict",  # invalid type
                ],
            }
        }
        _, _, _, _, _, peaks = MetricsLogger._extract_strength_data(metrics)
        assert len(peaks) == 1
        assert peaks[0]["hz"] == pytest.approx(50.0)

    def test_empty_bucket_treated_as_none(self) -> None:
        from vibesensor.metrics_log import MetricsLogger

        metrics: dict[str, object] = {
            "strength_metrics": {
                "vibration_strength_db": 5.0,
                "strength_bucket": "",
                "top_peaks": [],
            }
        }
        _, _, bucket, _, _, _ = MetricsLogger._extract_strength_data(metrics)
        assert bucket is None


# ---------------------------------------------------------------------------
# Finding 9: MetricsLogger._resolve_speed_context  (metrics_log.py:367)
# SEVERITY: MEDIUM
# WHY: Resolves GPS/manual speed, computes estimated engine RPM from tire
#      specs and gear ratios.  Incorrect RPM estimation propagates bad data
#      into sample records and downstream analysis.  Zero direct tests.
# ---------------------------------------------------------------------------


class TestResolveSpeedContext:
    """Tests for _resolve_speed_context via a minimal MetricsLogger setup."""

    def _make_logger(self) -> tuple[Any, Any]:
        from pathlib import Path

        from vibesensor.metrics_log import MetricsLogger

        gps_mock = MagicMock()
        gps_mock.speed_mps = None
        gps_mock.effective_speed_mps = None
        gps_mock.override_speed_mps = None
        gps_mock.resolve_speed.return_value = MagicMock(source="none")

        registry = MagicMock()
        registry.active_client_ids.return_value = []

        settings_mock = MagicMock()
        settings_mock.snapshot.return_value = {
            "tire_width_mm": 205,
            "tire_aspect_pct": 55,
            "rim_in": 16,
            "final_drive_ratio": 3.73,
            "current_gear_ratio": 1.0,
            "tire_deflection_factor": None,
        }

        processor = MagicMock()

        logger = MetricsLogger(
            enabled=False,
            log_path=Path("/tmp/test"),
            metrics_log_hz=1,
            registry=registry,
            gps_monitor=gps_mock,
            processor=processor,
            analysis_settings=settings_mock,
            sensor_model="test",
            default_sample_rate_hz=800,
            fft_window_size_samples=512,
            persist_history_db=False,
        )
        return logger, gps_mock

    def test_no_speed_available(self) -> None:
        logger, _ = self._make_logger()
        speed_kmh, gps_speed, source, rpm, fdr, gr = logger._resolve_speed_context()
        assert speed_kmh is None
        assert rpm is None

    def test_gps_speed_available(self) -> None:
        logger, gps_mock = self._make_logger()
        gps_mock.speed_mps = 10.0  # 36 km/h
        gps_mock.effective_speed_mps = 10.0
        gps_mock.resolve_speed.return_value = MagicMock(source="gps")
        speed_kmh, gps_speed, source, rpm, _, _ = logger._resolve_speed_context()
        assert speed_kmh == pytest.approx(36.0, rel=0.01)
        assert gps_speed == pytest.approx(36.0, rel=0.01)
        assert source == "gps"
        assert rpm is not None and rpm > 0

    def test_manual_override(self) -> None:
        logger, gps_mock = self._make_logger()
        gps_mock.override_speed_mps = 20.0  # 72 km/h
        gps_mock.effective_speed_mps = 20.0
        gps_mock.resolve_speed.return_value = MagicMock(source="manual")
        speed_kmh, _, source, _, _, _ = logger._resolve_speed_context()
        assert speed_kmh == pytest.approx(72.0, rel=0.01)
        assert source == "manual"

    def test_no_gear_ratio_skips_rpm(self) -> None:
        logger, gps_mock = self._make_logger()
        gps_mock.effective_speed_mps = 15.0
        gps_mock.resolve_speed.return_value = MagicMock(source="gps")
        # Remove gear ratio from settings
        logger.analysis_settings.snapshot.return_value = {
            "tire_width_mm": 205,
            "tire_aspect_pct": 55,
            "rim_in": 16,
            "final_drive_ratio": 3.73,
            "current_gear_ratio": None,  # missing
            "tire_deflection_factor": None,
        }
        _, _, _, rpm, _, _ = logger._resolve_speed_context()
        assert rpm is None, "Without gear_ratio, RPM should not be estimated"


# ---------------------------------------------------------------------------
# Finding 10: summarize_run_data — edge cases (summary.py:710)
# SEVERITY: MEDIUM
# WHY: The main orchestrator function.  While it has integration tests,
#      boundary inputs (empty samples, all-None axes, zero duration) are
#      untested and represent production crash vectors.
# ---------------------------------------------------------------------------


class TestSummarizeRunDataEdgeCases:
    """Integration edge cases for summarize_run_data."""

    @staticmethod
    def _minimal_metadata() -> dict[str, Any]:
        return {
            "run_id": "test-edge",
            "start_time_utc": "2025-01-01T00:00:00Z",
            "end_time_utc": "2025-01-01T00:01:00Z",
            "sensor_model": "ADXL345",
            "raw_sample_rate_hz": 800,
        }

    def test_empty_samples_no_crash(self) -> None:
        from vibesensor.analysis.summary import summarize_run_data

        summary = summarize_run_data(self._minimal_metadata(), [], lang="en")
        assert summary["rows"] == 0
        assert summary.get("run_suitability") is not None

    def test_samples_with_all_none_axes(self) -> None:
        from vibesensor.analysis.summary import summarize_run_data

        samples: list[dict[str, Any]] = [
            {
                "t_s": i,
                "client_id": "c1",
                "location": "front",
                "vibration_strength_db": 0.0,
                "strength_bucket": "l1",
            }
            for i in range(10)
        ]
        summary = summarize_run_data(self._minimal_metadata(), samples, lang="en")
        assert summary["rows"] == 10
        accel_sanity = summary.get("data_quality", {}).get("accel_sanity", {})
        assert accel_sanity.get("saturation_count") == 0

    def test_single_sample_no_crash(self) -> None:
        from vibesensor.analysis.summary import summarize_run_data

        samples: list[dict[str, Any]] = [
            {
                "t_s": 0,
                "client_id": "c1",
                "location": "front",
                "accel_x_g": 0.1,
                "accel_y_g": 0.0,
                "accel_z_g": 1.0,
                "vibration_strength_db": 5.0,
                "strength_bucket": "l1",
            }
        ]
        summary = summarize_run_data(self._minimal_metadata(), samples, lang="en")
        assert summary["rows"] == 1
        assert summary.get("findings") is not None

    def test_nl_lang_no_crash(self) -> None:
        from vibesensor.analysis.summary import summarize_run_data

        summary = summarize_run_data(self._minimal_metadata(), [], lang="nl")
        assert summary["lang"] == "nl"

    def test_missing_metadata_fields(self) -> None:
        """Minimal metadata (only run_id) should not crash."""
        from vibesensor.analysis.summary import summarize_run_data

        summary = summarize_run_data({"run_id": "minimal"}, [], lang="en")
        assert summary["run_id"] == "minimal"
