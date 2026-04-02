"""Decoding helpers for diagnostics context construction."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import cast

from vibesensor.shared.boundaries.run_context_codec import (
    run_context_snapshot_from_metadata,
)
from vibesensor.shared.boundaries.run_metadata_snapshot_codec import (
    run_metadata_snapshot_from_metadata,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.types.json_types import JsonObject, JsonValue

from ._context import DiagnosticsContext

_OWNED_METADATA_KEYS = frozenset(
    {
        "run_id",
        "case_id",
        "sensor_mac",
        "sensor_model",
        "firmware_version",
        "raw_sample_rate_hz",
        "feature_interval_s",
        "_summary_version",
        "start_time_utc",
        "end_time_utc",
        "report_date",
        "language",
        "fft_window_size_samples",
        "fft_window_type",
        "peak_picker_method",
        "accel_scale_g_per_lsb",
        "incomplete_for_order_analysis",
        "symptom",
        "symptom_onset",
        "symptom_context",
        "tire_circumference_m",
        "engine_rpm",
        "analysis_settings",
        "analysis_settings_snapshot",
        "active_car_snapshot",
    },
)


def build_diagnostics_context(
    metadata: Mapping[str, object],
    *,
    file_name: str = "run",
) -> DiagnosticsContext:
    """Decode one raw metadata mapping into the diagnostics context."""
    raw_metadata = dict(metadata)
    run_metadata_payload = dict(raw_metadata)
    if not _non_empty_text(run_metadata_payload.get("run_id")):
        run_metadata_payload["run_id"] = f"run-{file_name}"
    run_context = run_context_snapshot_from_metadata(raw_metadata)
    return DiagnosticsContext(
        run_metadata=run_metadata_snapshot_from_metadata(
            run_metadata_payload,
            fallback_run_id=f"run-{file_name}",
        ),
        run_context=run_context,
        start_time_utc=_non_empty_text(raw_metadata.get("start_time_utc")),
        end_time_utc=_non_empty_text(raw_metadata.get("end_time_utc")),
        report_date=_non_empty_text(raw_metadata.get("report_date")),
        default_language=_normalized_language(raw_metadata.get("language")),
        fft_window_size_samples=_as_int(raw_metadata.get("fft_window_size_samples")),
        fft_window_type=_non_empty_text(raw_metadata.get("fft_window_type")),
        peak_picker_method=_non_empty_text(raw_metadata.get("peak_picker_method")),
        accel_scale_g_per_lsb=_as_float(raw_metadata.get("accel_scale_g_per_lsb")),
        incomplete_for_order_analysis=bool(raw_metadata.get("incomplete_for_order_analysis")),
        symptom_description=_non_empty_text(raw_metadata.get("symptom")) or "",
        symptom_onset=_non_empty_text(raw_metadata.get("symptom_onset")) or "",
        symptom_context=_non_empty_text(raw_metadata.get("symptom_context")) or "",
        tire_circumference_m_override=_as_float(raw_metadata.get("tire_circumference_m")),
        explicit_engine_rpm=_as_float(raw_metadata.get("engine_rpm")),
        extra_metadata=_extra_metadata(raw_metadata),
    )


def _non_empty_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _normalized_language(value: object) -> str:
    text = _non_empty_text(value)
    return text.lower() if text is not None else "en"


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


_INVALID_JSON = object()


def _extra_metadata(metadata: Mapping[str, object]) -> JsonObject:
    extra: JsonObject = {}
    for key, value in metadata.items():
        if not isinstance(key, str) or key in _OWNED_METADATA_KEYS:
            continue
        json_value = _json_value_or_invalid(value)
        if json_value is not _INVALID_JSON:
            extra[key] = cast(JsonValue, json_value)
    return extra


def _json_value_or_invalid(value: object) -> JsonValue | object:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _INVALID_JSON
    if isinstance(value, Mapping):
        nested: JsonObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                return _INVALID_JSON
            nested_value = _json_value_or_invalid(item)
            if nested_value is _INVALID_JSON:
                return _INVALID_JSON
            nested[key] = cast(JsonValue, nested_value)
        return nested
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        nested_items: list[JsonValue] = []
        for item in value:
            nested_value = _json_value_or_invalid(item)
            if nested_value is _INVALID_JSON:
                return _INVALID_JSON
            nested_items.append(cast(JsonValue, nested_value))
        return nested_items
    return _INVALID_JSON
