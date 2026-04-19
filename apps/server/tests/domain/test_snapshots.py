"""Tests for domain snapshot value objects.

Covers AnalysisSettingsSnapshot, RunContextSnapshot,
SpeedProfileSummary, and DrivingPhaseSummary.
"""

from __future__ import annotations

import pytest

from vibesensor.domain import (
    AnalysisSettingsSnapshot,
    CarSnapshot,
    RunContextSnapshot,
)
from vibesensor.shared.boundaries.codecs import (
    analysis_settings_snapshot_from_mapping,
    driving_phase_summary_from_mapping,
    speed_profile_summary_from_mapping,
)
from vibesensor.shared.order_reference_settings import order_reference_spec_from_snapshot

# ── AnalysisSettingsSnapshot ────────────────────────────────────────


class TestAnalysisSettingsSnapshotFromDict:
    """Boundary snapshot codec tests."""

    def test_mixed_invalid_payload_blocks_order_reference_projection(self) -> None:
        snap = analysis_settings_snapshot_from_mapping(
            {
                "tire_width_mm": "bad",
                "tire_aspect_pct": 55.0,
                "rim_in": 16.0,
                "current_gear_ratio": "0.82",
                "tire_deflection_factor": None,
            }
        )

        assert snap.tire_width_mm == 0.0
        assert snap.tire_aspect_pct == 55.0
        assert snap.rim_in == 16.0
        assert snap.current_gear_ratio == 0.82
        assert snap.tire_deflection_factor == 1.0
        assert order_reference_spec_from_snapshot(snap) is None

    def test_combined_fields_project_a_complete_order_reference_spec(self) -> None:
        snap = analysis_settings_snapshot_from_mapping(
            {
            "tire_width_mm": 285.0,
            "tire_aspect_pct": 30.0,
            "rim_in": 21.0,
            "final_drive_ratio": 3.08,
            "current_gear_ratio": 0.64,
            "wheel_bandwidth_pct": 0.0025,
            "driveshaft_bandwidth_pct": 0.0025,
            "engine_bandwidth_pct": 0.0025,
            "speed_uncertainty_pct": 0.05,
            "tire_diameter_uncertainty_pct": 0.02,
            "final_drive_uncertainty_pct": 0.01,
            "gear_uncertainty_pct": 0.01,
            "min_abs_band_hz": 1.0,
            "max_band_half_width_pct": 0.05,
            "tire_deflection_factor": 0.96,
            }
        )

        spec = order_reference_spec_from_snapshot(snap)

        assert spec is not None
        assert spec.tire_spec is not None
        assert spec.tire_spec.width_mm == 285.0
        assert spec.tire_spec.deflection_factor == 0.96
        assert spec.final_drive_ratio == pytest.approx(3.08)
        assert spec.current_gear_ratio == pytest.approx(0.64)
        assert spec.has_engine_reference is True
        assert spec.is_complete is True
        assert spec.tire_circumference_m > 0

    def test_non_numeric_values_default(self) -> None:
        snap = analysis_settings_snapshot_from_mapping({"tire_width_mm": "not_a_number"})
        assert snap.tire_width_mm == 0.0

    def test_none_values_default(self) -> None:
        snap = analysis_settings_snapshot_from_mapping({"rim_in": None})
        assert snap.rim_in == 0.0

    def test_infinity_defaults(self) -> None:
        snap = analysis_settings_snapshot_from_mapping({"tire_width_mm": float("inf")})
        assert snap.tire_width_mm == 0.0


class TestAnalysisSettingsOrderRef:
    """Order-reference projection helpers."""

    def test_missing_tire_returns_none(self) -> None:
        snap = AnalysisSettingsSnapshot()
        assert order_reference_spec_from_snapshot(snap) is None

    def test_valid_tire_returns_spec(self) -> None:
        snap = analysis_settings_snapshot_from_mapping(
            {"tire_width_mm": 285.0, "tire_aspect_pct": 30.0, "rim_in": 21.0}
        )
        spec = order_reference_spec_from_snapshot(snap)
        assert spec is not None
        assert spec.tire_spec is not None
        assert spec.tire_spec.width_mm == 285.0

    def test_snapshot_projection_preserves_engine_reference_inputs(self) -> None:
        snap = AnalysisSettingsSnapshot(
            tire_width_mm=285.0,
            tire_aspect_pct=30.0,
            rim_in=21.0,
            final_drive_ratio=3.08,
            current_gear_ratio=0.64,
            tire_deflection_factor=0.97,
        )

        spec = order_reference_spec_from_snapshot(snap)

        assert spec is not None
        assert spec.final_drive_ratio == pytest.approx(3.08)
        assert spec.current_gear_ratio == pytest.approx(0.64)
        assert spec.tire_spec is not None
        assert spec.tire_spec.deflection_factor == pytest.approx(0.97)
        assert spec.has_engine_reference is True


# ── RunContextSnapshot ──────────────────────────────────────────────


