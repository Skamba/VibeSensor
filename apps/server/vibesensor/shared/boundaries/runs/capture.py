"""Boundary codecs for run-capture setup snapshots."""

from __future__ import annotations

from vibesensor.domain import ConfigurationSnapshot
from vibesensor.shared.types.run_schema import RunMetadata


def _configuration_snapshot_from_run_metadata(metadata: RunMetadata) -> ConfigurationSnapshot:
    order_reference_spec = metadata.order_reference_spec
    return ConfigurationSnapshot(
        sensor_model=_non_empty_text(metadata.sensor_model),
        firmware_version=_non_empty_text(metadata.firmware_version),
        strength_algorithm_version=_non_empty_text(metadata.strength_algorithm_version),
        peak_detector_version=_non_empty_text(metadata.peak_detector_version),
        calibration_profile_id=_non_empty_text(metadata.calibration_profile_id),
        vehicle_baseline_profile_id=_non_empty_text(metadata.vehicle_baseline_profile_id),
        raw_sample_rate_hz=(
            float(metadata.raw_sample_rate_hz) if metadata.raw_sample_rate_hz is not None else None
        ),
        feature_interval_s=metadata.feature_interval_s,
        final_drive_ratio=metadata.final_drive_ratio,
        tire_spec=order_reference_spec.tire_spec if order_reference_spec is not None else None,
    )


def configuration_snapshot_from_metadata(
    metadata: RunMetadata,
) -> ConfigurationSnapshot:
    """Project typed run metadata into the domain configuration snapshot."""

    if not isinstance(metadata, RunMetadata):
        raise TypeError(
            "configuration_snapshot_from_metadata expects RunMetadata, "
            f"got {type(metadata).__name__}"
        )
    return _configuration_snapshot_from_run_metadata(metadata)


def configuration_snapshot_from_run_metadata(metadata: RunMetadata) -> ConfigurationSnapshot:
    """Project typed run metadata into the domain configuration snapshot."""

    return _configuration_snapshot_from_run_metadata(metadata)


def _non_empty_text(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text or text.lower() == "unknown":
        return None
    return text
