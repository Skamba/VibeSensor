"""Boundary codecs for ordered storage-row SensorFrame payloads."""

from __future__ import annotations

import math
from collections.abc import Sequence

from vibesensor.shared.boundaries.strength_metrics_codec import strength_peak_payloads
from vibesensor.shared.json_utils import safe_json_dumps
from vibesensor.shared.types.sensor_frame import SensorFrame

from .sensor_frame_value_codec import (
    SensorFrameDecodeError,
    build_sensor_frame,
    strict_optional_float,
    strict_optional_int,
    strength_bucket,
    text_value,
    top_peaks_payload_from_row_value,
)

__all__ = [
    "SENSOR_FRAME_FIELD_NAMES",
    "sensor_frame_from_row",
    "sensor_frame_to_row_values",
    "sensor_frames_from_rows",
]

SENSOR_FRAME_FIELD_NAMES: tuple[str, ...] = (
    "run_id",
    "timestamp_utc",
    "t_s",
    "client_id",
    "client_name",
    "location",
    "sample_rate_hz",
    "speed_kmh",
    "gps_speed_kmh",
    "speed_source",
    "engine_rpm",
    "engine_rpm_source",
    "gear",
    "final_drive_ratio",
    "accel_x_g",
    "accel_y_g",
    "accel_z_g",
    "dominant_freq_hz",
    "dominant_axis",
    "vibration_strength_db",
    "strength_bucket",
    "strength_peak_amp_g",
    "strength_floor_amp_g",
    "frames_dropped_total",
    "queue_overflow_drops",
    "top_peaks",
)

_TOP_PEAKS_COLUMN_INDEX = len(SENSOR_FRAME_FIELD_NAMES) - 1
_ISFINITE = math.isfinite


def sensor_frame_from_row(
    row: Sequence[object],
    *,
    row_offset: int = 0,
    source: str = "sample row",
) -> SensorFrame:
    """Decode one ordered storage row into the canonical typed sample object."""

    expected_end = row_offset + len(SENSOR_FRAME_FIELD_NAMES)
    if len(row) < expected_end:
        raise SensorFrameDecodeError(
            source=source,
            field="row",
            detail=f"has {len(row)} column(s), expected at least {expected_end}",
        )
    values = row[row_offset:expected_end]
    top_peaks = top_peaks_payload_from_row_value(values[_TOP_PEAKS_COLUMN_INDEX], source=source)
    return build_sensor_frame(
        run_id=text_value(values[0]),
        timestamp_utc=text_value(values[1]),
        t_s=strict_optional_float(values[2], field="t_s", source=source),
        client_id=text_value(values[3]),
        client_name=text_value(values[4]),
        location=text_value(values[5]),
        sample_rate_hz=strict_optional_int(values[6], field="sample_rate_hz", source=source),
        speed_kmh=strict_optional_float(values[7], field="speed_kmh", source=source),
        gps_speed_kmh=strict_optional_float(values[8], field="gps_speed_kmh", source=source),
        speed_source=text_value(values[9]),
        engine_rpm=strict_optional_float(values[10], field="engine_rpm", source=source),
        engine_rpm_source=text_value(values[11]),
        gear=strict_optional_float(values[12], field="gear", source=source),
        final_drive_ratio=strict_optional_float(
            values[13],
            field="final_drive_ratio",
            source=source,
        ),
        accel_x_g=strict_optional_float(values[14], field="accel_x_g", source=source),
        accel_y_g=strict_optional_float(values[15], field="accel_y_g", source=source),
        accel_z_g=strict_optional_float(values[16], field="accel_z_g", source=source),
        dominant_freq_hz=strict_optional_float(
            values[17],
            field="dominant_freq_hz",
            source=source,
        ),
        dominant_axis=text_value(values[18]),
        vibration_strength_db=strict_optional_float(
            values[19],
            field="vibration_strength_db",
            source=source,
        ),
        strength_bucket=strength_bucket(values[20]),
        strength_peak_amp_g=strict_optional_float(
            values[21],
            field="strength_peak_amp_g",
            source=source,
        ),
        strength_floor_amp_g=strict_optional_float(
            values[22],
            field="strength_floor_amp_g",
            source=source,
        ),
        frames_dropped_total=(
            strict_optional_int(values[23], field="frames_dropped_total", source=source) or 0
        ),
        queue_overflow_drops=(
            strict_optional_int(values[24], field="queue_overflow_drops", source=source) or 0
        ),
        top_peaks=top_peaks,
    )


def sensor_frames_from_rows(rows: Sequence[Sequence[object]]) -> list[SensorFrame]:
    """Decode ordered rows into canonical typed sample objects."""

    return [sensor_frame_from_row(row) for row in rows]


def sensor_frame_to_row_values(frame: SensorFrame) -> tuple[object, ...]:
    """Encode one typed sample into flat ordered row values for storage."""

    top_peaks_payload = strength_peak_payloads(frame.top_peaks)
    return (
        frame.run_id,
        frame.timestamp_utc,
        _finite_or_none(frame.t_s),
        frame.client_id,
        frame.client_name,
        frame.location,
        frame.sample_rate_hz,
        _finite_or_none(frame.speed_kmh),
        _finite_or_none(frame.gps_speed_kmh),
        frame.speed_source,
        _finite_or_none(frame.engine_rpm),
        frame.engine_rpm_source,
        _finite_or_none(frame.gear),
        _finite_or_none(frame.final_drive_ratio),
        _finite_or_none(frame.accel_x_g),
        _finite_or_none(frame.accel_y_g),
        _finite_or_none(frame.accel_z_g),
        _finite_or_none(frame.dominant_freq_hz),
        frame.dominant_axis,
        _finite_or_none(frame.vibration_strength_db),
        frame.strength_bucket,
        _finite_or_none(frame.strength_peak_amp_g),
        _finite_or_none(frame.strength_floor_amp_g),
        frame.frames_dropped_total,
        frame.queue_overflow_drops,
        safe_json_dumps(top_peaks_payload) if top_peaks_payload else None,
    )


def _finite_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return value if _ISFINITE(value) else None
