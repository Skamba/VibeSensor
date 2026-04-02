"""Boundary translators for persisted run metadata payloads."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Final

from vibesensor.shared.json_utils import as_float_or_none, as_int_or_none
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.run_schema import RUN_METADATA_TYPE, RUN_SCHEMA_VERSION, RunMetadata

__all__ = [
    "run_metadata_from_mapping",
    "run_metadata_to_json_object",
]

_LOGGER = logging.getLogger(__name__)
_RUN_METADATA_FIELD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "record_type",
        "schema_version",
        "run_id",
        "start_time_utc",
        "end_time_utc",
        "sensor_model",
        "firmware_version",
        "raw_sample_rate_hz",
        "feature_interval_s",
        "fft_window_size_samples",
        "fft_window_type",
        "peak_picker_method",
        "accel_scale_g_per_lsb",
        "incomplete_for_order_analysis",
    }
)


def _as_str_or_none(value: object) -> str | None:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def run_metadata_from_mapping(data: Mapping[str, object]) -> RunMetadata:
    """Normalize a raw persisted metadata mapping into the canonical typed object."""

    run_id = str(data.get("run_id", ""))
    if not run_id:
        _LOGGER.warning("run_metadata_from_mapping: missing or empty run_id in record %r", data)
    return RunMetadata(
        record_type=str(data.get("record_type", RUN_METADATA_TYPE)),
        schema_version=str(data.get("schema_version", RUN_SCHEMA_VERSION)),
        run_id=run_id,
        start_time_utc=str(data.get("start_time_utc", "")),
        end_time_utc=_as_str_or_none(data.get("end_time_utc")),
        sensor_model=str(data.get("sensor_model", "unknown")),
        firmware_version=(str(data.get("firmware_version", "")).strip() or None),
        raw_sample_rate_hz=as_int_or_none(data.get("raw_sample_rate_hz")),
        feature_interval_s=as_float_or_none(data.get("feature_interval_s")),
        fft_window_size_samples=as_int_or_none(data.get("fft_window_size_samples")),
        fft_window_type=_as_str_or_none(data.get("fft_window_type")),
        peak_picker_method=str(data.get("peak_picker_method", "")),
        accel_scale_g_per_lsb=as_float_or_none(data.get("accel_scale_g_per_lsb")),
        incomplete_for_order_analysis=bool(data.get("incomplete_for_order_analysis", False)),
        extras={
            key: value
            for key, value in data.items()
            if key not in _RUN_METADATA_FIELD_KEYS
            and (value is None or isinstance(value, (bool, int, float, str, list, dict)))
        },
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
    }
    payload.update(metadata.extras)
    return payload
