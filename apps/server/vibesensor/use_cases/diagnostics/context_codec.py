"""Boundary translators for the diagnostics-only context model."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import Car, ConfigurationSnapshot, RunContextSnapshot, Symptom, TireSpec
from vibesensor.shared.boundaries.analysis_settings_snapshot_codec import (
    ScalarSettings,
    analysis_settings_snapshot_items,
    analysis_settings_snapshot_to_metadata,
)
from vibesensor.shared.boundaries.run_metadata_codec import run_metadata_from_mapping
from vibesensor.shared.order_reference_settings import order_reference_mapping_from_spec
from vibesensor.shared.types.run_schema import RunMetadata

from .context import DiagnosticsContext

__all__ = [
    "diagnostics_analysis_settings_items",
    "diagnostics_car",
    "diagnostics_configuration_snapshot",
    "diagnostics_context_from_metadata",
    "diagnostics_context_to_run_metadata",
    "diagnostics_symptom",
]


def diagnostics_context_from_metadata(
    metadata: RunMetadata | Mapping[str, object],
    *,
    file_name: str = "run",
) -> DiagnosticsContext:
    """Decode one persisted metadata payload into the diagnostics context."""

    typed = metadata if isinstance(metadata, RunMetadata) else run_metadata_from_mapping(metadata)
    run_id = typed.run_id or f"run-{file_name}"
    return DiagnosticsContext(
        record_type=typed.record_type,
        schema_version=typed.schema_version,
        run_id=run_id,
        start_time_utc=typed.start_time_utc,
        end_time_utc=typed.end_time_utc,
        sensor_model=typed.sensor_model,
        firmware_version=typed.firmware_version,
        raw_sample_rate_hz=typed.raw_sample_rate_hz,
        feature_interval_s=typed.feature_interval_s,
        fft_window_size_samples=typed.fft_window_size_samples,
        fft_window_type=typed.fft_window_type,
        peak_picker_method=typed.peak_picker_method,
        accel_scale_g_per_lsb=typed.accel_scale_g_per_lsb,
        incomplete_for_order_analysis=typed.incomplete_for_order_analysis,
        analysis_settings=typed.analysis_settings,
        car=typed.car,
        case_id=typed.case_id,
        sensor_mac=typed.sensor_mac,
        summary_version=typed.summary_version,
        symptom=typed.symptom,
        report_date=typed.report_date,
        language=typed.language,
        explicit_engine_rpm=typed.explicit_engine_rpm,
        tire_circumference_m_override=typed.tire_circumference_m_override,
        units=typed.units,
        amplitude_definitions=typed.amplitude_definitions,
        recorded_utc_offset_seconds=typed.recorded_utc_offset_seconds,
    )


def diagnostics_context_to_run_metadata(context: DiagnosticsContext) -> RunMetadata:
    """Project the diagnostics context back to the explicit metadata boundary."""

    return RunMetadata(
        record_type=context.record_type,
        schema_version=context.schema_version,
        run_id=context.run_id,
        start_time_utc=context.start_time_utc,
        end_time_utc=context.end_time_utc,
        sensor_model=context.sensor_model,
        firmware_version=context.firmware_version,
        raw_sample_rate_hz=context.raw_sample_rate_hz,
        feature_interval_s=context.feature_interval_s,
        fft_window_size_samples=context.fft_window_size_samples,
        fft_window_type=context.fft_window_type,
        peak_picker_method=context.peak_picker_method,
        accel_scale_g_per_lsb=context.accel_scale_g_per_lsb,
        incomplete_for_order_analysis=context.incomplete_for_order_analysis,
        run_context=RunContextSnapshot(
            analysis_settings=context.analysis_settings,
            car=context.car,
        ),
        case_id=context.case_id,
        sensor_mac=context.sensor_mac,
        summary_version=context.summary_version,
        symptom=context.symptom,
        report_date=context.report_date,
        language=context.language,
        explicit_engine_rpm=context.explicit_engine_rpm,
        tire_circumference_m_override=context.tire_circumference_m_override,
        units=context.units,
        amplitude_definitions=context.amplitude_definitions,
        recorded_utc_offset_seconds=context.recorded_utc_offset_seconds,
    )


def diagnostics_analysis_settings_items(context: DiagnosticsContext) -> ScalarSettings:
    """Flatten analysis settings only at the test-run/report boundary."""

    return analysis_settings_snapshot_items(context.analysis_settings)


def diagnostics_configuration_snapshot(context: DiagnosticsContext) -> ConfigurationSnapshot:
    """Project diagnostics context into the run-capture configuration boundary."""

    settings_payload = analysis_settings_snapshot_to_metadata(context.analysis_settings)
    tire_spec = TireSpec.from_aspects(
        {
            key: coerced
            for key in ("tire_width_mm", "tire_aspect_pct", "rim_in")
            if (value := settings_payload.get(key)) is not None
            if (coerced := _coerce_float(value)) is not None
        },
        deflection_factor=context.analysis_settings.tire_deflection_factor or 1.0,
    )
    return ConfigurationSnapshot(
        sensor_model=_non_empty_text(context.sensor_model),
        firmware_version=_non_empty_text(context.firmware_version),
        raw_sample_rate_hz=(
            float(context.raw_sample_rate_hz) if context.raw_sample_rate_hz is not None else None
        ),
        feature_interval_s=context.feature_interval_s,
        final_drive_ratio=context.final_drive_ratio,
        tire_spec=tire_spec,
    )


def diagnostics_car(context: DiagnosticsContext) -> Car | None:
    """Build case-scoped car context from the diagnostics context boundary."""

    if context.car is None and context.order_reference_spec is None:
        return None
    return Car(
        id=context.active_car_id,
        name=context.car_name or "Unnamed Car",
        car_type=context.car_type or "sedan",
        aspects=(
            context.car.aspects
            if context.car is not None and context.car.aspects
            else (
                order_reference_mapping_from_spec(context.order_reference_spec)
                if context.order_reference_spec is not None
                else None
            )
        ),
        variant=context.car_variant,
        order_reference_spec=context.order_reference_spec,
    )


def diagnostics_symptom(context: DiagnosticsContext) -> Symptom:
    """Build a case symptom from the diagnostics context boundary."""

    return context.symptom if context.symptom is not None else Symptom.unspecified()


def _non_empty_text(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() == "unknown":
        return None
    return text


def _coerce_float(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None
