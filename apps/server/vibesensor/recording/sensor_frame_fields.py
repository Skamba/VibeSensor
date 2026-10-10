"""Shared SensorFrame field ownership for JSON and storage-row adapters."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, fields
from typing import cast

from vibesensor.common.json_types import JsonArray, JsonObject, JsonValue, is_json_array
from vibesensor.common.json_utils import safe_json_dumps, safe_json_loads
from vibesensor.common.scalars import float_or, optional_float, optional_int
from vibesensor.domain.strength_metrics import StrengthPeak
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.recording.sensor_frame_values import (
    SensorFrameDecodeError,
    strict_optional_float,
    strict_optional_int,
)
from vibesensor.recording.strength_metrics_codec import (
    stored_strength_peak_amps,
    stored_strength_peaks,
    strength_peak_payloads,
    strength_peaks_from_sequence,
)

__all__ = [
    "SENSOR_FRAME_FIELD_NAMES",
    "sensor_frame_top_peak_amp_from_row_value",
    "sensor_frame_from_mapping_payload",
    "sensor_frame_from_row_payload",
    "sensor_frames_from_canonical_rows",
    "storage_float_column",
    "storage_top_peak_amp_column",
    "sensor_frame_to_mapping_payload",
    "sensor_frame_to_row_payload",
]

# A row keeps at most this many of its stored peaks.
_MAX_TOP_PEAKS = 10

_VIBRATION_STRENGTH_DB_KEY = "vibration_strength_db"
_STRENGTH_BUCKET_KEY = "strength_bucket"
_TOP_PEAKS_KEY = "top_peaks"
_ISFINITE = math.isfinite
_INF = math.inf
# Integers a float carries exactly; the general row decode goes through float.
_EXACT_INT_LIMIT = 2**53
_NONE_TYPE = type(None)
_FLOAT_COLUMN_TYPES = frozenset({float, _NONE_TYPE})
_INT_COLUMN_TYPES = frozenset({int, _NONE_TYPE})


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
# Decodes one stored column of a batch of rows, or returns None when a value is
# not of the column's stored type (the batch is then decoded row by row).
type _ColumnDecoder = Callable[[Sequence[object]], Sequence[object] | None]


@dataclass(frozen=True, slots=True)
class _SensorFrameScalarFieldSpec:
    name: str
    decode_mapping: _MappingScalarDecoder
    decode_row: _RowScalarDecoder
    project_row: _RowScalarProjector
    decode_column: _ColumnDecoder


def _identity_row_projector(value: object) -> object:
    return value


def _float_row_projector(value: object) -> object:
    return _finite_or_none(cast(float | None, value))


def _bool_row_projector(value: object) -> object:
    return _bool_to_sqlite(cast(bool | None, value))


def storage_float_column(values: Sequence[object]) -> list[float | None] | None:
    """A stored float column as ``strict_optional_float`` decodes it, or None.

    None when a value is neither a float nor NULL; non-finite floats become None.
    """
    if not set(map(type, values)) <= _FLOAT_COLUMN_TYPES:
        return None
    floats = cast("Sequence[float | None]", values)
    return [value if value is not None and -_INF < value < _INF else None for value in floats]


def _storage_int_column(values: Sequence[object]) -> list[int | None] | None:
    """A stored integer column as ``strict_optional_int`` decodes it, or None."""
    if not set(map(type, values)) <= _INT_COLUMN_TYPES:
        return None
    present = [cast(int, value) for value in values if value is not None]
    if present and (min(present) < -_EXACT_INT_LIMIT or max(present) > _EXACT_INT_LIMIT):
        return None
    return cast(list[int | None], list(values))


def _text_column(values: Sequence[object]) -> list[object]:
    return [value if type(value) is str else _text_value(value) for value in values]


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
        decode_column=_text_column,
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
        decode_column=storage_float_column,
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
        decode_column=_storage_int_column,
    )


def _default_zero_int_field(name: str) -> _SensorFrameScalarFieldSpec:
    def decode_mapping(value: object, strict: bool, source: str) -> object:
        return _decode_mapping_int(value, strict=strict, source=source, field=name) or 0

    def decode_row(value: object, source: str) -> object:
        return strict_optional_int(value, field=name, source=source) or 0

    def decode_column(values: Sequence[object]) -> list[object] | None:
        decoded = _storage_int_column(values)
        return None if decoded is None else [value or 0 for value in decoded]

    return _SensorFrameScalarFieldSpec(
        name=name,
        decode_mapping=decode_mapping,
        decode_row=decode_row,
        project_row=_identity_row_projector,
        decode_column=decode_column,
    )


def _bool_field(name: str) -> _SensorFrameScalarFieldSpec:
    def decode_mapping(value: object, strict: bool, source: str) -> object:
        return _decode_optional_bool(value, strict=strict, source=source, field=name)

    def decode_row(value: object, source: str) -> object:
        return _decode_optional_bool(value, strict=True, source=source, field=name)

    def decode_column(values: Sequence[object]) -> list[object] | None:
        decoded = _storage_int_column(values)
        return None if decoded is None else [None if v is None else v != 0 for v in decoded]

    return _SensorFrameScalarFieldSpec(
        name=name,
        decode_mapping=decode_mapping,
        decode_row=decode_row,
        project_row=_bool_row_projector,
        decode_column=decode_column,
    )


def _strength_bucket_field(name: str) -> _SensorFrameScalarFieldSpec:
    def decode_mapping(value: object, strict: bool, source: str) -> object:
        del strict, source
        return _strength_bucket(value)

    def decode_row(value: object, source: str) -> object:
        del source
        return _strength_bucket(value)

    def decode_column(values: Sequence[object]) -> list[object]:
        return [_strength_bucket(value) for value in values]

    return _SensorFrameScalarFieldSpec(
        name=name,
        decode_mapping=decode_mapping,
        decode_row=decode_row,
        project_row=_identity_row_projector,
        decode_column=decode_column,
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
# SensorFrame's positional argument order, by stored column index.
_SENSOR_FRAME_ARG_COLUMNS: tuple[int, ...] = tuple(
    SENSOR_FRAME_FIELD_NAMES.index(field.name)
    for field in fields(SensorFrame)
    if field.name in SENSOR_FRAME_FIELD_NAMES
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
        top_peaks=_strength_peaks(
            _top_peaks_from_mapping_value(
                record.get(_TOP_PEAKS_KEY),
                strict=strict,
                source=source,
            )
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
        top_peaks=_strength_peaks(
            _top_peaks_from_row_value(values[_TOP_PEAKS_COLUMN_INDEX], source=source)
        ),
    )


def sensor_frames_from_canonical_rows(
    rows: Sequence[Sequence[object]],
    *,
    row_offset: int = 0,
) -> list[SensorFrame] | None:
    """Decode a batch of storage rows column by column, or None.

    The frames ``sensor_frame_from_row_payload`` decodes from each row, built a
    column at a time. None when a value is not of its column's stored type or a
    ``top_peaks`` value is not a well-formed peak list: decode those rows one
    at a time, which coerces or rejects such values.
    """
    if not rows:
        return []
    expected_end = row_offset + len(SENSOR_FRAME_FIELD_NAMES)
    if any(len(row) < expected_end for row in rows):
        return None
    stored = list(zip(*rows, strict=False))[row_offset:expected_end]
    columns: list[Sequence[object]] = []
    for spec, values in zip(_SENSOR_FRAME_SCALAR_FIELDS, stored, strict=False):
        decoded = spec.decode_column(values)
        if decoded is None:
            return None
        columns.append(decoded)
    top_peaks = _storage_top_peaks_column(stored[_TOP_PEAKS_COLUMN_INDEX])
    if top_peaks is None:
        return None
    columns.append(top_peaks)
    return [
        SensorFrame(*args)
        for args in zip(*(columns[index] for index in _SENSOR_FRAME_ARG_COLUMNS), strict=True)
    ]


def sensor_frame_to_row_payload(frame: SensorFrame) -> tuple[object, ...]:
    top_peaks_payload = strength_peak_payloads(frame.top_peaks)
    scalar_row_values = tuple(
        field.project_row(getattr(frame, field.name)) for field in _SENSOR_FRAME_SCALAR_FIELDS
    )
    return (
        *scalar_row_values,
        safe_json_dumps(top_peaks_payload) if top_peaks_payload else None,
    )


def sensor_frame_top_peak_amp_from_row_value(
    value: object,
    *,
    source: str = "sample row",
) -> float | None:
    """The largest amplitude of the peaks a full row decode keeps from a ``top_peaks`` column.

    The same peaks as ``_strength_peaks`` keeps (the first ``_MAX_TOP_PEAKS``
    objects, valid ones only), without building them: a long drive's rows are
    all read this way to pick the ones analysed.
    """
    largest: float | None = None
    for item in _top_peaks_from_row_value(value, source=source)[:_MAX_TOP_PEAKS]:
        if not isinstance(item, Mapping):
            continue
        amp = float_or(item.get("amp"))
        if float_or(item.get("hz")) > 0.0 and amp > 0.0 and (largest is None or amp > largest):
            largest = amp
    return largest


def _storage_top_peaks_column(
    values: Sequence[object],
) -> list[tuple[StrengthPeak, ...]] | None:
    """Each stored ``top_peaks`` value's kept peaks, or None if one is not well-formed."""
    top_peaks: list[tuple[StrengthPeak, ...]] = []
    for value in values:
        if value is None or value == "":
            top_peaks.append(())
            continue
        if type(value) is not str:
            return None
        peaks = stored_strength_peaks(value, max_items=_MAX_TOP_PEAKS)
        if peaks is None:
            return None
        top_peaks.append(peaks)
    return top_peaks


def storage_top_peak_amp_column(values: Sequence[object]) -> list[float | None] | None:
    """``sensor_frame_top_peak_amp_from_row_value`` of each stored ``top_peaks`` value, or None.

    None when a value is not a well-formed peak list: decode those rows one at a time.
    """
    largest: list[float | None] = []
    for value in values:
        if value is None or value == "":
            largest.append(None)
            continue
        if type(value) is not str:
            return None
        amps = stored_strength_peak_amps(value, max_items=_MAX_TOP_PEAKS)
        if amps is None:
            return None
        largest.append(max(amps, default=None))
    return largest


def _strength_peaks(top_peaks: object) -> tuple[StrengthPeak, ...]:
    return strength_peaks_from_sequence(top_peaks, max_items=_MAX_TOP_PEAKS)


def _build_sensor_frame(
    values: SensorFrameScalarValues, *, top_peaks: tuple[StrengthPeak, ...]
) -> SensorFrame:
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
        top_peaks=top_peaks,
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
