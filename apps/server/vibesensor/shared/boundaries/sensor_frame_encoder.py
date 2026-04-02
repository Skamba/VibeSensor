"""Boundary encoders for typed SensorFrame payloads."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from vibesensor.shared.boundaries.strength_metrics_codec import strength_peak_payloads
from vibesensor.shared.types.json_types import JsonObject, JsonValue
from vibesensor.shared.types.sensor_frame import SensorFrame

__all__ = [
    "sensor_frame_to_json_object",
    "sensor_frames_to_json_objects",
]

_VIBRATION_STRENGTH_DB_KEY = "vibration_strength_db"
_STRENGTH_BUCKET_KEY = "strength_bucket"
_TOP_PEAKS_KEY = "top_peaks"


def sensor_frame_to_json_object(frame: SensorFrame) -> JsonObject:
    """Encode one typed sample for an explicit JSON boundary."""

    top_peaks = cast(list[JsonValue], strength_peak_payloads(frame.top_peaks))
    return {
        "run_id": frame.run_id,
        "timestamp_utc": frame.timestamp_utc,
        "t_s": frame.t_s,
        "client_id": frame.client_id,
        "client_name": frame.client_name,
        "location": frame.location,
        "sample_rate_hz": frame.sample_rate_hz,
        "speed_kmh": frame.speed_kmh,
        "gps_speed_kmh": frame.gps_speed_kmh,
        "speed_source": frame.speed_source,
        "engine_rpm": frame.engine_rpm,
        "engine_rpm_source": frame.engine_rpm_source,
        "gear": frame.gear,
        "final_drive_ratio": frame.final_drive_ratio,
        "accel_x_g": frame.accel_x_g,
        "accel_y_g": frame.accel_y_g,
        "accel_z_g": frame.accel_z_g,
        "dominant_freq_hz": frame.dominant_freq_hz,
        "dominant_axis": frame.dominant_axis,
        _TOP_PEAKS_KEY: top_peaks,
        _VIBRATION_STRENGTH_DB_KEY: frame.vibration_strength_db,
        _STRENGTH_BUCKET_KEY: frame.strength_bucket,
        "strength_peak_amp_g": frame.strength_peak_amp_g,
        "strength_floor_amp_g": frame.strength_floor_amp_g,
        "frames_dropped_total": frame.frames_dropped_total,
        "queue_overflow_drops": frame.queue_overflow_drops,
    }


def sensor_frames_to_json_objects(samples: Sequence[SensorFrame]) -> list[JsonObject]:
    """Serialize typed sensor frames only at an explicit JSON boundary."""

    return [sensor_frame_to_json_object(sample) for sample in samples]
