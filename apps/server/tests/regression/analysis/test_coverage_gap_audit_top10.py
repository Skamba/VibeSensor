# ruff: noqa: E402
from __future__ import annotations

"""Coverage gap audit – untested critical code paths."""


import math
from typing import Any
from unittest.mock import MagicMock

import pytest

from vibesensor.analysis import summarize_run_data
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
from vibesensor.analysis.ranking import phase_adjusted_ranking_score as _phase_ranking_score
from vibesensor.analysis.summary_builder import build_phase_timeline as _build_phase_timeline
from vibesensor.analysis.summary_builder import (
    build_run_suitability_checks as _build_run_suitability_checks,
)
from vibesensor.analysis.summary_builder import (
    compute_accel_statistics as _compute_accel_statistics,
)
from vibesensor.metrics_log import MetricsLogger, MetricsLoggerConfig
from vibesensor.metrics_log.sample_builder import extract_strength_data, resolve_speed_context

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class _FakeSeg:
    """Minimal driving-phase segment stub for timeline tests."""

    def __init__(
        self,
        phase: DrivingPhase = DrivingPhase.CRUISE,
        start: float = 0.0,
        end: float = 10.0,
        speed_min: float = 50.0,
        speed_max: float = 60.0,
    ) -> None:
        self.phase = phase
        self.start_t_s = start
        self.end_t_s = end
        self.speed_min_kmh = speed_min
        self.speed_max_kmh = speed_max


_SUITABILITY_DEFAULTS: dict[str, Any] = {
    "steady_speed": False,
    "speed_sufficient": True,
    "sensor_ids": {"s1", "s2", "s3"},
    "reference_complete": True,
    "sat_count": 0,
    "samples": [],
}


def _suitability_checks(**overrides: Any) -> list[dict[str, Any]]:
    """Call _build_run_suitability_checks with sensible defaults + overrides."""
    kw = {**_SUITABILITY_DEFAULTS, **overrides}
    return _build_run_suitability_checks(**kw)


def _make_metrics_logger() -> tuple[MetricsLogger, MagicMock]:
    """Build a minimal MetricsLogger with mocked dependencies."""
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

    logger = MetricsLogger(
        MetricsLoggerConfig(
            enabled=False,
            metrics_log_hz=1,
            sensor_model="test",
            default_sample_rate_hz=800,
            fft_window_size_samples=512,
            persist_history_db=False,
        ),
        registry=registry,
        gps_monitor=gps_mock,
        processor=MagicMock(),
        analysis_settings=settings_mock,
    )
    return logger, gps_mock


