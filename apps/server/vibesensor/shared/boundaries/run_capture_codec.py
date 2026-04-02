"""Boundary codecs for run-capture setup snapshots."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import ConfigurationSnapshot
from vibesensor.shared.boundaries.run_metadata_codec import run_metadata_from_mapping
from vibesensor.shared.types.run_schema import RunMetadata


def _configuration_snapshot_from_run_metadata(metadata: RunMetadata) -> ConfigurationSnapshot:
    order_reference_spec = metadata.order_reference_spec
    return ConfigurationSnapshot(
        sensor_model=_non_empty_text(metadata.sensor_model),
        firmware_version=_non_empty_text(metadata.firmware_version),
        raw_sample_rate_hz=(
            float(metadata.raw_sample_rate_hz) if metadata.raw_sample_rate_hz is not None else None
        ),
        feature_interval_s=metadata.feature_interval_s,
        final_drive_ratio=metadata.final_drive_ratio,
        tire_spec=order_reference_spec.tire_spec if order_reference_spec is not None else None,
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
def _non_empty_text(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() == "unknown":
        return None
    return text
