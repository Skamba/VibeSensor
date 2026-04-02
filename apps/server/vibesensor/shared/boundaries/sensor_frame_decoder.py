"""Boundary decoders for JSON/object-shaped SensorFrame payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from vibesensor.shared.types.sensor_frame import SensorFrame

from .sensor_frame_value_codec import (
    SensorFrameDecodeError,
    build_sensor_frame,
    optional_float,
    optional_int,
    strength_bucket,
    strict_optional_float,
    strict_optional_int,
    text_value,
    top_peaks_from_value,
)

__all__ = [
    "SensorFrameDecodeError",
    "sensor_frame_from_mapping",
    "sensor_frames_from_mappings",
]

_VIBRATION_STRENGTH_DB_KEY = "vibration_strength_db"
_STRENGTH_BUCKET_KEY = "strength_bucket"
_TOP_PEAKS_KEY = "top_peaks"


def sensor_frame_from_mapping(
    record: Mapping[str, object],
    *,
    strict: bool = False,
    source: str = "sample payload",
) -> SensorFrame:
    """Decode one raw sample payload into the canonical typed sample object."""

    float_decoder = strict_optional_float if strict else optional_float
    int_decoder = strict_optional_int if strict else optional_int
    return build_sensor_frame(
        run_id=text_value(record.get("run_id")),
        timestamp_utc=text_value(record.get("timestamp_utc")),
        t_s=float_decoder(record.get("t_s"), field="t_s", source=source),
        client_id=text_value(record.get("client_id")),
        client_name=text_value(record.get("client_name")),
        location=text_value(record.get("location")),
        sample_rate_hz=int_decoder(
            record.get("sample_rate_hz"),
            field="sample_rate_hz",
            source=source,
        ),
        speed_kmh=float_decoder(record.get("speed_kmh"), field="speed_kmh", source=source),
        gps_speed_kmh=float_decoder(
            record.get("gps_speed_kmh"),
            field="gps_speed_kmh",
            source=source,
        ),
        speed_source=text_value(record.get("speed_source")),
        engine_rpm=float_decoder(record.get("engine_rpm"), field="engine_rpm", source=source),
        engine_rpm_source=text_value(record.get("engine_rpm_source")),
        gear=float_decoder(record.get("gear"), field="gear", source=source),
        final_drive_ratio=float_decoder(
            record.get("final_drive_ratio"),
            field="final_drive_ratio",
            source=source,
        ),
        accel_x_g=float_decoder(record.get("accel_x_g"), field="accel_x_g", source=source),
        accel_y_g=float_decoder(record.get("accel_y_g"), field="accel_y_g", source=source),
        accel_z_g=float_decoder(record.get("accel_z_g"), field="accel_z_g", source=source),
        dominant_freq_hz=float_decoder(
            record.get("dominant_freq_hz"),
            field="dominant_freq_hz",
            source=source,
        ),
        dominant_axis=text_value(record.get("dominant_axis")),
        top_peaks=top_peaks_from_value(record.get(_TOP_PEAKS_KEY), strict=strict, source=source),
        vibration_strength_db=float_decoder(
            record.get(_VIBRATION_STRENGTH_DB_KEY),
            field=_VIBRATION_STRENGTH_DB_KEY,
            source=source,
        ),
        strength_bucket=strength_bucket(record.get(_STRENGTH_BUCKET_KEY)),
        strength_peak_amp_g=float_decoder(
            record.get("strength_peak_amp_g"),
            field="strength_peak_amp_g",
            source=source,
        ),
        strength_floor_amp_g=float_decoder(
            record.get("strength_floor_amp_g"),
            field="strength_floor_amp_g",
            source=source,
        ),
        frames_dropped_total=int_decoder(
            record.get("frames_dropped_total"),
            field="frames_dropped_total",
            source=source,
        )
        or 0,
        queue_overflow_drops=int_decoder(
            record.get("queue_overflow_drops"),
            field="queue_overflow_drops",
            source=source,
        )
        or 0,
    )


def sensor_frames_from_mappings(rows: Sequence[Mapping[str, object]]) -> list[SensorFrame]:
    """Decode raw object payloads into canonical typed sample objects."""

    return [sensor_frame_from_mapping(row) for row in rows]
