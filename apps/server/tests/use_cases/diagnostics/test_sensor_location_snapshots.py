from __future__ import annotations

from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.shared.types.run_schema import RunMetadata, RunSensorMetadata
from vibesensor.shared.types.sensor_frame import SensorFrame
from vibesensor.use_cases.diagnostics.run_analysis_projection import build_sensor_analysis


def test_build_sensor_analysis_prefers_run_sensor_snapshot_labels() -> None:
    metadata = RunMetadata.create(
        run_id="run-1",
        start_time_utc="2026-01-01T00:00:00Z",
        sensor_model="ADXL345",
        raw_sample_rate_hz=800,
        feature_interval_s=0.5,
        fft_window_size_samples=1024,
        accel_scale_g_per_lsb=None,
        analysis_settings=AnalysisSettingsSnapshot(),
        sensor_snapshots=(
            RunSensorMetadata(
                sensor_id="sensor-a",
                display_name="Stable front left",
                location_code="front_left_wheel",
            ),
        ),
    )
    samples = [
        SensorFrame(
            run_id="run-1",
            timestamp_utc="2026-01-01T00:00:00Z",
            t_s=0.0,
            client_id="sensor-a",
            client_name="Renamed live row",
            location="rear_right_wheel",
            sample_rate_hz=800,
            speed_kmh=None,
            gps_speed_kmh=None,
            speed_source="none",
            engine_rpm=None,
            engine_rpm_source="missing",
            gear=None,
            final_drive_ratio=None,
            accel_x_g=None,
            accel_y_g=None,
            accel_z_g=None,
            dominant_freq_hz=None,
            dominant_axis="combined",
            top_peaks=tuple(),
            vibration_strength_db=20.0,
            strength_bucket="l2",
            strength_peak_amp_g=0.1,
            strength_floor_amp_g=0.01,
            frames_dropped_total=0,
            queue_overflow_drops=0,
        )
    ]

    sensor_locations, connected_locations, sensor_intensity = build_sensor_analysis(
        samples=samples,
        language="en",
        per_sample_phases=[],
        metadata=metadata,
    )

    assert sensor_locations == ["Front Left Wheel"]
    assert connected_locations == {"Front Left Wheel"}
    assert sensor_intensity[0].location == "Front Left Wheel"


def test_build_sensor_analysis_falls_back_for_legacy_runs_without_snapshot() -> None:
    metadata = RunMetadata.create(
        run_id="legacy-run",
        start_time_utc="2026-01-01T00:00:00Z",
        sensor_model="ADXL345",
        raw_sample_rate_hz=800,
        feature_interval_s=0.5,
        fft_window_size_samples=1024,
        accel_scale_g_per_lsb=None,
        analysis_settings=AnalysisSettingsSnapshot(),
    )
    samples = [
        SensorFrame(
            run_id="legacy-run",
            timestamp_utc="2026-01-01T00:00:00Z",
            t_s=0.0,
            client_id="sensor-a",
            client_name="Legacy sample row",
            location="",
            sample_rate_hz=800,
            speed_kmh=None,
            gps_speed_kmh=None,
            speed_source="none",
            engine_rpm=None,
            engine_rpm_source="missing",
            gear=None,
            final_drive_ratio=None,
            accel_x_g=None,
            accel_y_g=None,
            accel_z_g=None,
            dominant_freq_hz=None,
            dominant_axis="combined",
            top_peaks=tuple(),
            vibration_strength_db=20.0,
            strength_bucket="l2",
            strength_peak_amp_g=0.1,
            strength_floor_amp_g=0.01,
            frames_dropped_total=0,
            queue_overflow_drops=0,
        )
    ]

    sensor_locations, connected_locations, sensor_intensity = build_sensor_analysis(
        samples=samples,
        language="en",
        per_sample_phases=[],
        metadata=metadata,
    )

    assert sensor_locations == ["Legacy sample row"]
    assert connected_locations == {"Legacy sample row"}
    assert sensor_intensity[0].location == "Legacy sample row"
