"""Tests for domain snapshot value objects.

Covers AnalysisSettingsSnapshot, RunContextSnapshot,
SpeedProfileSummary, and DrivingPhaseSummary.
"""

from __future__ import annotations

import pytest

from vibesensor.domain import (
    AnalysisSettingsSnapshot,
    CarSnapshot,
    OrderReferenceSpec,
    RunContextSnapshot,
)
from vibesensor.shared.boundaries.codecs import (
    analysis_settings_snapshot_from_mapping,
    driving_phase_summary_from_mapping,
    speed_profile_summary_from_mapping,
)
from vibesensor.shared.order_reference_settings import (
    order_reference_spec_from_mapping,
    order_reference_spec_from_snapshot,
)

# ── AnalysisSettingsSnapshot ────────────────────────────────────────


class TestAnalysisSettingsSnapshotFromDict:
    """Boundary snapshot codec tests."""

    def test_empty_dict_never_raises(self) -> None:
        snap = analysis_settings_snapshot_from_mapping({})
        assert snap.tire_width_mm == 0.0
        assert snap.tire_deflection_factor == 1.0

    def test_round_trip_fields(self) -> None:
        data = {
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
        snap = analysis_settings_snapshot_from_mapping(data)
        assert snap.tire_width_mm == 285.0
        assert snap.current_gear_ratio == 0.64
        assert snap.tire_deflection_factor == 0.96

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

    def test_order_reference_spec_is_snapshot_projection(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}
        sentinel = order_reference_spec_from_mapping(
            {"tire_width_mm": 285.0, "tire_aspect_pct": 30.0, "rim_in": 21.0},
        )
        assert sentinel is not None

        def _fake_from_settings(data: dict[str, object]) -> OrderReferenceSpec | None:
            captured.update(data)
            return sentinel

        monkeypatch.setattr(
            "vibesensor.shared.order_reference_settings.order_reference_spec_from_mapping",
            _fake_from_settings,
        )
        snap = AnalysisSettingsSnapshot(
            tire_width_mm=285.0,
            tire_aspect_pct=30.0,
            rim_in=21.0,
            final_drive_ratio=3.08,
            current_gear_ratio=0.64,
            tire_deflection_factor=0.97,
        )

        assert order_reference_spec_from_snapshot(snap) is sentinel
        assert captured["tire_width_mm"] == 285.0
        assert captured["final_drive_ratio"] == 3.08
        assert captured["tire_deflection_factor"] == 0.97


# ── RunContextSnapshot ──────────────────────────────────────────────


class TestRunContextSnapshot:
    """Typed domain tests for RunContextSnapshot."""

    def test_defaults_are_empty(self) -> None:
        ctx = RunContextSnapshot()

        assert ctx.car is None
        assert ctx.has_car_context is False
        assert ctx.analysis_settings.tire_width_mm == 0.0

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


# ── SpeedProfileSummary ──────────────────────────────────────────────


class TestSpeedProfileSummaryFromDict:
    """Boundary snapshot codec tests."""

    def test_empty_dict_never_raises(self) -> None:
        snap = speed_profile_summary_from_mapping({})
        assert snap.min_kmh is None
        assert snap.steady_speed is False
        assert snap.sample_count == 0

    def test_round_trip(self) -> None:
        data = {
            "min_kmh": 40.0,
            "max_kmh": 120.0,
            "mean_kmh": 80.0,
            "stddev_kmh": 10.5,
            "range_kmh": 80.0,
            "steady_speed": True,
            "sample_count": 500,
        }
        snap = speed_profile_summary_from_mapping(data)
        assert snap.min_kmh == 40.0
        assert snap.max_kmh == 120.0
        assert snap.steady_speed is True
        assert snap.sample_count == 500

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

    def test_round_trip(self) -> None:
        data = {
            "phase_counts": {"cruise": 100, "accel": 50},
            "phase_pcts": {"cruise": 0.66, "accel": 0.34},
            "total_samples": 150,
            "segment_count": 5,
            "has_cruise": True,
            "has_acceleration": True,
            "cruise_pct": 0.66,
            "idle_pct": 0.0,
            "speed_unknown_pct": 0.0,
        }
        snap = driving_phase_summary_from_mapping(data)
        assert snap.total_samples == 150
        assert snap.has_cruise is True
        assert snap.phase_counts["cruise"] == 100
        assert snap.cruise_pct == pytest.approx(0.66)

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
