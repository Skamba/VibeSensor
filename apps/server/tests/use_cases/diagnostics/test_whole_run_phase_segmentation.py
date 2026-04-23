from __future__ import annotations

import pytest

from vibesensor.domain import AnalysisSettingsSnapshot, DrivingPhase
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.whole_run_analysis import WholeRunContextWindowLabel
from vibesensor.use_cases.diagnostics.phase_segmentation import (
    segment_whole_run_context,
)
from vibesensor.use_cases.diagnostics.whole_run_context import (
    normalize_whole_run_context_labels,
)
from vibesensor.use_cases.diagnostics.whole_run_windows import plan_whole_run_windows


def _metadata() -> RunMetadata:
    return RunMetadata.create(
        run_id="run-1",
        start_time_utc="2025-01-01T00:00:00Z",
        sensor_model="fixture-sensor",
        raw_sample_rate_hz=800,
        feature_interval_s=0.25,
        fft_window_size_samples=2048,
        accel_scale_g_per_lsb=0.001,
        analysis_settings=AnalysisSettingsSnapshot(**AnalysisSettingsSnapshot.DEFAULTS),
    )


def test_segment_whole_run_context_builds_deterministic_intervals() -> None:
    metadata = _metadata()
    window_plan = plan_whole_run_windows(metadata=metadata, total_sample_count=3248)
    samples = sensor_frames_from_mappings(
        [
            {"t_s": 1.28, "client_id": "sensor-a", "speed_kmh": 0.0, "speed_source": "gps"},
            {"t_s": 1.53, "client_id": "sensor-a", "speed_kmh": 0.0, "speed_source": "gps"},
            {"t_s": 1.78, "client_id": "sensor-a", "speed_kmh": 20.0, "speed_source": "gps"},
            {"t_s": 2.03, "client_id": "sensor-a", "speed_kmh": 40.0, "speed_source": "gps"},
            {"t_s": 2.28, "client_id": "sensor-a", "speed_kmh": 60.0, "speed_source": "gps"},
            {"t_s": 2.53, "client_id": "sensor-a", "speed_kmh": 60.0, "speed_source": "gps"},
            {"t_s": 2.78, "client_id": "sensor-a", "speed_kmh": 60.0, "speed_source": "gps"},
        ]
    )
    labels = normalize_whole_run_context_labels(
        metadata=metadata,
        samples=samples,
        window_plan=window_plan,
    )

    result = segment_whole_run_context(labels=labels, window_plan=window_plan)

    assert [label.phase for label in result.labels] == [
        DrivingPhase.IDLE,
        DrivingPhase.IDLE,
        DrivingPhase.ACCELERATION,
        DrivingPhase.ACCELERATION,
        DrivingPhase.ACCELERATION,
        DrivingPhase.CRUISE,
        DrivingPhase.CRUISE,
    ]
    assert [label.segment_index for label in result.labels] == [0, 0, 1, 1, 1, 2, 2]
    assert [interval.phase for interval in result.intervals] == [
        DrivingPhase.IDLE,
        DrivingPhase.ACCELERATION,
        DrivingPhase.CRUISE,
    ]
    assert [
        (interval.start_window_index, interval.end_window_index) for interval in result.intervals
    ] == [(0, 1), (2, 4), (5, 6)]
    assert result.intervals[1].load_state == "transient"
    assert result.intervals[2].load_state == "steady"


def test_segment_whole_run_context_interpolates_missing_speed_gaps() -> None:
    metadata = _metadata()
    window_plan = plan_whole_run_windows(metadata=metadata, total_sample_count=2848)
    labels = tuple(
        WholeRunContextWindowLabel(
            window_index=window.window_index,
            segment_index=None,
            phase=DrivingPhase.SPEED_UNKNOWN,
            context_coverage=("missing" if window.window_index in {1, 2} else "partial"),
            speed_validity=("missing" if window.window_index in {1, 2} else "measured"),
            rpm_validity="missing",
            load_state="unknown",
            speed_kmh=(None if window.window_index in {1, 2} else 60.0),
            speed_band=(None if window.window_index in {1, 2} else "60-70 km/h"),
            speed_source=(None if window.window_index in {1, 2} else "gps"),
        )
        for window in window_plan.windows
    )

    result = segment_whole_run_context(labels=labels, window_plan=window_plan)

    assert [label.phase for label in result.labels] == [DrivingPhase.CRUISE] * 5
    assert [label.context_coverage for label in result.labels] == [
        "partial",
        "missing",
        "missing",
        "partial",
        "partial",
    ]
    assert len(result.intervals) == 1
    assert result.intervals[0].phase == DrivingPhase.CRUISE
    assert result.intervals[0].missing_context_window_count == 2


def test_segment_whole_run_context_handles_empty_sequences() -> None:
    metadata = _metadata()
    window_plan = plan_whole_run_windows(metadata=metadata, total_sample_count=1024)

    result = segment_whole_run_context(labels=(), window_plan=window_plan)

    assert result.labels == ()
    assert result.intervals == ()


def test_segment_whole_run_context_rejects_window_plan_mismatch() -> None:
    metadata = _metadata()
    window_plan = plan_whole_run_windows(metadata=metadata, total_sample_count=2248)
    labels = normalize_whole_run_context_labels(
        metadata=metadata,
        samples=sensor_frames_from_mappings(
            [{"t_s": 1.28, "client_id": "sensor-a", "speed_kmh": 10.0, "speed_source": "gps"}]
        ),
        window_plan=window_plan,
    )

    with pytest.raises(ValueError, match="one label per planned window"):
        segment_whole_run_context(labels=labels[:-1], window_plan=window_plan)
