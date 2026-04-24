"""Boundary translators for persisted run metadata payloads."""

from __future__ import annotations

import logging
from collections.abc import Mapping

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
    RunMetadata,
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
    case_id: object = ""
    sensor_mac: object = None
    symptom: object = None
    report_date: object = None
    language: object = "en"
    reference_context: object = None
    recorded_utc_offset_seconds: object = None


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

    run_id = text_or_none(data.get("run_id")) or ""
    if not run_id:
        _LOGGER.warning("run_metadata_from_mapping: missing or empty run_id in record %r", data)
    return RunMetadata(
        record_type=text_or_none(data.get("record_type")) or RUN_METADATA_TYPE,
        schema_version=text_or_none(data.get("schema_version")) or RUN_SCHEMA_VERSION,
        run_id=run_id,
        start_time_utc=text_or_none(data.get("start_time_utc")) or "",
        end_time_utc=text_or_none(data.get("end_time_utc")),
        sensor_model=text_or_none(data.get("sensor_model")) or "unknown",
        firmware_version=text_or_none(data.get("firmware_version")),
        raw_sample_rate_hz=as_int_or_none(data.get("raw_sample_rate_hz")),
        configured_raw_sample_rate_hz=as_int_or_none(data.get("configured_raw_sample_rate_hz")),
        feature_interval_s=as_float_or_none(data.get("feature_interval_s")),
        fft_window_size_samples=as_int_or_none(data.get("fft_window_size_samples")),
        fft_window_type=text_or_none(data.get("fft_window_type")),
        peak_picker_method=text_or_none(data.get("peak_picker_method")) or PEAK_PICKER_METHOD,
        accel_scale_g_per_lsb=as_float_or_none(data.get("accel_scale_g_per_lsb")),
        incomplete_for_order_analysis=bool(data.get("incomplete_for_order_analysis", False)),
        analysis_settings=analysis_settings_snapshot_from_mapping(
            data.get("analysis_settings_snapshot"),
        ),
        car=run_car_metadata_from_mapping(data.get("active_car_snapshot")),
        sensor_snapshots=_run_sensor_snapshots_from_payload(data.get("sensor_snapshots")),
        case_id=text_or_none(data.get("case_id")) or "",
        sensor_mac=text_or_none(data.get("sensor_mac")),
        symptom=_symptom_from_payload(data.get("symptom")),
        report_date=text_or_none(data.get("report_date")),
        language=_normalized_language(data.get("language")),
        wheel_circumference_m=_reference_tire_circumference(data.get("reference_context")),
        recorded_utc_offset_seconds=coerce_utc_offset_seconds(
            data.get("recorded_utc_offset_seconds")
        ),
    )


def run_metadata_to_json_object(metadata: RunMetadata) -> JsonObject:
    """Project typed run metadata to the canonical JSON-safe storage payload."""

    payload: JsonObject = {
        "record_type": metadata.record_type,
        "schema_version": metadata.schema_version,
        "run_id": metadata.run_id,
        "start_time_utc": metadata.start_time_utc,
        "end_time_utc": metadata.end_time_utc,
        "sensor_model": metadata.sensor_model,
        "firmware_version": metadata.firmware_version,
        "raw_sample_rate_hz": metadata.raw_sample_rate_hz,
        "configured_raw_sample_rate_hz": metadata.configured_raw_sample_rate_hz,
        "feature_interval_s": metadata.feature_interval_s,
        "fft_window_size_samples": metadata.fft_window_size_samples,
        "fft_window_type": metadata.fft_window_type,
        "peak_picker_method": metadata.peak_picker_method,
        "accel_scale_g_per_lsb": metadata.accel_scale_g_per_lsb,
        "incomplete_for_order_analysis": metadata.incomplete_for_order_analysis,
        "case_id": metadata.case_id,
        "sensor_mac": metadata.sensor_mac,
        "report_date": metadata.report_date,
        "language": metadata.language,
        "analysis_settings_snapshot": analysis_settings_snapshot_to_metadata(
            metadata.analysis_settings,
        ),
    }
    if (car_metadata := run_car_metadata_to_json_object(metadata.car)) is not None:
        payload["active_car_snapshot"] = car_metadata
    if metadata.sensor_snapshots:
        payload["sensor_snapshots"] = [
            _run_sensor_snapshot_to_json_object(snapshot) for snapshot in metadata.sensor_snapshots
        ]
    if metadata.symptom is not None and not metadata.symptom.is_unspecified:
        payload["symptom"] = _symptom_to_json_object(metadata.symptom)
    if metadata.wheel_circumference_m is not None:
        payload["reference_context"] = {"tire_circumference_m": metadata.wheel_circumference_m}
    if metadata.recorded_utc_offset_seconds is not None:
        payload["recorded_utc_offset_seconds"] = metadata.recorded_utc_offset_seconds
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
    if not isinstance(payload, Mapping):
        return None
    description = text_or_none(payload.get("description"))
    if description is None:
        return None
    return Symptom(
        description=description,
        onset=text_or_none(payload.get("onset")) or "",
        context=text_or_none(payload.get("context")) or "",
    )


def _symptom_to_json_object(symptom: Symptom) -> JsonObject:
    payload: JsonObject = {"description": symptom.description}
    if symptom.onset:
        payload["onset"] = symptom.onset
    if symptom.context:
        payload["context"] = symptom.context
    return payload


def _reference_tire_circumference(payload: object) -> float | None:
    if not isinstance(payload, Mapping):
        return None
    return as_float_or_none(payload.get("tire_circumference_m"))


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
    if not isinstance(payload, Mapping):
        return None
    sensor_id = (
        text_or_none(payload.get("sensor_id"))
        or text_or_none(payload.get("client_id"))
        or text_or_none(fallback_sensor_id)
        or ""
    )
    if not sensor_id:
        return None
    return RunSensorMetadata(
        sensor_id=sensor_id,
        display_name=text_or_none(payload.get("display_name"))
        or text_or_none(payload.get("client_name"))
        or "",
        location_code=text_or_none(payload.get("location_code")) or "",
        sample_rate_hz=as_int_or_none(payload.get("sample_rate_hz")),
        firmware_version=text_or_none(payload.get("firmware_version")),
    )


def _run_sensor_snapshot_to_json_object(snapshot: RunSensorMetadata) -> JsonObject:
    payload: JsonObject = {
        "sensor_id": snapshot.sensor_id,
        "display_name": snapshot.display_name,
        "location_code": snapshot.location_code,
    }
    if snapshot.sample_rate_hz is not None:
        payload["sample_rate_hz"] = snapshot.sample_rate_hz
    if snapshot.firmware_version is not None:
        payload["firmware_version"] = snapshot.firmware_version
    return payload
