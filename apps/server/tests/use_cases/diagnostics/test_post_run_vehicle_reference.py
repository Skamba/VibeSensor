from __future__ import annotations

from dataclasses import replace

import pytest

from vibesensor.shared.order_bands import build_diagnostic_settings
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunWindowDescriptor,
    WholeRunWindowPolicy,
)
from vibesensor.use_cases.diagnostics.post_run_vehicle_reference import (
    VehicleReferenceTimelineConfig,
    build_post_run_vehicle_reference_timeline,
    vehicle_reference_debug_fixtures,
)

_RUN_ID = "run-reference"
_SAMPLE_RATE_HZ = 100


def _metadata(*, current_gear_ratio: float | None = None) -> RunMetadata:
    settings = build_diagnostic_settings()
    if current_gear_ratio is not None:
        settings = replace(settings, current_gear_ratio=current_gear_ratio)
    return RunMetadata.create(
        run_id=_RUN_ID,
        start_time_utc="2026-01-01T00:00:00Z",
        sensor_model="adxl345",
        raw_sample_rate_hz=_SAMPLE_RATE_HZ,
        feature_interval_s=0.5,
        fft_window_size_samples=100,
        accel_scale_g_per_lsb=0.001,
        analysis_settings=settings,
    )


def _window(index: int, *, center_t_s: float) -> WholeRunWindowDescriptor:
    policy = WholeRunWindowPolicy(
        sample_rate_hz=_SAMPLE_RATE_HZ,
        window_size_samples=20,
        stride_samples=20,
        overlap_samples=0,
        feature_interval_s=0.2,
    )
    descriptor = WholeRunWindowDescriptor.from_policy(
        window_index=index,
        sample_start=max(0, int(round((center_t_s * _SAMPLE_RATE_HZ) - 10))),
        policy=policy,
    )
    return WholeRunWindowDescriptor(
        window_index=index,
        sample_start=descriptor.sample_start,
        sample_end=descriptor.sample_end,
        center_sample=descriptor.center_sample,
        start_t_s=center_t_s - 0.1,
        end_t_s=center_t_s + 0.1,
        center_t_s=center_t_s,
    )


def _sample(
    t_s: float,
    *,
    speed_kmh: float | None = 72.0,
    gps_speed_kmh: float | None = None,
    speed_source: str = "obd",
    engine_rpm: float | None = 3000.0,
    engine_rpm_source: str = "obd",
    gear: float | None = None,
    final_drive_ratio: float | None = None,
    sample_rate_hz: int | None = _SAMPLE_RATE_HZ,
) -> SensorFrame:
    return SensorFrame(
        run_id=_RUN_ID,
        timestamp_utc=f"2026-01-01T00:00:{int(t_s):02d}Z",
        t_s=t_s,
        client_id="sensor-a",
        client_name="Sensor A",
        location="front_left",
        sample_rate_hz=sample_rate_hz,
        speed_kmh=speed_kmh,
        gps_speed_kmh=gps_speed_kmh,
        speed_source=speed_source,
        engine_rpm=engine_rpm,
        engine_rpm_source=engine_rpm_source,
        gear=gear,
        final_drive_ratio=final_drive_ratio,
        accel_x_g=0.0,
        accel_y_g=0.0,
        accel_z_g=0.0,
        dominant_freq_hz=None,
        dominant_axis="",
        top_peaks=(),
        vibration_strength_db=None,
        strength_bucket=None,
        strength_peak_amp_g=None,
        strength_floor_amp_g=None,
        frames_dropped_total=0,
        queue_overflow_drops=0,
    )


def test_vehicle_reference_timeline_fixed_speed_derives_order_frequencies() -> None:
    metadata = _metadata()
    assert metadata.order_reference_spec is not None
    timeline = build_post_run_vehicle_reference_timeline(
        run_id=_RUN_ID,
        metadata=metadata,
        samples=(_sample(0.0), _sample(1.0)),
        windows=(_window(0, center_t_s=0.5),),
    )

    point = timeline.points[0]
    assert point.speed_kmh == pytest.approx(72.0)
    assert point.speed_quality == "interpolated"
    assert point.engine_hz == pytest.approx(50.0)
    assert point.wheel_hz == pytest.approx(
        metadata.order_reference_spec.wheel_hz_from_speed_kmh(72.0)
    )
    assert point.wheel_hz is not None
    assert point.final_drive_ratio is not None
    assert point.driveshaft_hz == pytest.approx(point.wheel_hz * point.final_drive_ratio)
    assert point.unavailable_reasons == ()


