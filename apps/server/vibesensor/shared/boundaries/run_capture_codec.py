"""Boundary codecs for run-capture setup snapshots."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import ConfigurationSnapshot, TireSpec
from vibesensor.shared.boundaries.analysis_settings_snapshot_codec import (
    analysis_settings_snapshot_to_metadata,
)
from vibesensor.shared.boundaries.run_metadata_codec import run_metadata_from_mapping
from vibesensor.shared.json_utils import as_float_or_none
from vibesensor.shared.types.run_schema import RunMetadata


def _configuration_snapshot_from_run_metadata(metadata: RunMetadata) -> ConfigurationSnapshot:
    settings_payload = analysis_settings_snapshot_to_metadata(metadata.analysis_settings)

    tire_spec = TireSpec.from_aspects(
        {
            key: coerced
            for key in ("tire_width_mm", "tire_aspect_pct", "rim_in")
            if (value := settings_payload.get(key)) is not None
            if (coerced := _coerce_float(value)) is not None
        },
        deflection_factor=metadata.analysis_settings.tire_deflection_factor or 1.0,
    )
    return ConfigurationSnapshot(
        sensor_model=_non_empty_text(metadata.sensor_model),
        firmware_version=_non_empty_text(metadata.firmware_version),
        raw_sample_rate_hz=(
            float(metadata.raw_sample_rate_hz) if metadata.raw_sample_rate_hz is not None else None
        ),
        feature_interval_s=metadata.feature_interval_s,
        final_drive_ratio=metadata.analysis_settings.final_drive_ratio or None,
        tire_spec=tire_spec,
    )


def configuration_snapshot_from_metadata(
    metadata: RunMetadata | Mapping[str, object],
) -> ConfigurationSnapshot:
    """Decode raw or typed run metadata into the domain configuration snapshot."""

    typed_metadata = (
        metadata if isinstance(metadata, RunMetadata) else run_metadata_from_mapping(metadata)
    )
    return _configuration_snapshot_from_run_metadata(typed_metadata)


def configuration_snapshot_from_run_metadata(metadata: RunMetadata) -> ConfigurationSnapshot:
    """Project typed run metadata into the domain configuration snapshot."""

    return _configuration_snapshot_from_run_metadata(metadata)


def _coerce_float(value: object) -> float | None:
    return as_float_or_none(value)


def _non_empty_text(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() == "unknown":
        return None
    return text
