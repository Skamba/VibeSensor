from __future__ import annotations

from dataclasses import replace

import pytest

from vibesensor.shared.order_bands import build_diagnostic_settings, tolerance_for_order
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunWindowDescriptor,
    WholeRunWindowPolicy,
)
from vibesensor.use_cases.diagnostics.post_run_order_bands import (
    OrderBand,
    OrderBandWindow,
    PostRunOrderBandsConfig,
    build_post_run_order_band_timeline,
    serialize_order_band_rows,
)
from vibesensor.use_cases.diagnostics.post_run_vehicle_reference import (
    VehicleReferenceTimeline,
    VehicleReferenceTimelineConfig,
    build_post_run_vehicle_reference_timeline,
)

_RUN_ID = "run-order-bands"
_SAMPLE_RATE_HZ = 100


def _metadata(**overrides: float) -> RunMetadata:
    settings = build_diagnostic_settings(overrides)
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
) -> SensorFrame:
    return SensorFrame(
        run_id=_RUN_ID,
        timestamp_utc=f"2026-01-01T00:00:{int(t_s):02d}Z",
        t_s=t_s,
        client_id="sensor-a",
        client_name="Sensor A",
        location="front_left",
        sample_rate_hz=_SAMPLE_RATE_HZ,
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


def _vehicle_timeline(
    *,
    metadata: RunMetadata,
    samples: tuple[SensorFrame, ...],
    windows: tuple[WholeRunWindowDescriptor, ...] = (_window(0, center_t_s=0.5),),
) -> VehicleReferenceTimeline:
    return build_post_run_vehicle_reference_timeline(
        run_id=_RUN_ID,
        metadata=metadata,
        samples=samples,
        windows=windows,
        config=VehicleReferenceTimelineConfig(max_interpolation_gap_s=1.0),
    )


def _bands_by_label(window: OrderBandWindow) -> dict[str, OrderBand]:
    return {band.label: band for band in window.bands}


def test_post_run_order_bands_fixed_speed_emit_expected_harmonics() -> None:
    metadata = _metadata()
    assert metadata.order_reference_spec is not None
    vehicle_timeline = _vehicle_timeline(
        metadata=metadata,
        samples=(_sample(0.0), _sample(1.0)),
    )

    timeline = build_post_run_order_band_timeline(
        vehicle_timeline=vehicle_timeline,
        order_reference_spec=metadata.order_reference_spec,
    )

    point = vehicle_timeline.points[0]
    bands = _bands_by_label(timeline.windows[0])
    assert tuple(bands) == (
        "wheel_1x",
        "wheel_2x",
        "driveshaft_1x",
        "driveshaft_2x",
        "engine_1x",
        "engine_2x",
    )
    wheel_1x = bands["wheel_1x"]
    assert wheel_1x.center_hz == pytest.approx(point.wheel_hz)
    assert wheel_1x.unavailable_reason is None
    assert wheel_1x.center_hz is not None
    assert point.wheel_uncertainty_pct is not None
    expected_tolerance = tolerance_for_order(
        metadata.order_reference_spec.wheel_bandwidth_pct,
        wheel_1x.center_hz,
        point.wheel_uncertainty_pct,
        min_abs_band_hz=metadata.order_reference_spec.min_abs_band_hz,
        max_band_half_width_pct=metadata.order_reference_spec.max_band_half_width_pct,
    )
    assert wheel_1x.tolerance == pytest.approx(expected_tolerance)
    assert wheel_1x.min_hz == pytest.approx(wheel_1x.center_hz * (1.0 - expected_tolerance))
    assert wheel_1x.max_hz == pytest.approx(wheel_1x.center_hz * (1.0 + expected_tolerance))
    assert bands["engine_1x"].reference_source == "obd"


def test_post_run_order_bands_follow_speed_sweep() -> None:
    metadata = _metadata()
    assert metadata.order_reference_spec is not None
    vehicle_timeline = _vehicle_timeline(
        metadata=metadata,
        samples=(
            _sample(0.0, speed_kmh=36.0, engine_rpm=2000.0),
            _sample(1.0, speed_kmh=72.0, engine_rpm=3000.0),
        ),
        windows=(_window(0, center_t_s=0.25), _window(1, center_t_s=0.75)),
    )

    timeline = build_post_run_order_band_timeline(
        vehicle_timeline=vehicle_timeline,
        order_reference_spec=metadata.order_reference_spec,
    )

    first = _bands_by_label(timeline.windows[0])["wheel_1x"]
    second = _bands_by_label(timeline.windows[1])["wheel_1x"]
    assert first.center_hz is not None
    assert second.center_hz is not None
    assert second.center_hz > first.center_hz


def test_post_run_order_bands_keep_engine_available_when_speed_missing_but_rpm_valid() -> None:
    metadata = _metadata()
    assert metadata.order_reference_spec is not None
    vehicle_timeline = _vehicle_timeline(
        metadata=metadata,
        samples=(
            _sample(0.0, speed_kmh=None, gps_speed_kmh=None, engine_rpm=2400.0),
            _sample(1.0, speed_kmh=None, gps_speed_kmh=None, engine_rpm=2400.0),
        ),
    )

    timeline = build_post_run_order_band_timeline(
        vehicle_timeline=vehicle_timeline,
        order_reference_spec=metadata.order_reference_spec,
    )

    bands = _bands_by_label(timeline.windows[0])
    assert bands["wheel_1x"].unavailable_reason == "missing_speed"
    assert bands["driveshaft_1x"].unavailable_reason == "missing_speed"
    assert bands["engine_1x"].center_hz == pytest.approx(40.0)
    assert bands["engine_1x"].unavailable_reason is None


def test_post_run_order_bands_mark_engine_unavailable_when_gear_missing() -> None:
    settings = replace(build_diagnostic_settings(), current_gear_ratio=0.0)
    metadata = RunMetadata.create(
        run_id=_RUN_ID,
        start_time_utc="2026-01-01T00:00:00Z",
        sensor_model="adxl345",
        raw_sample_rate_hz=_SAMPLE_RATE_HZ,
        feature_interval_s=0.5,
        fft_window_size_samples=100,
        accel_scale_g_per_lsb=0.001,
        analysis_settings=settings,
    )
    assert metadata.order_reference_spec is not None
    vehicle_timeline = _vehicle_timeline(
        metadata=metadata,
        samples=(_sample(0.0, engine_rpm=None), _sample(1.0, engine_rpm=None)),
    )

    timeline = build_post_run_order_band_timeline(
        vehicle_timeline=vehicle_timeline,
        order_reference_spec=metadata.order_reference_spec,
    )

    bands = _bands_by_label(timeline.windows[0])
    assert bands["wheel_1x"].unavailable_reason is None
    assert bands["driveshaft_1x"].unavailable_reason is None
    assert bands["engine_1x"].unavailable_reason == "missing_gear"


def test_post_run_order_bands_expand_with_uncertainty_settings() -> None:
    default_metadata = _metadata()
    high_uncertainty_metadata = _metadata(speed_uncertainty_pct=20.0)
    assert default_metadata.order_reference_spec is not None
    assert high_uncertainty_metadata.order_reference_spec is not None
    default_timeline = build_post_run_order_band_timeline(
        vehicle_timeline=_vehicle_timeline(
            metadata=default_metadata,
            samples=(_sample(0.0), _sample(1.0)),
        ),
        order_reference_spec=default_metadata.order_reference_spec,
    )
    high_timeline = build_post_run_order_band_timeline(
        vehicle_timeline=_vehicle_timeline(
            metadata=high_uncertainty_metadata,
            samples=(_sample(0.0), _sample(1.0)),
        ),
        order_reference_spec=high_uncertainty_metadata.order_reference_spec,
    )

    default_band = _bands_by_label(default_timeline.windows[0])["wheel_1x"]
    high_band = _bands_by_label(high_timeline.windows[0])["wheel_1x"]
    assert default_band.tolerance is not None
    assert high_band.tolerance is not None
    assert high_band.tolerance > default_band.tolerance


def test_post_run_order_bands_clamp_to_spectrum_range() -> None:
    metadata = _metadata()
    assert metadata.order_reference_spec is not None
    vehicle_timeline = _vehicle_timeline(
        metadata=metadata,
        samples=(_sample(0.0), _sample(1.0)),
    )
    point = vehicle_timeline.points[0]
    assert point.wheel_hz is not None

    timeline = build_post_run_order_band_timeline(
        vehicle_timeline=vehicle_timeline,
        order_reference_spec=metadata.order_reference_spec,
        config=PostRunOrderBandsConfig(
            wheel_harmonics=(1,),
            driveshaft_harmonics=(1,),
            engine_harmonics=(1,),
            min_frequency_hz=point.wheel_hz - 0.05,
            max_frequency_hz=point.wheel_hz + 0.05,
        ),
    )

    wheel = _bands_by_label(timeline.windows[0])["wheel_1x"]
    engine = _bands_by_label(timeline.windows[0])["engine_1x"]
    assert wheel.min_hz == pytest.approx(point.wheel_hz - 0.05)
    assert wheel.max_hz == pytest.approx(point.wheel_hz + 0.05)
    assert engine.unavailable_reason == "outside_spectrum"


def test_post_run_order_band_rows_are_serializable_for_reports() -> None:
    metadata = _metadata()
    assert metadata.order_reference_spec is not None
    timeline = build_post_run_order_band_timeline(
        vehicle_timeline=_vehicle_timeline(
            metadata=metadata,
            samples=(_sample(0.0), _sample(1.0)),
        ),
        order_reference_spec=metadata.order_reference_spec,
        config=PostRunOrderBandsConfig(
            wheel_harmonics=(1,),
            driveshaft_harmonics=(1,),
            engine_harmonics=(1,),
        ),
    )

    rows = serialize_order_band_rows(timeline)

    assert [row["label"] for row in rows] == ["wheel_1x", "driveshaft_1x", "engine_1x"]
    assert rows[0]["window_index"] == 0
    assert "center_hz" in rows[0]