def test_vehicle_reference_timeline_interpolates_speed_sweep() -> None:
    timeline = build_post_run_vehicle_reference_timeline(
        run_id=_RUN_ID,
        metadata=_metadata(),
        samples=(
            _sample(0.0, speed_kmh=36.0, engine_rpm=2000.0),
            _sample(1.0, speed_kmh=72.0, engine_rpm=3000.0),
        ),
        windows=(_window(0, center_t_s=0.5),),
    )

    point = timeline.points[0]
    assert point.speed_kmh == pytest.approx(54.0)
    assert point.engine_rpm == pytest.approx(2500.0)
    assert point.speed_quality == "interpolated"
    assert point.engine_rpm_quality == "interpolated"


def test_vehicle_reference_timeline_marks_long_gps_gap_unavailable() -> None:
    timeline = build_post_run_vehicle_reference_timeline(
        run_id=_RUN_ID,
        metadata=_metadata(),
        samples=(
            _sample(0.0, speed_kmh=None, gps_speed_kmh=60.0, speed_source="gps"),
            _sample(3.0, speed_kmh=None, gps_speed_kmh=61.0, speed_source="gps"),
        ),
        windows=(_window(0, center_t_s=1.5),),
        config=VehicleReferenceTimelineConfig(
            max_interpolation_gap_s=1.0,
            max_stale_sample_age_s=0.4,
        ),
    )

    point = timeline.points[0]
    assert point.speed_kmh is None
    assert point.speed_quality == "unavailable"
    assert "stale_speed" in point.unavailable_reasons


def test_vehicle_reference_timeline_rejects_ambiguous_speed_source_switch() -> None:
    timeline = build_post_run_vehicle_reference_timeline(
        run_id=_RUN_ID,
        metadata=_metadata(),
        samples=(
            _sample(0.0, speed_kmh=70.0, speed_source="manual"),
            _sample(1.0, speed_kmh=None, gps_speed_kmh=72.0, speed_source="gps"),
        ),
        windows=(_window(0, center_t_s=0.5),),
    )

    point = timeline.points[0]
    assert point.speed_kmh is None
    assert "ambiguous_gap" in point.unavailable_reasons


def test_vehicle_reference_timeline_derives_engine_from_settings_when_rpm_missing() -> None:
    timeline = build_post_run_vehicle_reference_timeline(
        run_id=_RUN_ID,
        metadata=_metadata(),
        samples=(_sample(0.0, engine_rpm=None), _sample(1.0, engine_rpm=None)),
        windows=(_window(0, center_t_s=0.5),),
    )

    point = timeline.points[0]
    assert "missing_rpm" in point.unavailable_reasons
    assert point.driveshaft_hz is not None
    assert point.gear_ratio is not None
    assert point.engine_hz == pytest.approx(point.driveshaft_hz * point.gear_ratio)
    assert point.engine_rpm is None


def test_vehicle_reference_timeline_marks_missing_gear_without_speculation() -> None:
    timeline = build_post_run_vehicle_reference_timeline(
        run_id=_RUN_ID,
        metadata=_metadata(current_gear_ratio=0.0),
        samples=(_sample(0.0, engine_rpm=None), _sample(1.0, engine_rpm=None)),
        windows=(_window(0, center_t_s=0.5),),
    )

    point = timeline.points[0]
    assert point.gear_ratio is None
    assert point.engine_hz is None
    assert "missing_gear" in point.unavailable_reasons


def test_vehicle_reference_timeline_rejects_changing_final_drive_values() -> None:
    timeline = build_post_run_vehicle_reference_timeline(
        run_id=_RUN_ID,
        metadata=_metadata(),
        samples=(
            _sample(0.0, final_drive_ratio=3.0),
            _sample(1.0, final_drive_ratio=4.0),
        ),
        windows=(_window(0, center_t_s=0.5),),
    )

    point = timeline.points[0]
    assert point.final_drive_ratio is None
    assert point.driveshaft_hz is None
    assert "ambiguous_gap" in point.unavailable_reasons
    assert "unknown_final_drive" in point.unavailable_reasons


def test_vehicle_reference_timeline_marks_inconsistent_sample_rate() -> None:
    timeline = build_post_run_vehicle_reference_timeline(
        run_id=_RUN_ID,
        metadata=_metadata(),
        samples=(_sample(0.0, sample_rate_hz=100), _sample(1.0, sample_rate_hz=200)),
        windows=(_window(0, center_t_s=0.5),),
    )

    assert "inconsistent_sample_rate" in timeline.points[0].unavailable_reasons


def test_vehicle_reference_debug_fixtures_are_stable_rows() -> None:
    timeline = build_post_run_vehicle_reference_timeline(
        run_id=_RUN_ID,
        metadata=_metadata(),
        samples=(_sample(0.0), _sample(1.0)),
        windows=(_window(0, center_t_s=0.5), _window(1, center_t_s=0.7)),
    )

    rows = vehicle_reference_debug_fixtures(timeline)

    assert [row.window_index for row in rows] == [0, 1]
    assert rows[0].speed_kmh == pytest.approx(72.0)
    assert rows[0].unavailable_reasons == ()
