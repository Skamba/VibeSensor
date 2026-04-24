"""Shared SensorFrame field ownership for JSON and storage-row adapters."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from vibesensor.shared.boundaries.codecs.scalars import optional_float, optional_int
from vibesensor.shared.boundaries.codecs.sensor_frame_values import (
    SensorFrameDecodeError,
    strict_optional_float,
    strict_optional_int,
)
from vibesensor.shared.json_utils import safe_json_dumps, safe_json_loads
from vibesensor.shared.types.json_types import JsonArray, JsonObject, JsonValue, is_json_array
from vibesensor.shared.types.sensor_frame import SensorFrame

from ..codecs import strength_peak_payloads, strength_peaks_from_sequence

__all__ = [
    "SENSOR_FRAME_FIELD_NAMES",
    "sensor_frame_from_mapping_payload",
    "sensor_frame_from_row_payload",
    "sensor_frame_to_mapping_payload",
    "sensor_frame_to_row_payload",
]

_VIBRATION_STRENGTH_DB_KEY = "vibration_strength_db"
_STRENGTH_BUCKET_KEY = "strength_bucket"
_TOP_PEAKS_KEY = "top_peaks"
_SENSOR_FRAME_SCALAR_FIELD_NAMES: tuple[str, ...] = (
    "run_id",
    "timestamp_utc",
    "t_s",
    "analysis_window_start_us",
    "analysis_window_end_us",
    "analysis_window_synced",
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
    _VIBRATION_STRENGTH_DB_KEY,
    _STRENGTH_BUCKET_KEY,
    "strength_peak_amp_g",
    "strength_floor_amp_g",
    "frames_dropped_total",
    "queue_overflow_drops",
)
SENSOR_FRAME_FIELD_NAMES: tuple[str, ...] = (*_SENSOR_FRAME_SCALAR_FIELD_NAMES, _TOP_PEAKS_KEY)
_TOP_PEAKS_COLUMN_INDEX = len(SENSOR_FRAME_FIELD_NAMES) - 1
_ISFINITE = math.isfinite


@dataclass(frozen=True, slots=True)
class SensorFrameScalarValues:
    run_id: str
    timestamp_utc: str
    t_s: float | None
    analysis_window_start_us: int | None
    analysis_window_end_us: int | None
    analysis_window_synced: bool | None
    client_id: str
    client_name: str
    location: str
    sample_rate_hz: int | None
    speed_kmh: float | None
    gps_speed_kmh: float | None
    speed_source: str
    engine_rpm: float | None
    engine_rpm_source: str
    gear: float | None
    final_drive_ratio: float | None
    accel_x_g: float | None
    accel_y_g: float | None
    accel_z_g: float | None
    dominant_freq_hz: float | None
    dominant_axis: str
    vibration_strength_db: float | None
    strength_bucket: str | None
    strength_peak_amp_g: float | None
    strength_floor_amp_g: float | None
    frames_dropped_total: int
    queue_overflow_drops: int


def sensor_frame_from_mapping_payload(
    record: Mapping[str, object],
    *,
    strict: bool = False,
    source: str = "sample payload",
) -> SensorFrame:
    return _build_sensor_frame(
        _scalars_from_mapping(
            record,
            strict=strict,
            source=source,
        ),
        top_peaks=_top_peaks_from_mapping_value(
            record.get(_TOP_PEAKS_KEY),
            strict=strict,
            source=source,
        ),
    )


def sensor_frame_to_mapping_payload(frame: SensorFrame) -> JsonObject:
    return {
        "run_id": frame.run_id,
        "timestamp_utc": frame.timestamp_utc,
        "t_s": frame.t_s,
        "analysis_window_start_us": frame.analysis_window_start_us,
        "analysis_window_end_us": frame.analysis_window_end_us,
        "analysis_window_synced": frame.analysis_window_synced,
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
        _TOP_PEAKS_KEY: cast(list[JsonValue], strength_peak_payloads(frame.top_peaks)),
        _VIBRATION_STRENGTH_DB_KEY: frame.vibration_strength_db,
        _STRENGTH_BUCKET_KEY: frame.strength_bucket,
        "strength_peak_amp_g": frame.strength_peak_amp_g,
        "strength_floor_amp_g": frame.strength_floor_amp_g,
        "frames_dropped_total": frame.frames_dropped_total,
        "queue_overflow_drops": frame.queue_overflow_drops,
    }


def sensor_frame_from_row_payload(
    row: Sequence[object],
    *,
    row_offset: int = 0,
    source: str = "sample row",
) -> SensorFrame:
    expected_end = row_offset + len(SENSOR_FRAME_FIELD_NAMES)
    if len(row) < expected_end:
        raise SensorFrameDecodeError(
            source=source,
            field="row",
            detail=f"has {len(row)} column(s), expected at least {expected_end}",
        )
    values = row[row_offset:expected_end]
    return _build_sensor_frame(
        _scalars_from_row(values, source=source),
        top_peaks=_top_peaks_from_row_value(values[_TOP_PEAKS_COLUMN_INDEX], source=source),
    )


def sensor_frame_to_row_payload(frame: SensorFrame) -> tuple[object, ...]:
    top_peaks_payload = strength_peak_payloads(frame.top_peaks)
    return (
        frame.run_id,
        frame.timestamp_utc,
        _finite_or_none(frame.t_s),
        frame.analysis_window_start_us,
        frame.analysis_window_end_us,
        _bool_to_sqlite(frame.analysis_window_synced),
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


def _build_sensor_frame(values: SensorFrameScalarValues, *, top_peaks: object) -> SensorFrame:
    return SensorFrame(
        run_id=values.run_id,
        timestamp_utc=values.timestamp_utc,
        t_s=values.t_s,
        analysis_window_start_us=values.analysis_window_start_us,
        analysis_window_end_us=values.analysis_window_end_us,
        analysis_window_synced=values.analysis_window_synced,
        client_id=values.client_id,
        client_name=values.client_name,
        location=values.location,
        sample_rate_hz=values.sample_rate_hz,
        speed_kmh=values.speed_kmh,
        gps_speed_kmh=values.gps_speed_kmh,
        speed_source=values.speed_source,
        engine_rpm=values.engine_rpm,
        engine_rpm_source=values.engine_rpm_source,
        gear=values.gear,
        final_drive_ratio=values.final_drive_ratio,
        accel_x_g=values.accel_x_g,
        accel_y_g=values.accel_y_g,
        accel_z_g=values.accel_z_g,
        dominant_freq_hz=values.dominant_freq_hz,
        dominant_axis=values.dominant_axis,
        top_peaks=strength_peaks_from_sequence(top_peaks, max_items=10),
        vibration_strength_db=values.vibration_strength_db,
        strength_bucket=values.strength_bucket,
        strength_peak_amp_g=values.strength_peak_amp_g,
        strength_floor_amp_g=values.strength_floor_amp_g,
        frames_dropped_total=values.frames_dropped_total,
        queue_overflow_drops=values.queue_overflow_drops,
    )


def _scalars_from_mapping(
    record: Mapping[str, object],
    *,
    strict: bool,
    source: str,
) -> SensorFrameScalarValues:
    def decode_float(value: object, *, field: str) -> float | None:
        if strict:
            return strict_optional_float(value, field=field, source=source)
        return optional_float(value, field=field, source=source)

    def decode_int(value: object, *, field: str) -> int | None:
        if strict:
            return strict_optional_int(value, field=field, source=source)
        return optional_int(value, field=field, source=source)

    return SensorFrameScalarValues(
        run_id=_text_value(record.get("run_id")),
        timestamp_utc=_text_value(record.get("timestamp_utc")),
        t_s=decode_float(record.get("t_s"), field="t_s"),
        analysis_window_start_us=decode_int(
            record.get("analysis_window_start_us"),
            field="analysis_window_start_us",
        ),
        analysis_window_end_us=decode_int(
            record.get("analysis_window_end_us"),
            field="analysis_window_end_us",
        ),
        analysis_window_synced=_decode_optional_bool(
            record.get("analysis_window_synced"),
            strict=strict,
            source=source,
            field="analysis_window_synced",
        ),
        client_id=_text_value(record.get("client_id")),
        client_name=_text_value(record.get("client_name")),
        location=_text_value(record.get("location")),
        sample_rate_hz=decode_int(record.get("sample_rate_hz"), field="sample_rate_hz"),
        speed_kmh=decode_float(record.get("speed_kmh"), field="speed_kmh"),
        gps_speed_kmh=decode_float(record.get("gps_speed_kmh"), field="gps_speed_kmh"),
        speed_source=_text_value(record.get("speed_source")),
        engine_rpm=decode_float(record.get("engine_rpm"), field="engine_rpm"),
        engine_rpm_source=_text_value(record.get("engine_rpm_source")),
        gear=decode_float(record.get("gear"), field="gear"),
        final_drive_ratio=decode_float(
            record.get("final_drive_ratio"),
            field="final_drive_ratio",
        ),
        accel_x_g=decode_float(record.get("accel_x_g"), field="accel_x_g"),
        accel_y_g=decode_float(record.get("accel_y_g"), field="accel_y_g"),
        accel_z_g=decode_float(record.get("accel_z_g"), field="accel_z_g"),
        dominant_freq_hz=decode_float(record.get("dominant_freq_hz"), field="dominant_freq_hz"),
        dominant_axis=_text_value(record.get("dominant_axis")),
        vibration_strength_db=decode_float(
            record.get(_VIBRATION_STRENGTH_DB_KEY),
            field=_VIBRATION_STRENGTH_DB_KEY,
        ),
        strength_bucket=_strength_bucket(record.get(_STRENGTH_BUCKET_KEY)),
        strength_peak_amp_g=decode_float(
            record.get("strength_peak_amp_g"),
            field="strength_peak_amp_g",
        ),
        strength_floor_amp_g=decode_float(
            record.get("strength_floor_amp_g"),
            field="strength_floor_amp_g",
        ),
        frames_dropped_total=decode_int(
            record.get("frames_dropped_total"),
            field="frames_dropped_total",
        )
        or 0,
        queue_overflow_drops=decode_int(
            record.get("queue_overflow_drops"),
            field="queue_overflow_drops",
        )
        or 0,
    )


def _scalars_from_row(values: Sequence[object], *, source: str) -> SensorFrameScalarValues:
    return SensorFrameScalarValues(
        run_id=_text_value(values[0]),
        timestamp_utc=_text_value(values[1]),
        t_s=strict_optional_float(values[2], field="t_s", source=source),
        analysis_window_start_us=strict_optional_int(
            values[3],
            field="analysis_window_start_us",
            source=source,
        ),
        analysis_window_end_us=strict_optional_int(
            values[4],
            field="analysis_window_end_us",
            source=source,
        ),
        analysis_window_synced=_decode_optional_bool(
            values[5],
            strict=True,
            source=source,
            field="analysis_window_synced",
        ),
        client_id=_text_value(values[6]),
        client_name=_text_value(values[7]),
        location=_text_value(values[8]),
        sample_rate_hz=strict_optional_int(values[9], field="sample_rate_hz", source=source),
        speed_kmh=strict_optional_float(values[10], field="speed_kmh", source=source),
        gps_speed_kmh=strict_optional_float(values[11], field="gps_speed_kmh", source=source),
        speed_source=_text_value(values[12]),
        engine_rpm=strict_optional_float(values[13], field="engine_rpm", source=source),
        engine_rpm_source=_text_value(values[14]),
        gear=strict_optional_float(values[15], field="gear", source=source),
        final_drive_ratio=strict_optional_float(
            values[16],
            field="final_drive_ratio",
            source=source,
        ),
        accel_x_g=strict_optional_float(values[17], field="accel_x_g", source=source),
        accel_y_g=strict_optional_float(values[18], field="accel_y_g", source=source),
        accel_z_g=strict_optional_float(values[19], field="accel_z_g", source=source),
        dominant_freq_hz=strict_optional_float(
            values[20],
            field="dominant_freq_hz",
            source=source,
        ),
        dominant_axis=_text_value(values[21]),
        vibration_strength_db=strict_optional_float(
            values[22],
            field=_VIBRATION_STRENGTH_DB_KEY,
            source=source,
        ),
        strength_bucket=_strength_bucket(values[23]),
        strength_peak_amp_g=strict_optional_float(
            values[24],
            field="strength_peak_amp_g",
            source=source,
        ),
        strength_floor_amp_g=strict_optional_float(
            values[25],
            field="strength_floor_amp_g",
            source=source,
        ),
        frames_dropped_total=(
            strict_optional_int(values[26], field="frames_dropped_total", source=source) or 0
        ),
        queue_overflow_drops=(
            strict_optional_int(values[27], field="queue_overflow_drops", source=source) or 0
        ),
    )


def _bool_to_sqlite(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0


def _decode_optional_bool(
    value: object,
    *,
    strict: bool,
    source: str,
    field: str,
) -> bool | None:
    if value in (None, ""):
        return None
    decoded = (
        strict_optional_int(value, field=field, source=source)
        if strict
        else optional_int(value, field=field, source=source)
    )
    if decoded is None:
        return None
    return bool(decoded)


def _text_value(value: object) -> str:
    return str(value or "")


def _strength_bucket(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _top_peaks_from_mapping_value(
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


def _top_peaks_from_row_value(value: object, *, source: str) -> JsonArray:
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


def _finite_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return value if _ISFINITE(value) else None
