"""Focused tests for run metadata assembly."""

from __future__ import annotations

from vibesensor.domain import AnalysisSettingsSnapshot, CarOrderReferenceStatus, CarSnapshot
from vibesensor.shared.types.run_schema import RunCarMetadata
from vibesensor.use_cases.run.run_metadata_builder import build_run_metadata


def test_build_run_metadata_carries_active_car_override_provenance() -> None:
    metadata = build_run_metadata(
        run_id="run-1",
        start_time_utc="2026-04-25T00:00:00Z",
        analysis_settings_snapshot=AnalysisSettingsSnapshot(
            tire_width_mm=245.0,
            tire_aspect_pct=40.0,
            rim_in=18.0,
            final_drive_ratio=3.91,
            current_gear_ratio=0.82,
        ),
        sensor_model="fixture-sensor",
        firmware_version="1.2.3",
        default_sample_rate_hz=800,
        metrics_log_hz=10,
        fft_window_size_samples=1024,
        accel_scale_g_per_lsb=0.001,
        active_car_snapshot=CarSnapshot(
            car_id="car-1",
            name="Track Car",
            car_type="coupe",
            order_reference_status=CarOrderReferenceStatus(
                selection_source_status="manual_entry",
                tire_dimensions_confidence="user_confirmed",
                final_drive_ratio_confidence="user_confirmed",
                current_gear_ratio_confidence="user_confirmed",
                transmission_name="8-speed automatic",
                transmission_confidence="official_exact",
            ),
        ),
    )

    assert metadata.car == RunCarMetadata(
        car_id="car-1",
        name="Track Car",
        car_type="coupe",
        order_reference_status=CarOrderReferenceStatus(
            selection_source_status="manual_entry",
            tire_dimensions_confidence="user_confirmed",
            final_drive_ratio_confidence="user_confirmed",
            current_gear_ratio_confidence="user_confirmed",
            transmission_name="8-speed automatic",
            transmission_confidence="official_exact",
        ),
    )
