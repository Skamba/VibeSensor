"""Projection helpers for diagnostics context consumers."""

from __future__ import annotations

import math
from dataclasses import asdict
from typing import cast

from vibesensor.domain import Car, ConfigurationSnapshot, Symptom
from vibesensor.shared.types.json_types import JsonObject

from ._context import DiagnosticsContext


def context_to_metadata_dict(context: DiagnosticsContext) -> JsonObject:
    """Rehydrate the persisted metadata shape for boundary serializers."""
    metadata: JsonObject = cast(JsonObject, dict(context.passthrough_metadata))
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
    if context.report_date is not None or context.has_boundary_key("report_date"):
        metadata["report_date"] = context.report_date
    if context.fft_window_size_samples is not None or context.has_boundary_key(
        "fft_window_size_samples",
    ):
        metadata["fft_window_size_samples"] = context.fft_window_size_samples
    if context.fft_window_type is not None or context.has_boundary_key("fft_window_type"):
        metadata["fft_window_type"] = context.fft_window_type
    if context.peak_picker_method is not None or context.has_boundary_key("peak_picker_method"):
        metadata["peak_picker_method"] = context.peak_picker_method
    if context.accel_scale_g_per_lsb is not None or context.has_boundary_key(
        "accel_scale_g_per_lsb",
    ):
        metadata["accel_scale_g_per_lsb"] = context.accel_scale_g_per_lsb
    metadata["incomplete_for_order_analysis"] = context.incomplete_for_order_analysis
    if context.default_language != "en" or context.has_boundary_key("language"):
        metadata["language"] = context.default_language
    if context.explicit_engine_rpm is not None or context.has_boundary_key("engine_rpm"):
        metadata["engine_rpm"] = context.explicit_engine_rpm
    if context.symptom_description:
        metadata["symptom"] = context.symptom_description
    if context.symptom_onset or context.has_boundary_key("symptom_onset"):
        metadata["symptom_onset"] = context.symptom_onset
    if context.symptom_context or context.has_boundary_key("symptom_context"):
        metadata["symptom_context"] = context.symptom_context
    if context.scalar_analysis_settings or context.has_boundary_key("analysis_settings"):
        metadata["analysis_settings"] = dict(context.scalar_analysis_settings)
    metadata["analysis_settings_snapshot"] = _analysis_settings_snapshot_dict(context)
    active_car_snapshot = _active_car_snapshot_dict(context)
    if active_car_snapshot is not None:
        metadata["active_car_snapshot"] = active_car_snapshot
    tire_circumference_m = context.tire_circumference_m
    if tire_circumference_m is not None or context.has_boundary_key("tire_circumference_m"):
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
    """Project diagnostics symptom metadata into the domain symptom object."""
    if not context.symptom_description:
        return Symptom.unspecified()
    return Symptom(
        description=context.symptom_description,
        onset=context.symptom_onset,
        context=context.symptom_context,
    )


def _analysis_settings_snapshot_dict(context: DiagnosticsContext) -> JsonObject:
    settings_dict = asdict(context.run_context.analysis_settings)
    return cast(
        JsonObject,
        {
            key: value
            for key, value in settings_dict.items()
            if isinstance(value, (int, float)) and math.isfinite(float(value))
        },
    )


def _active_car_snapshot_dict(context: DiagnosticsContext) -> JsonObject | None:
    car_snapshot = context.run_context.car
    if car_snapshot is None:
        return None
    return {
        "id": car_snapshot.car_id,
        "name": car_snapshot.name,
        "type": car_snapshot.car_type,
        "variant": car_snapshot.variant,
        "aspects": dict(car_snapshot.aspects),
    }
