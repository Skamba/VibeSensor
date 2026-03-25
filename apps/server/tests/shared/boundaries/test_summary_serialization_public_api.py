from __future__ import annotations

from vibesensor.domain import DrivingPhase, DrivingPhaseInterval, LocationIntensitySummary
from vibesensor.domain.driving_phase_summary import DrivingPhaseSummary
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.shared.boundaries.summary_serialization import build_analysis_summary


def test_build_analysis_summary_exposes_stable_public_entrypoint() -> None:
    summary = build_analysis_summary(
        file_name="run.csv",
        run_id="run-1",
        samples=[{"t_s": 0.0, "speed_kmh": 32.0, "vibration_strength_db": 14.0}],
        duration_s=12.5,
        language="en",
        metadata={"end_time_utc": "2026-01-01T00:00:00Z"},
        raw_sample_rate_hz=100.0,
        speed_breakdown=[],
        phase_speed_breakdown=[],
        phase_segments=[],
        run_noise_baseline_g=0.02,
        speed_breakdown_skipped_reason=None,
        findings=(),
        top_causes=(),
        most_likely_origin=None,
        test_plan=[],
        phase_timeline=[
            DrivingPhaseInterval(
                phase=DrivingPhase.CRUISE,
                start_t_s=0.0,
                end_t_s=12.5,
            )
        ],
        speed_stats=SpeedProfileSummary(mean_kmh=32.0, sample_count=1),
        speed_stats_by_phase={},
        phase_info=DrivingPhaseSummary(has_cruise=True, cruise_pct=100.0),
        sensor_locations=["front"],
        connected_locations={"front"},
        sensor_intensity_by_location=[
            LocationIntensitySummary(location="front", p95_intensity_db=18.0)
        ],
        run_suitability=None,
        speed_values=[32.0],
        speed_non_null_pct=100.0,
        accel_stats={
            "x_mean": 0.0,
            "x_var": 0.1,
            "y_mean": 0.0,
            "y_var": 0.1,
            "z_mean": 1.0,
            "z_var": 0.2,
            "sensor_limit": 2.0,
        },
        amp_metric_values=[14.0],
    )

    assert summary["run_id"] == "run-1"
    assert summary["rows"] == 1
    assert summary["sensor_count_used"] == 1
    assert summary["warnings"] == []
    assert summary["data_quality"]["speed_coverage"]["count_non_null"] == 1