class TestRunContextSnapshot:
    """Typed domain tests for RunContextSnapshot."""

    def test_absent_car_context_degrades_consumer_accessors(self) -> None:
        ctx = RunContextSnapshot()

        assert ctx.car is None
        assert ctx.has_car_context is False
        assert ctx.active_car_id is None
        assert ctx.car_name is None
        assert ctx.car_type is None
        assert ctx.car_variant is None
        assert order_reference_spec_from_snapshot(ctx.analysis_settings) is None

    def test_order_reference_spec_delegates_to_analysis_settings(self) -> None:
        ctx = RunContextSnapshot(
            analysis_settings=AnalysisSettingsSnapshot(
                tire_width_mm=285.0,
                tire_aspect_pct=30.0,
                rim_in=21.0,
            ),
        )

        assert order_reference_spec_from_snapshot(ctx.analysis_settings) is not None

    def test_convenience_accessors_delegate_to_car_snapshot(self) -> None:
        ctx = RunContextSnapshot(
            analysis_settings=AnalysisSettingsSnapshot(),
            car=CarSnapshot(
                car_id="car-1",
                name="Primary",
                car_type="sedan",
                variant="track",
            ),
        )

        assert ctx.has_car_context is True
        assert ctx.active_car_id == "car-1"
        assert ctx.car_name == "Primary"
        assert ctx.car_type == "sedan"
        assert ctx.car_variant == "track"

    def test_convenience_accessors_degrade_when_car_absent(self) -> None:
        ctx = RunContextSnapshot()

        assert ctx.has_car_context is False
        assert ctx.active_car_id is None
        assert ctx.car_name is None
        assert ctx.car_type is None
        assert ctx.car_variant is None

    def test_partial_car_context_stays_usable_without_fake_analysis_defaults(self) -> None:
        ctx = RunContextSnapshot(
            car=CarSnapshot(
                car_id=None,
                name="Project Car",
                car_type=None,
                variant="prototype",
            ),
        )

        assert ctx.has_car_context is True
        assert ctx.active_car_id is None
        assert ctx.car_name == "Project Car"
        assert ctx.car_type is None
        assert ctx.car_variant == "prototype"
        assert order_reference_spec_from_snapshot(ctx.analysis_settings) is None


# ── SpeedProfileSummary ──────────────────────────────────────────────


class TestSpeedProfileSummaryFromDict:
    """Boundary snapshot codec tests."""

    def test_empty_dict_never_raises(self) -> None:
        snap = speed_profile_summary_from_mapping({})
        assert snap.min_kmh is None
        assert snap.steady_speed is False
        assert snap.sample_count == 0

    def test_sanitizes_mixed_speed_payload_without_hidden_normalization(self) -> None:
        snap = speed_profile_summary_from_mapping(
            {
                "min_kmh": -5.0,
                "max_kmh": "120.0",
                "mean_kmh": "80.5",
                "stddev_kmh": float("inf"),
                "range_kmh": "bad",
                "steady_speed": "yes",
                "sample_count": "12",
            }
        )

        assert snap.min_kmh == pytest.approx(-5.0)
        assert snap.max_kmh == pytest.approx(120.0)
        assert snap.mean_kmh == pytest.approx(80.5)
        assert snap.stddev_kmh is None
        assert snap.range_kmh is None
        assert snap.steady_speed is False
        assert snap.sample_count == 12

    def test_non_numeric_speed_defaults_to_none(self) -> None:
        snap = speed_profile_summary_from_mapping({"min_kmh": "bad"})
        assert snap.min_kmh is None

    def test_infinity_speed_defaults_to_none(self) -> None:
        snap = speed_profile_summary_from_mapping({"mean_kmh": float("inf")})
        assert snap.mean_kmh is None


# ── DrivingPhaseSummary ────────────────────────────────────────────────────


class TestDrivingPhaseSummaryFromDict:
    """from_dict() constructor tests."""

    def test_empty_dict_never_raises(self) -> None:
        snap = driving_phase_summary_from_mapping({})
        assert snap.total_samples == 0
        assert snap.has_cruise is False
        assert dict(snap.phase_counts) == {}

    def test_counts_percentages_and_flags_fall_back_consistently(self) -> None:
        snap = driving_phase_summary_from_mapping(
            {
                "phase_counts": {"cruise": "100", "acceleration": 50, "idle": "bad"},
                "phase_pcts": {"cruise": 0.66, "idle": "0.10", "speed_unknown": "bad"},
                "total_samples": "150",
                "segment_count": "5",
            }
        )

        assert dict(snap.phase_counts) == {"cruise": 100, "acceleration": 50}
        assert dict(snap.phase_pcts) == {"cruise": 0.66, "idle": 0.10}
        assert snap.total_samples == 150
        assert snap.segment_count == 5
        assert snap.has_cruise is True
        assert snap.has_acceleration is True
        assert snap.cruise_pct == pytest.approx(0.66)
        assert snap.idle_pct == pytest.approx(0.10)
        assert snap.speed_unknown_pct == 0.0

    def test_explicit_flags_and_percentages_override_count_fallbacks(self) -> None:
        snap = driving_phase_summary_from_mapping(
            {
                "phase_counts": {"cruise": 10, "acceleration": 3},
                "phase_pcts": {"cruise": 0.9},
                "has_cruise": False,
                "has_acceleration": False,
                "cruise_pct": 0.0,
            }
        )

        assert snap.has_cruise is False
        assert snap.has_acceleration is False
        assert snap.cruise_pct == 0.0

    def test_invalid_phase_counts_skipped(self) -> None:
        snap = driving_phase_summary_from_mapping({"phase_counts": {"cruise": "bad", "accel": 10}})
        assert "cruise" not in snap.phase_counts
        assert snap.phase_counts["accel"] == 10

    def test_phase_counts_immutable(self) -> None:
        snap = driving_phase_summary_from_mapping({"phase_counts": {"cruise": 5}})
        with pytest.raises(TypeError):
            snap.phase_counts["new"] = 1

    def test_phase_pcts_immutable(self) -> None:
        snap = driving_phase_summary_from_mapping({"phase_pcts": {"cruise": 0.5}})
        with pytest.raises(TypeError):
            snap.phase_pcts["new"] = 0.1
