"""Projection helpers for diagnostics context consumers."""

from __future__ import annotations

from vibesensor.domain import Car, ConfigurationSnapshot, Symptom
from vibesensor.shared.boundaries.analysis_settings_snapshot_codec import (
    analysis_settings_snapshot_to_metadata,
)
from vibesensor.shared.boundaries.car_snapshot_codec import car_snapshot_to_metadata
from vibesensor.shared.types.json_types import JsonObject

from ._context import DiagnosticsContext


def context_to_metadata_dict(context: DiagnosticsContext) -> JsonObject:
    """Rehydrate the persisted metadata shape for boundary serializers."""
    metadata: JsonObject = {
        "run_id": context.run_id,
        "case_id": context.case_id,
        "sensor_mac": context.sensor_mac,
        "sensor_model": context.sensor_model,
        "firmware_version": context.firmware_version,
        "raw_sample_rate_hz": context.raw_sample_rate_hz,
        "feature_interval_s": context.feature_interval_s,
        "_summary_version": context.summary_version,
        "start_time_utc": context.start_time_utc,
        "end_time_utc": context.end_time_utc,
        "language": context.default_language,
        "incomplete_for_order_analysis": context.incomplete_for_order_analysis,
        "analysis_settings_snapshot": analysis_settings_snapshot_to_metadata(
            context.analysis_settings,
        ),
    }
    if context.report_date is not None:
        metadata["report_date"] = context.report_date
    if context.fft_window_size_samples is not None:
        metadata["fft_window_size_samples"] = context.fft_window_size_samples
    if context.fft_window_type is not None:
        metadata["fft_window_type"] = context.fft_window_type
    if context.peak_picker_method is not None:
        metadata["peak_picker_method"] = context.peak_picker_method
    if context.accel_scale_g_per_lsb is not None:
        metadata["accel_scale_g_per_lsb"] = context.accel_scale_g_per_lsb
    if context.units is not None:
        metadata["units"] = context.units
    if context.amplitude_definitions is not None:
        metadata["amplitude_definitions"] = context.amplitude_definitions
    if context.explicit_engine_rpm is not None:
        metadata["engine_rpm"] = context.explicit_engine_rpm
    symptom = context.symptom
    if symptom is not None and not symptom.is_unspecified:
        metadata["symptom"] = symptom.description
        if symptom.onset:
            metadata["symptom_onset"] = symptom.onset
        if symptom.context:
            metadata["symptom_context"] = symptom.context
    if (car_metadata := car_snapshot_to_metadata(context.car)) is not None:
        metadata["active_car_snapshot"] = car_metadata
    tire_circumference_m = context.tire_circumference_m
    if tire_circumference_m is not None:
        metadata["tire_circumference_m"] = tire_circumference_m
    return metadata


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
