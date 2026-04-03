"""Boundary translators for persisted run metadata payloads."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from vibesensor.domain import Symptom
from vibesensor.shared.boundaries._codec_helpers import text_or_none
from vibesensor.shared.boundaries.analysis_settings_snapshot_codec import (
    analysis_settings_snapshot_from_mapping,
    analysis_settings_snapshot_to_metadata,
)
from vibesensor.shared.boundaries.run_car_codec import (
    run_car_metadata_from_mapping,
    run_car_metadata_to_json_object,
)
from vibesensor.shared.json_utils import as_float_or_none, as_int_or_none
from vibesensor.shared.time_utils import coerce_utc_offset_seconds
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.run_schema import (
    PEAK_PICKER_METHOD,
    RUN_METADATA_TYPE,
    RUN_SCHEMA_VERSION,
    RunMetadata,
)

__all__ = [
    "run_metadata_from_mapping",
    "run_metadata_to_json_object",
]

_LOGGER = logging.getLogger(__name__)


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
    if metadata.symptom is not None and not metadata.symptom.is_unspecified:
        payload["symptom"] = _symptom_to_json_object(metadata.symptom)
    if metadata.wheel_circumference_m is not None:
        payload["reference_context"] = {"tire_circumference_m": metadata.wheel_circumference_m}
    if metadata.recorded_utc_offset_seconds is not None:
        payload["recorded_utc_offset_seconds"] = metadata.recorded_utc_offset_seconds
    return payload


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
