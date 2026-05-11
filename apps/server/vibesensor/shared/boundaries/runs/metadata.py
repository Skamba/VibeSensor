"""Boundary translators for persisted run metadata payloads."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import msgspec

from vibesensor.shared.boundaries.codecs import (
    analysis_settings_snapshot_from_mapping,
    analysis_settings_snapshot_to_metadata,
)
from vibesensor.shared.boundaries.runs._metadata_codecs import (
    PayloadFieldSpec,
    bool_decoder,
    decoded_values,
    float_decoder,
    include_if_not_none,
    int_decoder,
    language_decoder,
    optional_text_decoder,
    project_payload_fields,
    required_text_decoder,
    utc_offset_decoder,
)
from vibesensor.shared.boundaries.runs._metadata_sections import (
    reference_context_to_json_object,
    reference_tire_circumference,
    run_finalization_stage_to_json_object,
    run_finalization_stages_from_payload,
    run_raw_capture_finalize_from_payload,
    run_raw_capture_finalize_to_json_object,
    run_sensor_snapshot_to_json_object,
    run_sensor_snapshots_from_payload,
    symptom_from_payload,
    symptom_to_json_object,
)
from vibesensor.shared.boundaries.runs.car import (
    run_car_metadata_from_mapping,
    run_car_metadata_to_json_object,
)
from vibesensor.shared.types.json_types import JsonObject, is_json_object
from vibesensor.shared.types.run_schema import (
    PEAK_PICKER_METHOD,
    RUN_METADATA_TYPE,
    RUN_SCHEMA_VERSION,
    RunMetadata,
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
    finalization_stages: object = None
    case_id: object = ""
    sensor_mac: object = None
    symptom: object = None
    report_date: object = None
    language: object = "en"
    reference_context: object = None
    recorded_utc_offset_seconds: object = None


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


_RUN_METADATA_SCALAR_FIELD_SPECS: tuple[PayloadFieldSpec, ...] = (
    PayloadFieldSpec(
        "record_type",
        "record_type",
        required_text_decoder("record_type", RUN_METADATA_TYPE),
    ),
    PayloadFieldSpec(
        "schema_version",
        "schema_version",
        required_text_decoder("schema_version", RUN_SCHEMA_VERSION),
    ),
    PayloadFieldSpec("run_id", "run_id", required_text_decoder("run_id")),
    PayloadFieldSpec(
        "start_time_utc",
        "start_time_utc",
        required_text_decoder("start_time_utc"),
    ),
    PayloadFieldSpec("end_time_utc", "end_time_utc", optional_text_decoder("end_time_utc")),
    PayloadFieldSpec(
        "sensor_model",
        "sensor_model",
        required_text_decoder("sensor_model", "unknown"),
    ),
    PayloadFieldSpec(
        "firmware_version",
        "firmware_version",
        optional_text_decoder("firmware_version"),
    ),
    PayloadFieldSpec(
        "strength_algorithm_version",
        "strength_algorithm_version",
        optional_text_decoder("strength_algorithm_version"),
    ),
    PayloadFieldSpec(
        "peak_detector_version",
        "peak_detector_version",
        optional_text_decoder("peak_detector_version"),
    ),
    PayloadFieldSpec(
        "calibration_profile_id",
        "calibration_profile_id",
        optional_text_decoder("calibration_profile_id"),
    ),
    PayloadFieldSpec(
        "vehicle_baseline_profile_id",
        "vehicle_baseline_profile_id",
        optional_text_decoder("vehicle_baseline_profile_id"),
    ),
    PayloadFieldSpec("raw_sample_rate_hz", "raw_sample_rate_hz", int_decoder("raw_sample_rate_hz")),
    PayloadFieldSpec(
        "configured_raw_sample_rate_hz",
        "configured_raw_sample_rate_hz",
        int_decoder("configured_raw_sample_rate_hz"),
    ),
    PayloadFieldSpec(
        "feature_interval_s", "feature_interval_s", float_decoder("feature_interval_s")
    ),
    PayloadFieldSpec(
        "fft_window_size_samples",
        "fft_window_size_samples",
        int_decoder("fft_window_size_samples"),
    ),
    PayloadFieldSpec(
        "fft_window_type", "fft_window_type", optional_text_decoder("fft_window_type")
    ),
    PayloadFieldSpec(
        "peak_picker_method",
        "peak_picker_method",
        required_text_decoder("peak_picker_method", PEAK_PICKER_METHOD),
    ),
    PayloadFieldSpec(
        "accel_scale_g_per_lsb",
        "accel_scale_g_per_lsb",
        float_decoder("accel_scale_g_per_lsb"),
    ),
    PayloadFieldSpec(
        "incomplete_for_order_analysis",
        "incomplete_for_order_analysis",
        bool_decoder("incomplete_for_order_analysis"),
    ),
    PayloadFieldSpec("case_id", "case_id", required_text_decoder("case_id")),
    PayloadFieldSpec("sensor_mac", "sensor_mac", optional_text_decoder("sensor_mac")),
    PayloadFieldSpec("report_date", "report_date", optional_text_decoder("report_date")),
    PayloadFieldSpec("language", "language", language_decoder("language")),
    PayloadFieldSpec(
        "recorded_utc_offset_seconds",
        "recorded_utc_offset_seconds",
        utc_offset_decoder("recorded_utc_offset_seconds"),
        include=include_if_not_none,
    ),
)
_RUN_METADATA_SCALAR_STATE_FACTORY: Callable[..., _RunMetadataScalarState] = _RunMetadataScalarState


def _run_metadata_scalar_state_from_mapping(data: Mapping[str, object]) -> _RunMetadataScalarState:
    return _RUN_METADATA_SCALAR_STATE_FACTORY(
        **decoded_values(data, _RUN_METADATA_SCALAR_FIELD_SPECS),
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
        sensor_snapshots=run_sensor_snapshots_from_payload(data.get("sensor_snapshots")),
        raw_capture_finalize=run_raw_capture_finalize_from_payload(
            data.get("raw_capture_finalize")
        ),
        finalization_stages=run_finalization_stages_from_payload(data.get("finalization_stages")),
        case_id=scalar_state.case_id,
        sensor_mac=scalar_state.sensor_mac,
        symptom=symptom_from_payload(data.get("symptom")),
        report_date=scalar_state.report_date,
        language=scalar_state.language,
        wheel_circumference_m=reference_tire_circumference(data.get("reference_context")),
        recorded_utc_offset_seconds=scalar_state.recorded_utc_offset_seconds,
    )


def run_metadata_to_json_object(metadata: RunMetadata) -> JsonObject:
    """Project typed run metadata to the canonical JSON-safe storage payload."""

    payload = project_payload_fields(metadata, _RUN_METADATA_SCALAR_FIELD_SPECS)
    payload["analysis_settings_snapshot"] = analysis_settings_snapshot_to_metadata(
        metadata.analysis_settings,
    )
    if (car_metadata := run_car_metadata_to_json_object(metadata.car)) is not None:
        payload["active_car_snapshot"] = car_metadata
    if metadata.sensor_snapshots:
        payload["sensor_snapshots"] = [
            run_sensor_snapshot_to_json_object(snapshot) for snapshot in metadata.sensor_snapshots
        ]
    if metadata.raw_capture_finalize is not None:
        payload["raw_capture_finalize"] = run_raw_capture_finalize_to_json_object(
            metadata.raw_capture_finalize
        )
    if metadata.finalization_stages:
        payload["finalization_stages"] = [
            run_finalization_stage_to_json_object(stage) for stage in metadata.finalization_stages
        ]
    if (symptom := symptom_to_json_object(metadata.symptom)) is not None:
        payload["symptom"] = symptom
    if (
        reference_context := reference_context_to_json_object(metadata.wheel_circumference_m)
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
