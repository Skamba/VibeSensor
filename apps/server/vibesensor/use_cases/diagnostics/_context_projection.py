"""Projection helpers for diagnostics context consumers."""

from __future__ import annotations

from dataclasses import asdict
from typing import cast

from vibesensor.domain import Car, ConfigurationSnapshot, Symptom
from vibesensor.shared.types.json_types import JsonObject

from ._context import DiagnosticsContext


def context_to_metadata_dict(context: DiagnosticsContext) -> JsonObject:
    """Rehydrate the persisted metadata shape for boundary serializers."""
    metadata: dict[str, object] = dict(context._boundary_metadata)
    metadata["run_id"] = context.run_id
    metadata["case_id"] = context.run_metadata.case_id
    metadata["sensor_mac"] = context.run_metadata.sensor_mac
    metadata["sensor_model"] = context.sensor_model
    metadata["firmware_version"] = context.firmware_version
    metadata["raw_sample_rate_hz"] = context.raw_sample_rate_hz
    metadata["feature_interval_s"] = context.feature_interval_s
    metadata["_summary_version"] = context.run_metadata.summary_version
    metadata["start_time_utc"] = context.start_time_utc
    metadata["end_time_utc"] = context.end_time_utc
    if context.report_date is not None or "report_date" in metadata:
        metadata["report_date"] = context.report_date
    if context.fft_window_size_samples is not None or "fft_window_size_samples" in metadata:
        metadata["fft_window_size_samples"] = context.fft_window_size_samples
    if context.fft_window_type is not None or "fft_window_type" in metadata:
        metadata["fft_window_type"] = context.fft_window_type
    if context.peak_picker_method is not None or "peak_picker_method" in metadata:
        metadata["peak_picker_method"] = context.peak_picker_method
    if context.accel_scale_g_per_lsb is not None or "accel_scale_g_per_lsb" in metadata:
        metadata["accel_scale_g_per_lsb"] = context.accel_scale_g_per_lsb
    metadata["incomplete_for_order_analysis"] = context.incomplete_for_order_analysis
    if "language" in metadata or context.default_language != "en":
        metadata["language"] = context.default_language
    if context.explicit_engine_rpm is not None or "engine_rpm" in metadata:
        metadata["engine_rpm"] = context.explicit_engine_rpm

    settings_dict = asdict(context.run_context.analysis_settings)
    for key, value in settings_dict.items():
        if key in metadata or value:
            metadata[key] = value
    tire_circumference_m = context.tire_circumference_m
    if tire_circumference_m is not None or "tire_circumference_m" in metadata:
        metadata["tire_circumference_m"] = tire_circumference_m

    has_non_zero_settings = any(value != 0.0 for value in settings_dict.values())
    if "analysis_settings_snapshot" in metadata or has_non_zero_settings:
        metadata.update(context.run_context.to_metadata_dict())

    if context.run_context.has_car_context:
        metadata["active_car_id"] = context.run_context.active_car_id
        metadata["car_name"] = context.run_context.car_name
        metadata["car_type"] = context.run_context.car_type
        metadata["car_variant"] = context.run_context.car_variant
    else:
        if context.car_name is not None or "car_name" in metadata:
            metadata["car_name"] = context.car_name
        if context.car_type is not None or "car_type" in metadata:
            metadata["car_type"] = context.car_type
        if context.car_variant is not None or "car_variant" in metadata:
            metadata["car_variant"] = context.car_variant
    return cast(JsonObject, metadata)


def context_to_configuration_snapshot(context: DiagnosticsContext) -> ConfigurationSnapshot:
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
    spec = context.order_reference_spec
    car_snapshot = context.run_context.car
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
    if not context.symptom_description:
        return Symptom.unspecified()
    return Symptom(
        description=context.symptom_description,
        onset=context.symptom_onset,
        context=context.symptom_context,
    )