class TestComputeOrderConfidence:
    """Direct unit tests for _compute_order_confidence."""

    _DEFAULTS: dict[str, Any] = {
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

    @classmethod
    def _call(cls, **overrides: Any) -> float:
        return _compute_order_confidence(**{**cls._DEFAULTS, **overrides})

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

    @pytest.mark.parametrize(
        ("normal_kw", "penalty_kw"),
        [
            pytest.param(
                {"weak_spatial_separation": False},
                {"weak_spatial_separation": True},
                id="weak_spatial_separation",
            ),
            pytest.param(
                {"constant_speed": False},
                {"constant_speed": True},
                id="constant_speed",
            ),
            pytest.param(
                {"is_diffuse_excitation": False},
                {"is_diffuse_excitation": True, "diffuse_penalty": 0.75},
                id="diffuse_excitation",
            ),
            pytest.param(
                {"n_connected_locations": 3},
                {"n_connected_locations": 1},
                id="single_sensor",
            ),
            pytest.param(
                {"absolute_strength_db": 25.0},
                {"absolute_strength_db": 12.0},
                id="light_strength_band",
            ),
        ],
    )
    def test_penalty_reduces_confidence(
        self,
        normal_kw: dict[str, Any],
        penalty_kw: dict[str, Any],
    ) -> None:
        assert self._call(**penalty_kw) < self._call(**normal_kw)

    def test_path_compliance_shifts_weights(self) -> None:
        """Higher path_compliance should shift weight from corr to match."""
        stiff = self._call(path_compliance=1.0, corr_val=0.0, effective_match_rate=0.80)
        compliant = self._call(path_compliance=1.5, corr_val=0.0, effective_match_rate=0.80)
        assert compliant >= stiff - 0.02

    def test_corroborating_locations_boost(self) -> None:
        base = self._call(corroborating_locations=1)
        boosted = self._call(corroborating_locations=3)
        assert boosted > base, "3+ corroborating locations should boost confidence"


class TestDetectDiffuseExcitation:
    """Direct unit tests for _detect_diffuse_excitation."""

    def test_single_sensor_returns_not_diffuse(self) -> None:
        is_diff, penalty = _detect_diffuse_excitation(
            connected_locations={"front_left"},
            possible_by_location={"front_left": 20},
            matched_by_location={"front_left": 15},
            matched_points=[{"location": "front_left", "amp": 0.1}] * 15,
        )
        assert not is_diff
        assert penalty == 1.0

    def test_uniform_rates_uniform_amplitude_is_diffuse(self) -> None:
        locs = {"front_left", "front_right", "rear"}
        possible = dict.fromkeys(locs, 30)
        matched = dict.fromkeys(locs, 20)
        pts = [{"location": loc, "amp": 0.05} for loc in locs for _ in range(20)]
        is_diff, penalty = _detect_diffuse_excitation(locs, possible, matched, pts)
        assert is_diff, "Uniform rates + uniform amplitude should be diffuse"
        assert penalty < 1.0

    def test_dominant_amplitude_is_not_diffuse(self) -> None:
        locs = {"front_left", "rear"}
        possible = {"front_left": 20, "rear": 20}
        matched = {"front_left": 15, "rear": 14}
        pts = [{"location": "front_left", "amp": 0.30}] * 15 + [
            {"location": "rear", "amp": 0.05},
        ] * 14
        is_diff, penalty = _detect_diffuse_excitation(locs, possible, matched, pts)
        assert not is_diff, "Strong amplitude dominance should NOT be diffuse"

    def test_insufficient_samples_per_location(self) -> None:
        locs = {"front_left", "rear"}
        possible = {"front_left": 2, "rear": 2}
        matched = {"front_left": 2, "rear": 2}
        pts = [{"location": "front_left", "amp": 0.05}] * 2
        is_diff, penalty = _detect_diffuse_excitation(locs, possible, matched, pts)
        assert not is_diff, "Too few samples should not trigger diffuse"

    def test_empty_matched_points(self) -> None:
        locs = {"a", "b"}
        is_diff, penalty = _detect_diffuse_excitation(
            locs,
            {"a": 20, "b": 20},
            {"a": 15, "b": 15},
            [],
        )
        # With no amplitude data, amplitude check defaults to uniform
        assert isinstance(is_diff, bool)
        assert penalty <= 1.0


class TestSuppressEngineAliases:
    """Direct unit tests for _suppress_engine_aliases."""

    @staticmethod
    def _make_finding(source: str, conf: float) -> dict[str, object]:
        return {
            "suspected_source": source,
            "confidence_0_to_1": conf,
            "finding_id": "F_ORDER",
        }

    def test_no_wheel_no_suppression(self) -> None:
        findings = [
            (1.0, self._make_finding("engine", 0.60)),
            (0.5, self._make_finding("driveshaft", 0.40)),
        ]
        result = _suppress_engine_aliases(findings)
        assert any(f.get("suspected_source") == "engine" for f in result), (
            "Engine finding should survive when no wheel finding exists"
        )

    def test_engine_suppressed_by_stronger_wheel(self) -> None:
        findings = [
            (1.0, self._make_finding("wheel/tire", 0.70)),
            (0.8, self._make_finding("engine", 0.65)),
        ]
        result = _suppress_engine_aliases(findings)
        engine_findings = [f for f in result if f.get("suspected_source") == "engine"]
        if engine_findings:
            assert float(engine_findings[0]["confidence_0_to_1"]) < 0.65

    def test_strong_engine_not_suppressed(self) -> None:
        findings = [
            (0.3, self._make_finding("wheel/tire", 0.30)),
            (1.0, self._make_finding("engine", 0.90)),
        ]
        result = _suppress_engine_aliases(findings)
        engine_findings = [f for f in result if f.get("suspected_source") == "engine"]
        assert engine_findings, "Strong engine should survive weak wheel"

    def test_empty_input(self) -> None:
        assert _suppress_engine_aliases([]) == []

    def test_output_capped_at_5(self) -> None:
        findings = [(i, self._make_finding("wheel/tire", 0.50 + i * 0.05)) for i in range(7)]
        result = _suppress_engine_aliases(findings)
        assert len(result) <= 5


class TestBuildRunSuitabilityChecks:
    """Direct unit tests for _build_run_suitability_checks."""

    def test_all_pass(self) -> None:
        checks = _suitability_checks()
        assert all(c["state"] == "pass" for c in checks), (
            f"All checks should pass: {[c['check_key'] for c in checks if c['state'] != 'pass']}"
        )

    @pytest.mark.parametrize(
        ("overrides", "check_key"),
        [
            pytest.param(
                {"steady_speed": True},
                "SUITABILITY_CHECK_SPEED_VARIATION",
                id="speed_variation_steady",
            ),
            pytest.param(
                {"sensor_ids": {"s1"}},
                "SUITABILITY_CHECK_SENSOR_COVERAGE",
                id="sensor_coverage_below_3",
            ),
            pytest.param(
                {"sat_count": 5},
                "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
                id="saturation",
            ),
            pytest.param(
                {
                    "samples": [
                        {"client_id": "c1", "frames_dropped_total": 0},
                        {"client_id": "c1", "frames_dropped_total": 10},
                    ],
                },
                "SUITABILITY_CHECK_FRAME_INTEGRITY",
                id="frame_integrity_dropped",
            ),
            pytest.param(
                {"reference_complete": False},
                "SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
                id="reference_incomplete",
            ),
        ],
    )
    def test_warn_condition(self, overrides: dict[str, Any], check_key: str) -> None:
        checks = _suitability_checks(**overrides)
        check = next(c for c in checks if c["check_key"] == check_key)
        assert check["state"] == "warn"


class TestBuildPhaseTimeline:
    """Direct unit tests for _build_phase_timeline."""

    def test_empty_segments_returns_empty(self) -> None:
        assert _build_phase_timeline([], [], min_confidence=0.25) == []

    def test_basic_segment_output(self) -> None:
        segs = [
            _FakeSeg(DrivingPhase.CRUISE, 0.0, 30.0, speed_min=40.0, speed_max=80.0),
            _FakeSeg(DrivingPhase.ACCELERATION, 30.0, 45.0, speed_min=40.0, speed_max=80.0),
        ]
        findings: list[dict[str, object]] = [
            {
                "finding_id": "F001",
                "confidence_0_to_1": 0.60,
                "phase_evidence": {"phases_detected": ["cruise"]},
            },
        ]
        entries = _build_phase_timeline(segs, findings, min_confidence=0.25)
        assert len(entries) == 2
        assert entries[0]["phase"] == "cruise"
        assert entries[0]["has_fault_evidence"] is True
        assert entries[1]["has_fault_evidence"] is False

    @pytest.mark.parametrize(
        "finding",
        [
            pytest.param(
                {
                    "finding_id": "REF_SPEED",
                    "confidence_0_to_1": 0.90,
                    "phase_evidence": {"phases_detected": ["cruise"]},
                },
                id="ref_finding_ignored",
            ),
            pytest.param(
                {
                    "finding_id": "F001",
                    "confidence_0_to_1": 0.01,
                    "phase_evidence": {"phases_detected": ["cruise"]},
                },
                id="low_confidence_ignored",
            ),
        ],
    )
    def test_finding_does_not_mark_phase(self, finding: dict[str, object]) -> None:
        """REF_ findings and below-threshold findings should not contribute."""
        entries = _build_phase_timeline([_FakeSeg()], [finding], min_confidence=0.25)
        assert entries[0]["has_fault_evidence"] is False


class TestComputeAccelStatistics:
    """Direct unit tests for _compute_accel_statistics."""

    def test_empty_samples(self) -> None:
        result = _compute_accel_statistics([], "ADXL345")
        assert result["sat_count"] == 0
        assert result["accel_x_vals"] == []
        assert result["accel_mag_vals"] == []

    def test_basic_values(self) -> None:
        samples: list[dict[str, Any]] = [
            {
                "accel_x_g": 0.1,
                "accel_y_g": 0.2,
                "accel_z_g": 1.0,
                "vibration_strength_db": 12.0,
            },
        ]
        result = _compute_accel_statistics(samples, "ADXL345")
        assert len(result["accel_x_vals"]) == 1
        assert result["accel_x_vals"][0] == pytest.approx(0.1)
        assert len(result["accel_mag_vals"]) == 1
        expected_mag = math.sqrt(0.1**2 + 0.2**2 + 1.0**2)
        assert result["accel_mag_vals"][0] == pytest.approx(expected_mag, rel=1e-3)

    def test_saturation_detected_near_limit(self) -> None:
        # ADXL345 has ±16g limit; 98% threshold = 15.68g
        samples: list[dict[str, Any]] = [
            {"accel_x_g": 15.7, "accel_y_g": 0.0, "accel_z_g": 0.0},
        ]
        result = _compute_accel_statistics(samples, "ADXL345")
        assert result["sat_count"] >= 1, "Near-limit value should count as saturation"

    def test_missing_axes_handled(self) -> None:
        samples: list[dict[str, Any]] = [{"accel_x_g": 0.5}]
        result = _compute_accel_statistics(samples, "unknown")
        assert len(result["accel_x_vals"]) == 1
        assert result["accel_y_vals"] == []
        assert result["accel_mag_vals"] == []  # can't compute magnitude without all 3

    def test_unknown_sensor_no_saturation_check(self) -> None:
        """When sensor_limit is None, no saturation counting should occur."""
        samples: list[dict[str, Any]] = [
            {"accel_x_g": 999.0, "accel_y_g": 999.0, "accel_z_g": 999.0},
        ]
        result = _compute_accel_statistics(samples, "totally_unknown_sensor")
        # With unknown sensor, sensor_limit should be None → sat_count = 0
        if result["sensor_limit"] is None:
            assert result["sat_count"] == 0


class TestPhaseRankingScore:
    """Direct unit tests for _phase_ranking_score."""

    def test_no_phase_evidence(self) -> None:
        score = _phase_ranking_score({"confidence_0_to_1": 0.80})
        # No phase_evidence → cruise_fraction=0 → multiplier=0.85
        assert score == pytest.approx(0.80 * 0.85, rel=1e-3)

    def test_full_cruise_phase(self) -> None:
        finding: dict[str, object] = {
            "confidence_0_to_1": 0.80,
            "phase_evidence": {"cruise_fraction": 1.0},
        }
        score = _phase_ranking_score(finding)
        assert score == pytest.approx(0.80 * 1.0, rel=1e-3)

    def test_half_cruise(self) -> None:
        finding: dict[str, object] = {
            "confidence_0_to_1": 0.80,
            "phase_evidence": {"cruise_fraction": 0.50},
        }
        score = _phase_ranking_score(finding)
        expected = 0.80 * (0.85 + 0.15 * 0.50)
        assert score == pytest.approx(expected, rel=1e-3)

    @pytest.mark.parametrize(
        "finding",
        [
            pytest.param({"confidence_0_to_1": None}, id="none_confidence"),
            pytest.param({}, id="missing_confidence_key"),
        ],
    )
    def test_degenerate_confidence_returns_zero(self, finding: dict[str, object]) -> None:
        assert _phase_ranking_score(finding) == 0.0


class TestExtractStrengthData:
    """Direct unit tests for MetricsLogger._extract_strength_data."""

    def test_empty_metrics(self) -> None:
        strength, db, bucket, peak, floor, peaks = extract_strength_data({})
        assert strength == {}
        assert db is None
        assert bucket is None
        assert peaks == []

    def test_combined_strength_metrics(self) -> None:
        metrics: dict[str, object] = {
            "combined": {
                "strength_metrics": {
                    "vibration_strength_db": 18.5,
                    "strength_bucket": "l3",
                    "peak_amp_g": 0.02,
                    "noise_floor_amp_g": 0.001,
                    "top_peaks": [{"hz": 45.0, "amp": 0.015}],
                },
            },
        }
        strength, db, bucket, peak, floor, peaks = extract_strength_data(metrics)
        assert db == pytest.approx(18.5)
        assert bucket == "l3"
        assert len(peaks) == 1
        assert peaks[0]["hz"] == pytest.approx(45.0)

    def test_nested_combined_strength_metrics(self) -> None:
        metrics: dict[str, object] = {
            "combined": {
                "strength_metrics": {
                    "vibration_strength_db": 12.0,
                    "strength_bucket": "l2",
                    "top_peaks": [],
                },
            },
        }
        strength, db, bucket, _, _, _ = extract_strength_data(metrics)
        assert db == pytest.approx(12.0)
        assert bucket == "l2"

    def test_invalid_peak_data_filtered(self) -> None:
        metrics: dict[str, object] = {
            "combined": {
                "strength_metrics": {
                    "vibration_strength_db": 10.0,
                    "top_peaks": [
                        {"hz": float("nan"), "amp": 0.01},  # nan hz
                        {"hz": 50.0, "amp": float("inf")},  # inf amp
                        {"hz": -1.0, "amp": 0.01},  # negative hz
                        {"hz": 50.0, "amp": 0.01},  # valid
                        "not_a_dict",  # invalid type
                    ],
                },
            },
        }
        _, _, _, _, _, peaks = extract_strength_data(metrics)
        assert len(peaks) == 1
        assert peaks[0]["hz"] == pytest.approx(50.0)

    def test_empty_bucket_treated_as_none(self) -> None:
        metrics: dict[str, object] = {
            "combined": {
                "strength_metrics": {
                    "vibration_strength_db": 5.0,
                    "strength_bucket": "",
                    "top_peaks": [],
                },
            },
        }
        _, _, bucket, _, _, _ = extract_strength_data(metrics)
        assert bucket is None


class TestResolveSpeedContext:
    """Tests for _resolve_speed_context via a minimal MetricsLogger setup."""

    def test_no_speed_available(self) -> None:
        logger, _ = _make_metrics_logger()
        speed_kmh, gps_speed, source, rpm, fdr, gr = resolve_speed_context(
            logger.gps_monitor,
            logger.analysis_settings.snapshot(),
        )
        assert speed_kmh is None
        assert rpm is None

    def test_gps_speed_available(self) -> None:
        logger, gps_mock = _make_metrics_logger()
        gps_mock.speed_mps = 10.0  # 36 km/h
        gps_mock.resolve_speed.return_value = MagicMock(source="gps", speed_mps=10.0)
        speed_kmh, gps_speed, source, rpm, _, _ = resolve_speed_context(
            logger.gps_monitor,
            logger.analysis_settings.snapshot(),
        )
        assert speed_kmh == pytest.approx(36.0, rel=0.01)
        assert gps_speed == pytest.approx(36.0, rel=0.01)
        assert source == "gps"
        assert rpm is not None and rpm > 0

    def test_manual_override(self) -> None:
        logger, gps_mock = _make_metrics_logger()
        gps_mock.override_speed_mps = 20.0  # 72 km/h
        gps_mock.resolve_speed.return_value = MagicMock(source="manual", speed_mps=20.0)
        speed_kmh, _, source, _, _, _ = resolve_speed_context(
            logger.gps_monitor,
            logger.analysis_settings.snapshot(),
        )
        assert speed_kmh == pytest.approx(72.0, rel=0.01)
        assert source == "manual"

    def test_no_gear_ratio_skips_rpm(self) -> None:
        logger, gps_mock = _make_metrics_logger()
        gps_mock.resolve_speed.return_value = MagicMock(source="gps", speed_mps=15.0)
        # Remove gear ratio from settings
        logger.analysis_settings.snapshot.return_value = {
            "tire_width_mm": 205,
            "tire_aspect_pct": 55,
            "rim_in": 16,
            "final_drive_ratio": 3.73,
            "current_gear_ratio": None,  # missing
            "tire_deflection_factor": None,
        }
        _, _, _, rpm, _, _ = resolve_speed_context(
            logger.gps_monitor,
            logger.analysis_settings.snapshot(),
        )
        assert rpm is None, "Without gear_ratio, RPM should not be estimated"


class TestSummarizeRunDataEdgeCases:
    """Integration edge cases for summarize_run_data."""

    _MINIMAL_META: dict[str, Any] = {
        "run_id": "test-edge",
        "start_time_utc": "2025-01-01T00:00:00Z",
        "end_time_utc": "2025-01-01T00:01:00Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
    }

    def test_empty_samples_no_crash(self) -> None:
        summary = summarize_run_data(self._MINIMAL_META, [], lang="en")
        assert summary["rows"] == 0
        assert summary.get("run_suitability") is not None

    def test_samples_with_all_none_axes(self) -> None:
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
        summary = summarize_run_data(self._MINIMAL_META, samples, lang="en")
        assert summary["rows"] == 10
        accel_sanity = summary.get("data_quality", {}).get("accel_sanity", {})
        assert accel_sanity.get("saturation_count") == 0

    def test_single_sample_no_crash(self) -> None:
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
            },
        ]
        summary = summarize_run_data(self._MINIMAL_META, samples, lang="en")
        assert summary["rows"] == 1
        assert summary.get("findings") is not None

    def test_nl_lang_no_crash(self) -> None:
        summary = summarize_run_data(self._MINIMAL_META, [], lang="nl")
        assert summary["lang"] == "nl"

    def test_missing_metadata_fields(self) -> None:
        """Minimal metadata (only run_id) should not crash."""
        summary = summarize_run_data({"run_id": "minimal"}, [], lang="en")
        assert summary["run_id"] == "minimal"
