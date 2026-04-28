"""Boundary translators for persisted run metadata payloads."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast

import msgspec

from vibesensor.domain import Symptom
from vibesensor.shared.boundaries.codecs import (
    analysis_settings_snapshot_from_mapping,
    analysis_settings_snapshot_to_metadata,
)
from vibesensor.shared.boundaries.codecs.scalars import text_or_none
from vibesensor.shared.boundaries.runs.car import (
    run_car_metadata_from_mapping,
    run_car_metadata_to_json_object,
)
from vibesensor.shared.json_utils import as_float_or_none, as_int_or_none
from vibesensor.shared.time_utils import coerce_utc_offset_seconds
from vibesensor.shared.types.json_types import JsonObject, is_json_object
from vibesensor.shared.types.run_schema import (
    PEAK_PICKER_METHOD,
    RUN_METADATA_TYPE,
    RUN_SCHEMA_VERSION,
    RawCaptureFinalizeStatus,
    RunMetadata,
    RunRawCaptureFinalize,
    RunSensorMetadata,
)

__all__ = [
    "run_metadata_from_json",
    "run_metadata_from_mapping",
    "run_metadata_to_json_bytes",
    "run_metadata_to_json_object",
]

_LOGGER = logging.getLogger(__name__)


class _RunMetadataRecord(msgspec.Struct, kw_only=True, frozen=True):
    """Msgspec-owned run metadata record for persisted JSONL envelopes."""

    record_type: str = RUN_METADATA_TYPE
    schema_version: str = RUN_SCHEMA_VERSION
    run_id: object = ""
    start_time_utc: object = ""
    end_time_utc: object = None
    sensor_model: object = "unknown"
    firmware_version: object = None
    strength_algorithm_version: object = None
    peak_detector_version: object = None
    calibration_profile_id: object = None
    vehicle_baseline_profile_id: object = None
    raw_sample_rate_hz: object = None
    configured_raw_sample_rate_hz: object = None
    feature_interval_s: object = None
    fft_window_size_samples: object = None
    fft_window_type: object = None
    peak_picker_method: object = PEAK_PICKER_METHOD
    accel_scale_g_per_lsb: object = None
    incomplete_for_order_analysis: object = False
    analysis_settings_snapshot: object = None
    active_car_snapshot: object = None
    sensor_snapshots: object = None
    raw_capture_finalize: object = None
    case_id: object = ""
    sensor_mac: object = None
    symptom: object = None
    report_date: object = None
    language: object = "en"
    reference_context: object = None
    recorded_utc_offset_seconds: object = None


type _PayloadDecoder = Callable[[Mapping[str, object]], object]
type _IncludePredicate = Callable[[object], bool]


def _always_include(_value: object) -> bool:
    return True


def _include_if_not_none(value: object) -> bool:
    return value is not None


def _include_if_nonempty_text(value: object) -> bool:
    return value is not None and bool(str(value).strip())


@dataclass(frozen=True, slots=True)
class _PayloadFieldSpec:
    payload_key: str
    field_name: str
    decode: _PayloadDecoder
    include: _IncludePredicate = _always_include


@dataclass(frozen=True, slots=True)
class _RunMetadataScalarState:
    record_type: str
    schema_version: str
    run_id: str
    start_time_utc: str
    end_time_utc: str | None
    sensor_model: str
    firmware_version: str | None
    strength_algorithm_version: str | None
    peak_detector_version: str | None
    calibration_profile_id: str | None
    vehicle_baseline_profile_id: str | None
    raw_sample_rate_hz: int | None
    configured_raw_sample_rate_hz: int | None
    feature_interval_s: float | None
    fft_window_size_samples: int | None
    fft_window_type: str | None
    peak_picker_method: str
    accel_scale_g_per_lsb: float | None
    incomplete_for_order_analysis: bool
    case_id: str
    sensor_mac: str | None
    report_date: str | None
    language: str
    recorded_utc_offset_seconds: int | None


@dataclass(frozen=True, slots=True)
class _ReferenceContextState:
    wheel_circumference_m: float | None


@dataclass(frozen=True, slots=True)
class _SymptomState:
    description: str
    onset: str
    context: str


@dataclass(frozen=True, slots=True)
class _RunSensorSnapshotState:
    sensor_id: str
    display_name: str
    location_code: str
    mount_orientation: str | None
    sample_rate_hz: int | None
    firmware_version: str | None


@dataclass(frozen=True, slots=True)
class _RunRawCaptureFinalizeState:
    status: RawCaptureFinalizeStatus | None
    queue_depth: int | None
    error_summary: str | None


def _required_text_decoder(payload_key: str, default: str = "") -> _PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return text_or_none(payload.get(payload_key)) or default

    return decode


def _optional_text_decoder(payload_key: str) -> _PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return text_or_none(payload.get(payload_key))

    return decode


def _int_decoder(payload_key: str) -> _PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return as_int_or_none(payload.get(payload_key))

    return decode


def _float_decoder(payload_key: str) -> _PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return as_float_or_none(payload.get(payload_key))

    return decode


def _bool_decoder(payload_key: str) -> _PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return bool(payload.get(payload_key, False))

    return decode


def _language_decoder(payload_key: str) -> _PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return _normalized_language(payload.get(payload_key))

    return decode


def _utc_offset_decoder(payload_key: str) -> _PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return coerce_utc_offset_seconds(payload.get(payload_key))

    return decode


def _raw_capture_finalize_status_decoder(payload_key: str) -> _PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        status = text_or_none(payload.get(payload_key))
        if status not in {"completed", "not_configured", "enqueue_timeout", "timeout", "failed"}:
            return None
        return cast(RawCaptureFinalizeStatus, status)

    return decode


_RUN_METADATA_SCALAR_FIELD_SPECS: tuple[_PayloadFieldSpec, ...] = (
    _PayloadFieldSpec(
        "record_type",
        "record_type",
        _required_text_decoder("record_type", RUN_METADATA_TYPE),
    ),
    _PayloadFieldSpec(
        "schema_version",
        "schema_version",
        _required_text_decoder("schema_version", RUN_SCHEMA_VERSION),
    ),
    _PayloadFieldSpec("run_id", "run_id", _required_text_decoder("run_id")),
    _PayloadFieldSpec(
        "start_time_utc",
        "start_time_utc",
        _required_text_decoder("start_time_utc"),
    ),
    _PayloadFieldSpec("end_time_utc", "end_time_utc", _optional_text_decoder("end_time_utc")),
    _PayloadFieldSpec(
        "sensor_model",
        "sensor_model",
        _required_text_decoder("sensor_model", "unknown"),
    ),
    _PayloadFieldSpec(
        "firmware_version",
        "firmware_version",
        _optional_text_decoder("firmware_version"),
    ),
    _PayloadFieldSpec(
        "strength_algorithm_version",
        "strength_algorithm_version",
        _optional_text_decoder("strength_algorithm_version"),
    ),
    _PayloadFieldSpec(
        "peak_detector_version",
        "peak_detector_version",
        _optional_text_decoder("peak_detector_version"),
    ),
    _PayloadFieldSpec(
        "calibration_profile_id",
        "calibration_profile_id",
        _optional_text_decoder("calibration_profile_id"),
    ),
    _PayloadFieldSpec(
        "vehicle_baseline_profile_id",
        "vehicle_baseline_profile_id",
        _optional_text_decoder("vehicle_baseline_profile_id"),
    ),
    _PayloadFieldSpec(
        "raw_sample_rate_hz", "raw_sample_rate_hz", _int_decoder("raw_sample_rate_hz")
    ),
    _PayloadFieldSpec(
        "configured_raw_sample_rate_hz",
        "configured_raw_sample_rate_hz",
        _int_decoder("configured_raw_sample_rate_hz"),
    ),
    _PayloadFieldSpec(
        "feature_interval_s", "feature_interval_s", _float_decoder("feature_interval_s")
    ),
    _PayloadFieldSpec(
        "fft_window_size_samples",
        "fft_window_size_samples",
        _int_decoder("fft_window_size_samples"),
    ),
    _PayloadFieldSpec(
        "fft_window_type", "fft_window_type", _optional_text_decoder("fft_window_type")
    ),
    _PayloadFieldSpec(
        "peak_picker_method",
        "peak_picker_method",
        _required_text_decoder("peak_picker_method", PEAK_PICKER_METHOD),
    ),
    _PayloadFieldSpec(
        "accel_scale_g_per_lsb",
        "accel_scale_g_per_lsb",
        _float_decoder("accel_scale_g_per_lsb"),
    ),
    _PayloadFieldSpec(
        "incomplete_for_order_analysis",
        "incomplete_for_order_analysis",
        _bool_decoder("incomplete_for_order_analysis"),
    ),
    _PayloadFieldSpec("case_id", "case_id", _required_text_decoder("case_id")),
    _PayloadFieldSpec("sensor_mac", "sensor_mac", _optional_text_decoder("sensor_mac")),
    _PayloadFieldSpec("report_date", "report_date", _optional_text_decoder("report_date")),
    _PayloadFieldSpec("language", "language", _language_decoder("language")),
    _PayloadFieldSpec(
        "recorded_utc_offset_seconds",
        "recorded_utc_offset_seconds",
        _utc_offset_decoder("recorded_utc_offset_seconds"),
        include=_include_if_not_none,
    ),
)
_REFERENCE_CONTEXT_FIELD_SPECS: tuple[_PayloadFieldSpec, ...] = (
    _PayloadFieldSpec(
        "tire_circumference_m",
        "wheel_circumference_m",
        _float_decoder("tire_circumference_m"),
        include=_include_if_not_none,
    ),
)
_SYMPTOM_FIELD_SPECS: tuple[_PayloadFieldSpec, ...] = (
    _PayloadFieldSpec("description", "description", _required_text_decoder("description")),
    _PayloadFieldSpec(
        "onset",
        "onset",
        _required_text_decoder("onset"),
        include=_include_if_nonempty_text,
    ),
    _PayloadFieldSpec(
        "context",
        "context",
        _required_text_decoder("context"),
        include=_include_if_nonempty_text,
    ),
)
_RUN_SENSOR_SNAPSHOT_ENCODE_FIELD_SPECS: tuple[_PayloadFieldSpec, ...] = (
    _PayloadFieldSpec("sensor_id", "sensor_id", _required_text_decoder("sensor_id")),
    _PayloadFieldSpec("display_name", "display_name", _required_text_decoder("display_name")),
    _PayloadFieldSpec("location_code", "location_code", _required_text_decoder("location_code")),
    _PayloadFieldSpec(
        "mount_orientation",
        "mount_orientation",
        _optional_text_decoder("mount_orientation"),
        include=_include_if_not_none,
    ),
    _PayloadFieldSpec(
        "sample_rate_hz",
        "sample_rate_hz",
        _int_decoder("sample_rate_hz"),
        include=_include_if_not_none,
    ),
    _PayloadFieldSpec(
        "firmware_version",
        "firmware_version",
        _optional_text_decoder("firmware_version"),
        include=_include_if_not_none,
    ),
)
_RUN_RAW_CAPTURE_FINALIZE_FIELD_SPECS: tuple[_PayloadFieldSpec, ...] = (
    _PayloadFieldSpec(
        "status",
        "status",
        _raw_capture_finalize_status_decoder("status"),
    ),
    _PayloadFieldSpec(
        "queue_depth",
        "queue_depth",
        _int_decoder("queue_depth"),
        include=_include_if_not_none,
    ),
    _PayloadFieldSpec(
        "error_summary",
        "error_summary",
        _optional_text_decoder("error_summary"),
        include=_include_if_not_none,
    ),
)
_RUN_METADATA_SCALAR_STATE_FACTORY: Callable[..., _RunMetadataScalarState] = _RunMetadataScalarState
_REFERENCE_CONTEXT_STATE_FACTORY: Callable[..., _ReferenceContextState] = _ReferenceContextState
_SYMPTOM_STATE_FACTORY: Callable[..., _SymptomState] = _SymptomState
_RUN_SENSOR_SNAPSHOT_STATE_FACTORY: Callable[..., _RunSensorSnapshotState] = _RunSensorSnapshotState
_RUN_RAW_CAPTURE_FINALIZE_STATE_FACTORY: Callable[..., _RunRawCaptureFinalizeState] = (
    _RunRawCaptureFinalizeState
)


def _decoded_values(
    payload: Mapping[str, object],
    specs: tuple[_PayloadFieldSpec, ...],
) -> dict[str, object]:
    return {spec.field_name: spec.decode(payload) for spec in specs}


def _project_payload_fields(
    source: object,
    specs: tuple[_PayloadFieldSpec, ...],
) -> JsonObject:
    payload: dict[str, object] = {}
    for spec in specs:
        value = getattr(source, spec.field_name)
        if spec.include(value):
            payload[spec.payload_key] = value
    return cast(JsonObject, payload)


def _run_metadata_scalar_state_from_mapping(data: Mapping[str, object]) -> _RunMetadataScalarState:
    return _RUN_METADATA_SCALAR_STATE_FACTORY(
        **_decoded_values(data, _RUN_METADATA_SCALAR_FIELD_SPECS),
    )


def _reference_context_state_from_mapping(
    payload: Mapping[str, object],
) -> _ReferenceContextState:
    return _REFERENCE_CONTEXT_STATE_FACTORY(
        **_decoded_values(payload, _REFERENCE_CONTEXT_FIELD_SPECS),
    )


def _sensor_id_decoder(*, fallback_sensor_id: object = None) -> _PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return (
            text_or_none(payload.get("sensor_id"))
            or text_or_none(payload.get("client_id"))
            or text_or_none(fallback_sensor_id)
            or ""
        )

    return decode


def _display_name_decoder() -> _PayloadDecoder:
    def decode(payload: Mapping[str, object]) -> object:
        return (
            text_or_none(payload.get("display_name"))
            or text_or_none(payload.get("client_name"))
            or ""
        )

    return decode


def _run_sensor_snapshot_decode_field_specs(
    *,
    fallback_sensor_id: object = None,
) -> tuple[_PayloadFieldSpec, ...]:
    return (
        _PayloadFieldSpec(
            "sensor_id",
            "sensor_id",
            _sensor_id_decoder(fallback_sensor_id=fallback_sensor_id),
        ),
        _PayloadFieldSpec("display_name", "display_name", _display_name_decoder()),
        _PayloadFieldSpec(
            "location_code", "location_code", _required_text_decoder("location_code")
        ),
        _PayloadFieldSpec(
            "mount_orientation",
            "mount_orientation",
            _optional_text_decoder("mount_orientation"),
        ),
        _PayloadFieldSpec("sample_rate_hz", "sample_rate_hz", _int_decoder("sample_rate_hz")),
        _PayloadFieldSpec(
            "firmware_version",
            "firmware_version",
            _optional_text_decoder("firmware_version"),
        ),
    )


def run_metadata_from_json(data: str | bytes | bytearray) -> RunMetadata:
    """Decode persisted metadata JSON through the canonical msgspec boundary."""

    try:
        payload = msgspec.to_builtins(msgspec.json.decode(data, type=_RunMetadataRecord))
    except msgspec.ValidationError:
        payload = msgspec.json.decode(data)
    if not is_json_object(payload):
        raise TypeError("run metadata JSON must decode to an object")
    return run_metadata_from_mapping(payload)


def run_metadata_from_mapping(data: Mapping[str, object]) -> RunMetadata:
    """Normalize a raw persisted metadata mapping into the canonical typed object."""

    scalar_state = _run_metadata_scalar_state_from_mapping(data)
    if not scalar_state.run_id:
        _LOGGER.warning("run_metadata_from_mapping: missing or empty run_id in record %r", data)
    return RunMetadata(
        record_type=scalar_state.record_type,
        schema_version=scalar_state.schema_version,
        run_id=scalar_state.run_id,
        start_time_utc=scalar_state.start_time_utc,
        end_time_utc=scalar_state.end_time_utc,
        sensor_model=scalar_state.sensor_model,
        firmware_version=scalar_state.firmware_version,
        strength_algorithm_version=scalar_state.strength_algorithm_version,
        peak_detector_version=scalar_state.peak_detector_version,
        calibration_profile_id=scalar_state.calibration_profile_id,
        vehicle_baseline_profile_id=scalar_state.vehicle_baseline_profile_id,
        raw_sample_rate_hz=scalar_state.raw_sample_rate_hz,
        configured_raw_sample_rate_hz=scalar_state.configured_raw_sample_rate_hz,
        feature_interval_s=scalar_state.feature_interval_s,
        fft_window_size_samples=scalar_state.fft_window_size_samples,
        fft_window_type=scalar_state.fft_window_type,
        peak_picker_method=scalar_state.peak_picker_method,
        accel_scale_g_per_lsb=scalar_state.accel_scale_g_per_lsb,
        incomplete_for_order_analysis=scalar_state.incomplete_for_order_analysis,
        analysis_settings=analysis_settings_snapshot_from_mapping(
            data.get("analysis_settings_snapshot"),
        ),
        car=run_car_metadata_from_mapping(data.get("active_car_snapshot")),
        sensor_snapshots=_run_sensor_snapshots_from_payload(data.get("sensor_snapshots")),
        raw_capture_finalize=_run_raw_capture_finalize_from_payload(
            data.get("raw_capture_finalize")
        ),
        case_id=scalar_state.case_id,
        sensor_mac=scalar_state.sensor_mac,
        symptom=_symptom_from_payload(data.get("symptom")),
        report_date=scalar_state.report_date,
        language=scalar_state.language,
        wheel_circumference_m=_reference_tire_circumference(data.get("reference_context")),
        recorded_utc_offset_seconds=scalar_state.recorded_utc_offset_seconds,
    )


def run_metadata_to_json_object(metadata: RunMetadata) -> JsonObject:
    """Project typed run metadata to the canonical JSON-safe storage payload."""

    payload = _project_payload_fields(metadata, _RUN_METADATA_SCALAR_FIELD_SPECS)
    payload["analysis_settings_snapshot"] = analysis_settings_snapshot_to_metadata(
        metadata.analysis_settings,
    )
    if (car_metadata := run_car_metadata_to_json_object(metadata.car)) is not None:
        payload["active_car_snapshot"] = car_metadata
    if metadata.sensor_snapshots:
        payload["sensor_snapshots"] = [
            _run_sensor_snapshot_to_json_object(snapshot) for snapshot in metadata.sensor_snapshots
        ]
    if metadata.raw_capture_finalize is not None:
        payload["raw_capture_finalize"] = _run_raw_capture_finalize_to_json_object(
            metadata.raw_capture_finalize
        )
    if (symptom := _symptom_to_json_object(metadata.symptom)) is not None:
        payload["symptom"] = symptom
    if (
        reference_context := _reference_context_to_json_object(metadata.wheel_circumference_m)
    ) is not None:
        payload["reference_context"] = reference_context
    return payload


def run_metadata_to_json_bytes(metadata: RunMetadata) -> bytes:
    """Encode typed run metadata through the canonical msgspec boundary."""

    record = msgspec.convert(
        run_metadata_to_json_object(metadata),
        type=_RunMetadataRecord,
        strict=False,
    )
    return msgspec.json.encode(record)


def _normalized_language(value: object) -> str:
    text = text_or_none(value)
    return text.lower() if text is not None else "en"


def _symptom_from_payload(payload: object) -> Symptom | None:
    state = _symptom_state_from_mapping(payload)
    if state is None:
        return None
    return Symptom(
        description=state.description,
        onset=state.onset,
        context=state.context,
    )


def _symptom_state_from_mapping(payload: object) -> _SymptomState | None:
    if not isinstance(payload, Mapping):
        return None
    state = _SYMPTOM_STATE_FACTORY(**_decoded_values(payload, _SYMPTOM_FIELD_SPECS))
    if not state.description:
        return None
    return state


def _symptom_to_json_object(symptom: Symptom | None) -> JsonObject | None:
    if symptom is None or symptom.is_unspecified:
        return None
    return _project_payload_fields(symptom, _SYMPTOM_FIELD_SPECS)


def _reference_tire_circumference(payload: object) -> float | None:
    if (state := _reference_context_from_payload(payload)) is None:
        return None
    return state.wheel_circumference_m


def _reference_context_from_payload(payload: object) -> _ReferenceContextState | None:
    if not isinstance(payload, Mapping):
        return None
    return _reference_context_state_from_mapping(payload)


def _reference_context_to_json_object(wheel_circumference_m: float | None) -> JsonObject | None:
    if wheel_circumference_m is None:
        return None
    return _project_payload_fields(
        _ReferenceContextState(wheel_circumference_m=wheel_circumference_m),
        _REFERENCE_CONTEXT_FIELD_SPECS,
    )


def _run_sensor_snapshots_from_payload(payload: object) -> tuple[RunSensorMetadata, ...]:
    records: list[RunSensorMetadata] = []
    if isinstance(payload, Mapping):
        iterable: list[tuple[object, object]] = list(payload.items())
        for sensor_id, entry in iterable:
            if not isinstance(entry, Mapping):
                continue
            snapshot = _run_sensor_snapshot_from_mapping(entry, fallback_sensor_id=sensor_id)
            if snapshot is not None:
                records.append(snapshot)
    elif isinstance(payload, list):
        for entry in payload:
            snapshot = _run_sensor_snapshot_from_mapping(entry)
            if snapshot is not None:
                records.append(snapshot)
    records.sort(key=lambda snapshot: snapshot.sensor_id)
    return tuple(records)


def _run_sensor_snapshot_from_mapping(
    payload: object,
    *,
    fallback_sensor_id: object = None,
) -> RunSensorMetadata | None:
    state = _run_sensor_snapshot_state_from_mapping(
        payload,
        fallback_sensor_id=fallback_sensor_id,
    )
    if state is None:
        return None
    return RunSensorMetadata(
        sensor_id=state.sensor_id,
        display_name=state.display_name,
        location_code=state.location_code,
        mount_orientation=state.mount_orientation,
        sample_rate_hz=state.sample_rate_hz,
        firmware_version=state.firmware_version,
    )


def _run_sensor_snapshot_state_from_mapping(
    payload: object,
    *,
    fallback_sensor_id: object = None,
) -> _RunSensorSnapshotState | None:
    if not isinstance(payload, Mapping):
        return None
    state = _RUN_SENSOR_SNAPSHOT_STATE_FACTORY(
        **_decoded_values(
            payload,
            _run_sensor_snapshot_decode_field_specs(
                fallback_sensor_id=fallback_sensor_id,
            ),
        )
    )
    if not state.sensor_id:
        return None
    return state


def _run_sensor_snapshot_to_json_object(snapshot: RunSensorMetadata) -> JsonObject:
    return _project_payload_fields(snapshot, _RUN_SENSOR_SNAPSHOT_ENCODE_FIELD_SPECS)


def _run_raw_capture_finalize_from_payload(payload: object) -> RunRawCaptureFinalize | None:
    state = _run_raw_capture_finalize_state_from_mapping(payload)
    if state is None or state.status is None:
        return None
    return RunRawCaptureFinalize(
        status=state.status,
        queue_depth=state.queue_depth,
        error_summary=state.error_summary,
    )


def _run_raw_capture_finalize_state_from_mapping(
    payload: object,
) -> _RunRawCaptureFinalizeState | None:
    if not isinstance(payload, Mapping):
        return None
    state = _RUN_RAW_CAPTURE_FINALIZE_STATE_FACTORY(
        **_decoded_values(payload, _RUN_RAW_CAPTURE_FINALIZE_FIELD_SPECS),
    )
    if state.status is None:
        return None
    return state


def _run_raw_capture_finalize_to_json_object(
    finalize: RunRawCaptureFinalize,
) -> JsonObject:
    return _project_payload_fields(finalize, _RUN_RAW_CAPTURE_FINALIZE_FIELD_SPECS)
