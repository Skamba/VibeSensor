"""Projection helpers for diagnostics context consumers."""

from __future__ import annotations

from vibesensor.domain import Car, ConfigurationSnapshot, RunContextSnapshot, Symptom
from vibesensor.shared.boundaries.run_metadata_codec import run_metadata_to_json_object
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.run_schema import RunMetadata

from ._context import DiagnosticsContext


def context_to_run_metadata(context: DiagnosticsContext) -> RunMetadata:
    """Project diagnostics context back to the canonical typed run metadata model."""
    return RunMetadata.create(
        run_id=context.run_id,
        start_time_utc=context.start_time_utc or "",
        sensor_model=context.sensor_model or "unknown",
        firmware_version=context.firmware_version,
        raw_sample_rate_hz=(
            int(context.raw_sample_rate_hz) if context.raw_sample_rate_hz is not None else None
        ),
        feature_interval_s=context.feature_interval_s,
        fft_window_size_samples=context.fft_window_size_samples,
        accel_scale_g_per_lsb=context.accel_scale_g_per_lsb,
        end_time_utc=context.end_time_utc,
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
        language=context.default_language,
        explicit_engine_rpm=context.explicit_engine_rpm,
        tire_circumference_m_override=context.tire_circumference_m_override,
        units=context.units,
        amplitude_definitions=context.amplitude_definitions,
    )


def context_to_metadata_dict(context: DiagnosticsContext) -> JsonObject:
    """Project diagnostics context into the canonical boundary payload shape."""
    return run_metadata_to_json_object(context_to_run_metadata(context))


def context_to_configuration_snapshot(context: DiagnosticsContext) -> ConfigurationSnapshot:
    """Project diagnostics context into the domain configuration snapshot shape."""
    spec = context.order_reference_spec
    return ConfigurationSnapshot(
        sensor_model=context.sensor_model,
        firmware_version=context.firmware_version,
        raw_sample_rate_hz=context.raw_sample_rate_hz,
        feature_interval_s=context.feature_interval_s,
        final_drive_ratio=context.final_drive_ratio,
        tire_spec=spec.tire_spec if spec is not None else None,
        metadata=context_to_metadata_dict(context),
    )


def context_to_car(context: DiagnosticsContext) -> Car | None:
    """Project the optional car context used by report and finding consumers."""
    spec = context.order_reference_spec
    car_snapshot = context.car
    if not (context.car_name or context.car_type or context.car_variant or spec is not None):
        return None
    return Car(
        id=car_snapshot.car_id if car_snapshot is not None else None,
        name=context.car_name or "Unnamed Car",
        car_type=context.car_type or "sedan",
        aspects=car_snapshot.aspects if car_snapshot is not None else None,
        variant=context.car_variant or None,
        order_reference_spec=spec,
    )


def context_to_symptom(context: DiagnosticsContext) -> Symptom:
    """Project diagnostics symptom metadata into the domain symptom object."""
    return context.symptom if context.symptom is not None else Symptom.unspecified()
