"""Decoding helpers for diagnostics context construction."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.shared.boundaries.analysis_settings_snapshot_codec import (
    analysis_settings_snapshot_from_mapping,
)
from vibesensor.shared.boundaries.car_snapshot_codec import car_snapshot_from_mapping
from vibesensor.shared.boundaries.run_metadata_snapshot_codec import (
    run_metadata_snapshot_from_metadata,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.types.json_types import JsonObject, is_json_object

from ._context import DiagnosticsContext, DiagnosticsSymptom


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
    return DiagnosticsContext(
        run_metadata=run_metadata_snapshot_from_metadata(
            run_metadata_payload,
            fallback_run_id=f"run-{file_name}",
        ),
        analysis_settings=analysis_settings_snapshot_from_mapping(
            raw_metadata.get("analysis_settings_snapshot"),
        ),
        car=car_snapshot_from_mapping(raw_metadata.get("active_car_snapshot")),
        symptom=DiagnosticsSymptom(
            description=_non_empty_text(raw_metadata.get("symptom")) or "",
            onset=_non_empty_text(raw_metadata.get("symptom_onset")) or "",
            context=_non_empty_text(raw_metadata.get("symptom_context")) or "",
        ),
        start_time_utc=_non_empty_text(raw_metadata.get("start_time_utc")),
        end_time_utc=_non_empty_text(raw_metadata.get("end_time_utc")),
        report_date=_non_empty_text(raw_metadata.get("report_date")),
        default_language=_normalized_language(raw_metadata.get("language")),
        fft_window_size_samples=_as_int(raw_metadata.get("fft_window_size_samples")),
        fft_window_type=_non_empty_text(raw_metadata.get("fft_window_type")),
        peak_picker_method=_non_empty_text(raw_metadata.get("peak_picker_method")),
        accel_scale_g_per_lsb=_as_float(raw_metadata.get("accel_scale_g_per_lsb")),
        incomplete_for_order_analysis=bool(raw_metadata.get("incomplete_for_order_analysis")),
        tire_circumference_m_override=_as_float(raw_metadata.get("tire_circumference_m")),
        explicit_engine_rpm=_as_float(raw_metadata.get("engine_rpm")),
        units=_json_object_or_none(raw_metadata.get("units")),
        amplitude_definitions=_json_object_or_none(raw_metadata.get("amplitude_definitions")),
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


def _json_object_or_none(value: object) -> JsonObject | None:
    return value if is_json_object(value) else None
