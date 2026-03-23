"""Decoding helpers for diagnostics context construction."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import OrderReferenceSpec, RunContextSnapshot, RunMetadataSnapshot
from vibesensor.shared.json_utils import as_float_or_none as _as_float

from ._context import DiagnosticsContext


def build_diagnostics_context(
    metadata: Mapping[str, object],
    *,
    file_name: str = "run",
) -> DiagnosticsContext:
    """Decode one raw metadata mapping into the diagnostics context."""
    raw_metadata = dict(metadata)
    run_metadata_payload = dict(raw_metadata)
    if not _non_empty_text(run_metadata_payload.get("run_id")) and not _non_empty_text(
        run_metadata_payload.get("recording_id"),
    ):
        run_metadata_payload["run_id"] = f"run-{file_name}"
    run_context = RunContextSnapshot.from_dict(raw_metadata)
    order_reference_spec = OrderReferenceSpec.from_settings(raw_metadata)
    run_context_spec = run_context.order_reference_spec
    final_drive_ratio = _as_float(raw_metadata.get("final_drive_ratio"))
    if final_drive_ratio is None and run_context_spec is not None:
        final_drive_ratio = _as_float(getattr(run_context_spec, "final_drive_ratio", None))
    current_gear_ratio = _as_float(raw_metadata.get("current_gear_ratio"))
    if current_gear_ratio is None and run_context_spec is not None:
        current_gear_ratio = _as_float(getattr(run_context_spec, "current_gear_ratio", None))
    return DiagnosticsContext(
        run_metadata=RunMetadataSnapshot.from_dict(run_metadata_payload),
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
        symptom_description=(
            _non_empty_text(raw_metadata.get("symptom") or raw_metadata.get("complaint")) or ""
        ),
        symptom_onset=_non_empty_text(raw_metadata.get("symptom_onset")) or "",
        symptom_context=_non_empty_text(raw_metadata.get("symptom_context")) or "",
        tire_circumference_m_override=_as_float(raw_metadata.get("tire_circumference_m")),
        explicit_engine_rpm=_as_float(raw_metadata.get("engine_rpm")),
        scalar_analysis_settings=_scalar_analysis_settings(raw_metadata),
        _final_drive_ratio=final_drive_ratio,
        _current_gear_ratio=current_gear_ratio,
        _car_name=_non_empty_text(raw_metadata.get("car_name") or raw_metadata.get("name")),
        _car_type=_non_empty_text(raw_metadata.get("car_type")),
        _car_variant=(
            _non_empty_text(raw_metadata.get("car_variant") or raw_metadata.get("variant"))
        ),
        _fallback_order_reference_spec=order_reference_spec,
        _boundary_metadata=raw_metadata,
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


def _scalar_analysis_settings(
    metadata: Mapping[str, object],
) -> tuple[tuple[str, int | float | bool | str], ...]:
    raw_settings = metadata.get("analysis_settings")
    if not isinstance(raw_settings, Mapping):
        return ()
    scalar_items: list[tuple[str, int | float | bool | str]] = []
    for key, value in sorted(raw_settings.items()):
        if isinstance(key, str) and isinstance(value, (int, float, bool, str)):
            scalar_items.append((key, value))
    return tuple(scalar_items)
