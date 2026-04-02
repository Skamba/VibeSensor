"""Decoding helpers for diagnostics context construction."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.shared.boundaries.run_metadata_codec import run_metadata_from_mapping
from vibesensor.shared.types.run_schema import RunMetadata

from ._context import DiagnosticsContext


def build_diagnostics_context(
    metadata: RunMetadata | Mapping[str, object],
    *,
    file_name: str = "run",
) -> DiagnosticsContext:
    """Build the canonical diagnostics context from one typed-or-boundary metadata input."""
    typed_metadata = (
        metadata if isinstance(metadata, RunMetadata) else run_metadata_from_mapping(metadata)
    )
    run_id = typed_metadata.run_id or f"run-{file_name}"
    return DiagnosticsContext(
        run_id=run_id,
        case_id=typed_metadata.case_id,
        sensor_mac=typed_metadata.sensor_mac,
        sensor_model=typed_metadata.sensor_model,
        firmware_version=typed_metadata.firmware_version,
        raw_sample_rate_hz=(
            float(typed_metadata.raw_sample_rate_hz)
            if typed_metadata.raw_sample_rate_hz is not None
            else None
        ),
        feature_interval_s=typed_metadata.feature_interval_s,
        summary_version=typed_metadata.summary_version,
        analysis_settings=typed_metadata.analysis_settings,
        car=typed_metadata.car,
        symptom=typed_metadata.symptom,
        start_time_utc=typed_metadata.start_time_utc or None,
        end_time_utc=typed_metadata.end_time_utc,
        report_date=typed_metadata.report_date,
        default_language=typed_metadata.language,
        fft_window_size_samples=typed_metadata.fft_window_size_samples,
        fft_window_type=typed_metadata.fft_window_type,
        peak_picker_method=typed_metadata.peak_picker_method,
        accel_scale_g_per_lsb=typed_metadata.accel_scale_g_per_lsb,
        incomplete_for_order_analysis=typed_metadata.incomplete_for_order_analysis,
        tire_circumference_m_override=typed_metadata.tire_circumference_m_override,
        explicit_engine_rpm=typed_metadata.explicit_engine_rpm,
        units=typed_metadata.units,
        amplitude_definitions=typed_metadata.amplitude_definitions,
    )
