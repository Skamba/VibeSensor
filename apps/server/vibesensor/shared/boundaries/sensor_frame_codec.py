"""Boundary codecs for diagnostics sample rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from vibesensor.shared.boundaries.strength_metrics_codec import (
    strength_peak_payloads,
    strength_peaks_from_sequence,
)
from vibesensor.shared.json_utils import as_float_or_none, as_int_or_none
from vibesensor.shared.types.json_types import JsonObject, JsonValue
from vibesensor.shared.types.sensor_frame import SensorFrame

__all__ = [
    "sensor_frame_from_mapping",
    "sensor_frame_to_json_object",
    "sensor_frames_from_rows",
    "sensor_frames_to_json_objects",
]

_VIBRATION_STRENGTH_DB_KEY = "vibration_strength_db"
_STRENGTH_BUCKET_KEY = "strength_bucket"


def sensor_frame_from_mapping(record: Mapping[str, object]) -> SensorFrame:
    """Decode one raw sample row into the canonical typed sample object."""

    return SensorFrame(
        run_id=str(record.get("run_id", "")),
        timestamp_utc=str(record.get("timestamp_utc", "")),
        t_s=as_float_or_none(record.get("t_s")),
        client_id=str(record.get("client_id", "")),
        client_name=str(record.get("client_name", "")),
        location=str(record.get("location", "")),
        sample_rate_hz=as_int_or_none(record.get("sample_rate_hz")),
        speed_kmh=as_float_or_none(record.get("speed_kmh")),
        gps_speed_kmh=as_float_or_none(record.get("gps_speed_kmh")),
        speed_source=str(record.get("speed_source", "")),
        engine_rpm=as_float_or_none(record.get("engine_rpm")),
        engine_rpm_source=str(record.get("engine_rpm_source", "")),
        gear=as_float_or_none(record.get("gear")),
        final_drive_ratio=as_float_or_none(record.get("final_drive_ratio")),
        accel_x_g=as_float_or_none(record.get("accel_x_g")),
        accel_y_g=as_float_or_none(record.get("accel_y_g")),
        accel_z_g=as_float_or_none(record.get("accel_z_g")),
        dominant_freq_hz=as_float_or_none(record.get("dominant_freq_hz")),
        dominant_axis=str(record.get("dominant_axis", "")),
        top_peaks=strength_peaks_from_sequence(record.get("top_peaks"), max_items=10),
        vibration_strength_db=as_float_or_none(record.get(_VIBRATION_STRENGTH_DB_KEY)),
        strength_bucket=_strength_bucket(record),
        strength_peak_amp_g=as_float_or_none(record.get("strength_peak_amp_g")),
        strength_floor_amp_g=as_float_or_none(record.get("strength_floor_amp_g")),
        frames_dropped_total=as_int_or_none(record.get("frames_dropped_total")) or 0,
        queue_overflow_drops=as_int_or_none(record.get("queue_overflow_drops")) or 0,
    )


def sensor_frames_from_rows(rows: Sequence[Mapping[str, object]]) -> list[SensorFrame]:
    """Decode raw boundary rows into canonical typed sample objects."""

    return [sensor_frame_from_mapping(row) for row in rows]


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
        "top_peaks": top_peaks,
        _VIBRATION_STRENGTH_DB_KEY: frame.vibration_strength_db,
        _STRENGTH_BUCKET_KEY: frame.strength_bucket,
        "strength_peak_amp_g": frame.strength_peak_amp_g,
        "strength_floor_amp_g": frame.strength_floor_amp_g,
        "frames_dropped_total": frame.frames_dropped_total,
        "queue_overflow_drops": frame.queue_overflow_drops,
    }


def sensor_frames_to_json_objects(samples: Sequence[SensorFrame]) -> list[JsonObject]:
    """Serialize typed sensor frames at an explicit JSON boundary."""

    return [sensor_frame_to_json_object(sample) for sample in samples]


def _strength_bucket(record: Mapping[str, object]) -> str | None:
    raw_bucket = record.get(_STRENGTH_BUCKET_KEY)
    return str(raw_bucket) if raw_bucket not in (None, "") else None
