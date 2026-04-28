"""Shared SensorFrame field ownership for JSON and storage-row adapters."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
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


type _MappingScalarDecoder = Callable[[object, bool, str], object]
type _RowScalarDecoder = Callable[[object, str], object]
type _RowScalarProjector = Callable[[object], object]


@dataclass(frozen=True, slots=True)
class _SensorFrameScalarFieldSpec:
    name: str
    decode_mapping: _MappingScalarDecoder
    decode_row: _RowScalarDecoder
    project_row: _RowScalarProjector


def _identity_row_projector(value: object) -> object:
    return value


def _float_row_projector(value: object) -> object:
    return _finite_or_none(cast(float | None, value))


def _bool_row_projector(value: object) -> object:
    return _bool_to_sqlite(cast(bool | None, value))


def _decode_mapping_float(
    value: object,
    *,
    strict: bool,
    source: str,
    field: str,
) -> float | None:
    if strict:
        return strict_optional_float(value, field=field, source=source)
    return optional_float(value, field=field, source=source)


def _decode_mapping_int(
    value: object,
    *,
    strict: bool,
    source: str,
    field: str,
) -> int | None:
    if strict:
        return strict_optional_int(value, field=field, source=source)
    return optional_int(value, field=field, source=source)


def _text_field(name: str) -> _SensorFrameScalarFieldSpec:
    def decode_mapping(value: object, strict: bool, source: str) -> object:
        del strict, source
        return _text_value(value)

    def decode_row(value: object, source: str) -> object:
        del source
        return _text_value(value)

    return _SensorFrameScalarFieldSpec(
        name=name,
        decode_mapping=decode_mapping,
        decode_row=decode_row,
        project_row=_identity_row_projector,
    )


def _float_field(name: str) -> _SensorFrameScalarFieldSpec:
    def decode_mapping(value: object, strict: bool, source: str) -> object:
        return _decode_mapping_float(value, strict=strict, source=source, field=name)

    def decode_row(value: object, source: str) -> object:
        return strict_optional_float(value, field=name, source=source)

    return _SensorFrameScalarFieldSpec(
        name=name,
        decode_mapping=decode_mapping,
        decode_row=decode_row,
        project_row=_float_row_projector,
    )


def _int_field(name: str) -> _SensorFrameScalarFieldSpec:
    def decode_mapping(value: object, strict: bool, source: str) -> object:
        return _decode_mapping_int(value, strict=strict, source=source, field=name)

    def decode_row(value: object, source: str) -> object:
        return strict_optional_int(value, field=name, source=source)

    return _SensorFrameScalarFieldSpec(
        name=name,
        decode_mapping=decode_mapping,
        decode_row=decode_row,
        project_row=_identity_row_projector,
    )


def _default_zero_int_field(name: str) -> _SensorFrameScalarFieldSpec:
    def decode_mapping(value: object, strict: bool, source: str) -> object:
        return _decode_mapping_int(value, strict=strict, source=source, field=name) or 0

    def decode_row(value: object, source: str) -> object:
        return strict_optional_int(value, field=name, source=source) or 0

    return _SensorFrameScalarFieldSpec(
        name=name,
        decode_mapping=decode_mapping,
        decode_row=decode_row,
        project_row=_identity_row_projector,
    )


def _bool_field(name: str) -> _SensorFrameScalarFieldSpec:
    def decode_mapping(value: object, strict: bool, source: str) -> object:
        return _decode_optional_bool(value, strict=strict, source=source, field=name)

    def decode_row(value: object, source: str) -> object:
        return _decode_optional_bool(value, strict=True, source=source, field=name)

    return _SensorFrameScalarFieldSpec(
        name=name,
        decode_mapping=decode_mapping,
        decode_row=decode_row,
        project_row=_bool_row_projector,
    )


def _strength_bucket_field(name: str) -> _SensorFrameScalarFieldSpec:
    def decode_mapping(value: object, strict: bool, source: str) -> object:
        del strict, source
        return _strength_bucket(value)

    def decode_row(value: object, source: str) -> object:
        del source
        return _strength_bucket(value)

    return _SensorFrameScalarFieldSpec(
        name=name,
        decode_mapping=decode_mapping,
        decode_row=decode_row,
        project_row=_identity_row_projector,
    )


_SENSOR_FRAME_SCALAR_FIELDS: tuple[_SensorFrameScalarFieldSpec, ...] = (
    _text_field("run_id"),
    _text_field("timestamp_utc"),
    _float_field("t_s"),
    _int_field("analysis_window_start_us"),
    _int_field("analysis_window_end_us"),
    _bool_field("analysis_window_synced"),
    _text_field("client_id"),
    _text_field("client_name"),
    _text_field("location"),
    _int_field("sample_rate_hz"),
    _float_field("speed_kmh"),
    _float_field("gps_speed_kmh"),
    _text_field("speed_source"),
    _float_field("engine_rpm"),
    _text_field("engine_rpm_source"),
    _float_field("gear"),
    _float_field("final_drive_ratio"),
    _float_field("accel_x_g"),
    _float_field("accel_y_g"),
    _float_field("accel_z_g"),
    _float_field("dominant_freq_hz"),
    _text_field("dominant_axis"),
    _float_field(_VIBRATION_STRENGTH_DB_KEY),
    _strength_bucket_field(_STRENGTH_BUCKET_KEY),
    _float_field("strength_peak_amp_g"),
    _float_field("strength_floor_amp_g"),
    _default_zero_int_field("frames_dropped_total"),
    _default_zero_int_field("queue_overflow_drops"),
)
SENSOR_FRAME_FIELD_NAMES: tuple[str, ...] = (
    *(field.name for field in _SENSOR_FRAME_SCALAR_FIELDS),
    _TOP_PEAKS_KEY,
)
_TOP_PEAKS_COLUMN_INDEX = len(_SENSOR_FRAME_SCALAR_FIELDS)
_SENSOR_FRAME_SCALAR_VALUES_FACTORY: Callable[..., SensorFrameScalarValues] = (
    SensorFrameScalarValues
)


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
    payload = cast(
        JsonObject,
        {field.name: getattr(frame, field.name) for field in _SENSOR_FRAME_SCALAR_FIELDS},
    )
    payload[_TOP_PEAKS_KEY] = cast(list[JsonValue], strength_peak_payloads(frame.top_peaks))
    return payload


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
    scalar_row_values = tuple(
        field.project_row(getattr(frame, field.name)) for field in _SENSOR_FRAME_SCALAR_FIELDS
    )
    return (
        *scalar_row_values,
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
    decoded_values = {
        field.name: field.decode_mapping(record.get(field.name), strict, source)
        for field in _SENSOR_FRAME_SCALAR_FIELDS
    }
    return _SENSOR_FRAME_SCALAR_VALUES_FACTORY(**decoded_values)


def _scalars_from_row(values: Sequence[object], *, source: str) -> SensorFrameScalarValues:
    decoded_values = {
        field.name: field.decode_row(values[index], source)
        for index, field in enumerate(_SENSOR_FRAME_SCALAR_FIELDS)
    }
    return _SENSOR_FRAME_SCALAR_VALUES_FACTORY(**decoded_values)


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
