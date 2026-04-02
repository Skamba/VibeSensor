"""Boundary codecs for diagnostics samples."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import cast

from vibesensor.shared.boundaries.strength_metrics_codec import (
    strength_peak_payloads,
    strength_peaks_from_sequence,
)
from vibesensor.shared.json_utils import as_float_or_none, as_int_or_none, safe_json_loads
from vibesensor.shared.types.json_types import JsonArray, JsonObject, JsonValue, is_json_array
from vibesensor.shared.types.sensor_frame import SensorFrame

__all__ = [
    "SENSOR_FRAME_FIELD_NAMES",
    "SensorFrameDecodeError",
    "sensor_frame_from_mapping",
    "sensor_frame_from_row",
    "sensor_frame_to_json_object",
    "sensor_frames_from_rows",
    "sensor_frames_to_json_objects",
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

_VIBRATION_STRENGTH_DB_KEY = "vibration_strength_db"
_STRENGTH_BUCKET_KEY = "strength_bucket"
_TOP_PEAKS_KEY = "top_peaks"
_OPTIONAL_FLOAT_FIELDS: frozenset[str] = frozenset(
    {
        "t_s",
        "speed_kmh",
        "gps_speed_kmh",
        "engine_rpm",
        "gear",
        "final_drive_ratio",
        "accel_x_g",
        "accel_y_g",
        "accel_z_g",
        "dominant_freq_hz",
        _VIBRATION_STRENGTH_DB_KEY,
        "strength_peak_amp_g",
        "strength_floor_amp_g",
    },
)
_OPTIONAL_INT_FIELDS: frozenset[str] = frozenset(
    {"sample_rate_hz", "frames_dropped_total", "queue_overflow_drops"},
)


class SensorFrameDecodeError(ValueError):
    """Raised when a raw boundary sample cannot be decoded to ``SensorFrame``."""

    def __init__(self, *, source: str, field: str, detail: str) -> None:
        super().__init__(f"{source}: {field} {detail}")
        self.source = source
        self.field = field
        self.detail = detail


def sensor_frame_from_mapping(
    record: Mapping[str, object],
    *,
    strict: bool = False,
    source: str = "sample payload",
) -> SensorFrame:
    """Decode one raw sample row into the canonical typed sample object."""

    float_decoder = _strict_optional_float if strict else _optional_float
    int_decoder = _strict_optional_int if strict else _optional_int
    return _build_sensor_frame(
        run_id=_text_value(record.get("run_id")),
        timestamp_utc=_text_value(record.get("timestamp_utc")),
        t_s=float_decoder(record.get("t_s"), field="t_s", source=source),
        client_id=_text_value(record.get("client_id")),
        client_name=_text_value(record.get("client_name")),
        location=_text_value(record.get("location")),
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
        speed_source=_text_value(record.get("speed_source")),
        engine_rpm=float_decoder(record.get("engine_rpm"), field="engine_rpm", source=source),
        engine_rpm_source=_text_value(record.get("engine_rpm_source")),
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
        dominant_axis=_text_value(record.get("dominant_axis")),
        top_peaks=_top_peaks_from_value(record.get(_TOP_PEAKS_KEY), strict=strict, source=source),
        vibration_strength_db=float_decoder(
            record.get(_VIBRATION_STRENGTH_DB_KEY),
            field=_VIBRATION_STRENGTH_DB_KEY,
            source=source,
        ),
        strength_bucket=_strength_bucket(record),
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


def sensor_frames_from_rows(rows: Sequence[Mapping[str, object]]) -> list[SensorFrame]:
    """Decode raw boundary rows into canonical typed sample objects."""

    return [sensor_frame_from_mapping(row) for row in rows]


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
    record = dict(
        zip(
            SENSOR_FRAME_FIELD_NAMES,
            row[row_offset:expected_end],
            strict=True,
        ),
    )
    record[_TOP_PEAKS_KEY] = _top_peaks_payload_from_row_value(
        record.get(_TOP_PEAKS_KEY),
        source=source,
    )
    return sensor_frame_from_mapping(record, strict=True, source=source)


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


def _build_sensor_frame(
    *,
    run_id: str,
    timestamp_utc: str,
    t_s: float | None,
    client_id: str,
    client_name: str,
    location: str,
    sample_rate_hz: int | None,
    speed_kmh: float | None,
    gps_speed_kmh: float | None,
    speed_source: str,
    engine_rpm: float | None,
    engine_rpm_source: str,
    gear: float | None,
    final_drive_ratio: float | None,
    accel_x_g: float | None,
    accel_y_g: float | None,
    accel_z_g: float | None,
    dominant_freq_hz: float | None,
    dominant_axis: str,
    top_peaks: tuple[object, ...],
    vibration_strength_db: float | None,
    strength_bucket: str | None,
    strength_peak_amp_g: float | None,
    strength_floor_amp_g: float | None,
    frames_dropped_total: int,
    queue_overflow_drops: int,
) -> SensorFrame:
    return SensorFrame(
        run_id=run_id,
        timestamp_utc=timestamp_utc,
        t_s=t_s,
        client_id=client_id,
        client_name=client_name,
        location=location,
        sample_rate_hz=sample_rate_hz,
        speed_kmh=speed_kmh,
        gps_speed_kmh=gps_speed_kmh,
        speed_source=speed_source,
        engine_rpm=engine_rpm,
        engine_rpm_source=engine_rpm_source,
        gear=gear,
        final_drive_ratio=final_drive_ratio,
        accel_x_g=accel_x_g,
        accel_y_g=accel_y_g,
        accel_z_g=accel_z_g,
        dominant_freq_hz=dominant_freq_hz,
        dominant_axis=dominant_axis,
        top_peaks=strength_peaks_from_sequence(top_peaks, max_items=10),
        vibration_strength_db=vibration_strength_db,
        strength_bucket=strength_bucket,
        strength_peak_amp_g=strength_peak_amp_g,
        strength_floor_amp_g=strength_floor_amp_g,
        frames_dropped_total=frames_dropped_total,
        queue_overflow_drops=queue_overflow_drops,
    )


def _text_value(value: object) -> str:
    return str(value or "")


def _optional_float(value: object, *, field: str, source: str) -> float | None:
    del field, source
    return as_float_or_none(value)


def _strict_optional_float(value: object, *, field: str, source: str) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise SensorFrameDecodeError(
            source=source,
            field=field,
            detail="expected float-compatible value, got bool",
        )
    if not isinstance(value, int | float | str):
        raise SensorFrameDecodeError(
            source=source,
            field=field,
            detail=f"expected float-compatible value, got {type(value).__name__}",
        )
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise SensorFrameDecodeError(
            source=source,
            field=field,
            detail=f"expected float-compatible value, got {type(value).__name__}",
        ) from exc
    return numeric if math.isfinite(numeric) else None


def _optional_int(value: object, *, field: str, source: str) -> int | None:
    del field, source
    return as_int_or_none(value)


def _strict_optional_int(value: object, *, field: str, source: str) -> int | None:
    numeric = _strict_optional_float(value, field=field, source=source)
    if numeric is None:
        return None
    if numeric.is_integer():
        return int(numeric)
    raise SensorFrameDecodeError(
        source=source,
        field=field,
        detail=f"expected integer-compatible value, got {numeric}",
    )


def _top_peaks_from_value(
    value: object,
    *,
    strict: bool,
    source: str,
) -> tuple[JsonObject, ...] | tuple[object, ...]:
    if value in (None, "", ()):
        return ()
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        if strict:
            raise SensorFrameDecodeError(
                source=source,
                field=_TOP_PEAKS_KEY,
                detail=f"expected peak sequence, got {type(value).__name__}",
            )
        return ()
    return tuple(value)


def _top_peaks_payload_from_row_value(value: object, *, source: str) -> JsonArray:
    if value in (None, ""):
        return []
    parsed = safe_json_loads(str(value), context=f"{source} {_TOP_PEAKS_KEY}")
    if parsed is None:
        raise SensorFrameDecodeError(
            source=source,
            field=_TOP_PEAKS_KEY,
            detail="contains invalid JSON",
        )
    if not is_json_array(parsed):
        raise SensorFrameDecodeError(
            source=source,
            field=_TOP_PEAKS_KEY,
            detail=f"expected JSON array, got {type(parsed).__name__}",
        )
    return parsed
