from __future__ import annotations

from vibesensor.domain import AnalysisSettingsSnapshot, DrivingPhase
from vibesensor.shared.boundaries.sensor_frames import sensor_frames_from_mappings
from vibesensor.shared.types.run_schema import RunMetadata
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


def test_normalize_whole_run_context_labels_aligns_to_centers_and_groups_rows() -> None:
    metadata = _metadata()
    window_plan = plan_whole_run_windows(metadata=metadata, total_sample_count=2448)
    samples = sensor_frames_from_mappings(
        [
            {
                "t_s": 1.28,
                "client_id": "sensor-a",
                "speed_kmh": 12.0,
                "speed_source": "gps",
                "engine_rpm": 1100.0,
                "engine_rpm_source": "obd2",
            },
            {
                "t_s": 1.53,
                "client_id": "sensor-a",
                "speed_kmh": 45.0,
                "speed_source": "manual",
                "gear": 0.64,
                "final_drive_ratio": 3.08,
            },
            {
                "t_s": 1.78,
                "client_id": "sensor-a",
                "speed_source": "none",
            },
            {
                "t_s": 1.78,
                "client_id": "sensor-b",
                "speed_kmh": 65.0,
                "speed_source": "gps",
                "gear": 0.64,
                "final_drive_ratio": 3.08,
            },
        ]
    )

    labels = normalize_whole_run_context_labels(
        metadata=metadata,
        samples=samples,
        window_plan=window_plan,
    )

    assert [label.window_index for label in labels] == [0, 1, 2]

    assert labels[0].context_coverage == "full"
    assert labels[0].speed_validity == "measured"
    assert labels[0].rpm_validity == "measured"
    assert labels[0].speed_source == "gps"
    assert labels[0].engine_rpm_source == "obd2"
    assert labels[0].speed_is_stale is False
    assert labels[0].rpm_is_stale is False
    assert labels[0].speed_context_reasons == ("speed_low",)
    assert labels[0].phase == DrivingPhase.SPEED_UNKNOWN

    assert labels[1].context_coverage == "full"
    assert labels[1].speed_validity == "assumed"
    assert labels[1].rpm_validity == "estimated"
    assert labels[1].speed_source == "manual"
    assert labels[1].engine_rpm_source == "estimated_from_speed_and_ratios"
    assert labels[1].speed_band == "40-50 km/h"
    assert labels[1].speed_context_reasons == ("speed_assumed",)

    assert labels[2].context_coverage == "full"
    assert labels[2].speed_validity == "measured"
    assert labels[2].rpm_validity == "estimated"
    assert labels[2].speed_source == "gps"
    assert labels[2].engine_rpm_source == "estimated_from_speed_and_ratios"


def test_normalize_whole_run_context_labels_marks_stale_context_explicitly() -> None:
    metadata = _metadata()
    window_plan = plan_whole_run_windows(metadata=metadata, total_sample_count=2048)
    samples = sensor_frames_from_mappings(
        [
            {
                "t_s": 0.50,
                "client_id": "sensor-a",
                "speed_kmh": 30.0,
                "speed_source": "manual",
                "gear": 0.64,
                "final_drive_ratio": 3.08,
            }
        ]
    )

    label = normalize_whole_run_context_labels(
        metadata=metadata,
        samples=samples,
        window_plan=window_plan,
    )[0]

    assert label.context_coverage == "partial"
    assert label.speed_validity == "assumed"
    assert label.rpm_validity == "estimated"
    assert label.speed_is_stale is True
    assert label.rpm_is_stale is True
    assert label.speed_context_reasons == ("speed_assumed", "speed_stale")
    assert label.phase == DrivingPhase.SPEED_UNKNOWN
    assert label.load_state == "unknown"


def test_normalize_whole_run_context_labels_marks_fallback_manual_as_stale_provenance() -> None:
    metadata = _metadata()
    window_plan = plan_whole_run_windows(metadata=metadata, total_sample_count=2048)
    samples = sensor_frames_from_mappings(
        [
            {
                "t_s": 1.28,
                "client_id": "sensor-a",
                "speed_kmh": 30.0,
                "speed_source": "fallback_manual",
                "gear": 0.64,
                "final_drive_ratio": 3.08,
            }
        ]
    )

    label = normalize_whole_run_context_labels(
        metadata=metadata,
        samples=samples,
        window_plan=window_plan,
    )[0]

    assert label.context_coverage == "partial"
    assert label.speed_validity == "assumed"
    assert label.rpm_validity == "estimated"
    assert label.speed_source == "fallback_manual"
    assert label.speed_is_stale is True
    assert label.rpm_is_stale is True
    assert label.speed_context_reasons == ("speed_assumed", "speed_stale")
    assert label.speed_band is None
    assert label.phase == DrivingPhase.SPEED_UNKNOWN
    assert label.load_state == "unknown"


def test_normalize_whole_run_context_labels_keeps_missing_windows_explicit() -> None:
    metadata = _metadata()
    window_plan = plan_whole_run_windows(metadata=metadata, total_sample_count=2048)

    label = normalize_whole_run_context_labels(
        metadata=metadata,
        samples=(),
        window_plan=window_plan,
    )[0]

    assert label.context_coverage == "missing"
    assert label.speed_validity == "missing"
    assert label.rpm_validity == "missing"
    assert label.speed_source is None
    assert label.engine_rpm_source is None
    assert label.speed_is_stale is False
    assert label.rpm_is_stale is False
    assert label.speed_context_reasons == ("speed_unavailable",)
    assert label.phase == DrivingPhase.SPEED_UNKNOWN


def test_normalize_whole_run_context_labels_marks_unstable_speed_windows() -> None:
    metadata = _metadata()
    window_plan = plan_whole_run_windows(metadata=metadata, total_sample_count=2048)
    samples = sensor_frames_from_mappings(
        [
            {
                "t_s": 1.20,
                "client_id": "sensor-a",
                "speed_kmh": 30.0,
                "speed_source": "gps",
            },
            {
                "t_s": 1.35,
                "client_id": "sensor-a",
                "speed_kmh": 70.0,
                "speed_source": "gps",
            },
        ]
    )

    label = normalize_whole_run_context_labels(
        metadata=metadata,
        samples=samples,
        window_plan=window_plan,
    )[0]

    assert label.speed_validity == "measured"
    assert label.speed_is_stale is False
    assert label.speed_context_reasons == ("speed_unstable",)


def test_normalize_whole_run_context_labels_marks_idle_when_fresh_speed_is_zero() -> None:
    metadata = _metadata()
    window_plan = plan_whole_run_windows(metadata=metadata, total_sample_count=2048)
    samples = sensor_frames_from_mappings(
        [
            {
                "t_s": 1.28,
                "client_id": "sensor-a",
                "speed_kmh": 0.0,
                "speed_source": "gps",
            }
        ]
    )

    label = normalize_whole_run_context_labels(
        metadata=metadata,
        samples=samples,
        window_plan=window_plan,
    )[0]

    assert label.phase == DrivingPhase.IDLE
    assert label.load_state == "idle"
