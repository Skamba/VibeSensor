from __future__ import annotations

import pytest

from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.diagnostics.whole_run_windows import plan_whole_run_windows


def _metadata(
    *,
    raw_sample_rate_hz: int | None = 800,
    feature_interval_s: float | None = 0.25,
    fft_window_size_samples: int | None = 2048,
) -> RunMetadata:
    return RunMetadata.create(
        run_id="run-1",
        start_time_utc="2025-01-01T00:00:00Z",
        sensor_model="fixture-sensor",
        raw_sample_rate_hz=raw_sample_rate_hz,
        feature_interval_s=feature_interval_s,
        fft_window_size_samples=fft_window_size_samples,
        accel_scale_g_per_lsb=0.001,
    )


def test_window_planner_builds_deterministic_grid_from_metadata() -> None:
    plan = plan_whole_run_windows(metadata=_metadata(), total_sample_count=2648)

    assert plan.total_window_count == 4
    assert [window.window_index for window in plan.windows] == [0, 1, 2, 3]
    assert [window.sample_start for window in plan.windows] == [0, 200, 400, 600]
    assert [window.sample_end for window in plan.windows] == [2048, 2248, 2448, 2648]
    assert plan.window(3) == plan.windows[3]
    assert plan.window(4) is None
    assert plan.expected_sensor_sample_count == 2048
    assert plan.expected_sensor_coverage_start == 0
    assert plan.expected_sensor_coverage_end == 2648
    assert plan.dropped_trailing_samples == 0
    assert plan.trailing_window_policy == "drop_incomplete_trailing"


def test_window_planner_drops_incomplete_trailing_window_samples() -> None:
    plan = plan_whole_run_windows(
        metadata=_metadata(),
        total_sample_count=2048 + 199,
    )

    assert plan.total_window_count == 1
    assert plan.windows[0].sample_start == 0
    assert plan.windows[0].sample_end == 2048
    assert plan.expected_sensor_coverage_end == 2048
    assert plan.dropped_trailing_samples == 199


def test_window_planner_returns_empty_grid_for_short_runs() -> None:
    plan = plan_whole_run_windows(metadata=_metadata(), total_sample_count=1024)

    assert plan.windows == ()
    assert plan.total_window_count == 0
    assert plan.expected_sensor_coverage_start is None
    assert plan.expected_sensor_coverage_end is None
    assert plan.dropped_trailing_samples == 1024


def test_window_planner_handles_exact_boundary_for_second_window() -> None:
    plan = plan_whole_run_windows(
        metadata=_metadata(),
        total_sample_count=2048 + 200,
    )

    assert plan.total_window_count == 2
    assert [window.sample_start for window in plan.windows] == [0, 200]
    assert plan.dropped_trailing_samples == 0


def test_window_planner_rejects_negative_total_sample_count() -> None:
    with pytest.raises(ValueError, match="total_sample_count >= 0"):
        plan_whole_run_windows(metadata=_metadata(), total_sample_count=-1)
