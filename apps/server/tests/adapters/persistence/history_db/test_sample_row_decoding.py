"""Low-level samples_v2 row encoding and decoding coverage."""

from __future__ import annotations

import pytest

from vibesensor.adapters.persistence.history_db._samples import (
    _V2_COL_OFFSET,
    _V2_COLUMNS,
    sample_to_v2_row,
    v2_row_to_sensor_frame,
)
from vibesensor.shared.boundaries.sensor_frames import (
    SensorFrameDecodeError,
    sensor_frame_from_mapping,
)
from vibesensor.shared.types.sensor_frame import SensorFrame


def _frame() -> SensorFrame:
    return sensor_frame_from_mapping(
        {
            "run_id": "run-1",
            "timestamp_utc": "2026-01-01T00:00:00Z",
            "t_s": 1.25,
            "analysis_window_start_us": 750000,
            "analysis_window_end_us": 1250000,
            "analysis_window_synced": True,
            "client_id": "client-1",
            "client_name": "Front left",
            "location": "front_left",
            "sample_rate_hz": 800,
            "speed_kmh": 42.5,
            "gps_speed_kmh": 43.0,
            "speed_source": "gps",
            "engine_rpm": 2100.0,
            "engine_rpm_source": "obd",
            "gear": 4.0,
            "final_drive_ratio": 3.55,
            "accel_x_g": 0.1,
            "accel_y_g": 0.2,
            "accel_z_g": 0.3,
            "dominant_freq_hz": 56.0,
            "dominant_axis": "x",
            "top_peaks": [{"hz": 56.0, "amp_g": 0.42}],
            "vibration_strength_db": 12.3,
            "strength_bucket": "moderate",
            "strength_peak_amp_g": 0.42,
            "strength_floor_amp_g": 0.02,
            "frames_dropped_total": 5,
            "queue_overflow_drops": 2,
        }
    )


def test_v2_row_to_sensor_frame_round_trips_typed_row() -> None:
    frame = _frame()
    row = (123, *sample_to_v2_row(frame.run_id, frame))
    assert v2_row_to_sensor_frame(row) == frame


def test_v2_row_to_sensor_frame_rejects_non_numeric_scalar_columns() -> None:
    frame = _frame()
    row = list((123, *sample_to_v2_row(frame.run_id, frame)))
    row[_V2_COL_OFFSET + _V2_COLUMNS.index("sample_rate_hz")] = "fast"

    with pytest.raises(SensorFrameDecodeError, match="sample_rate_hz"):
        v2_row_to_sensor_frame(tuple(row))
