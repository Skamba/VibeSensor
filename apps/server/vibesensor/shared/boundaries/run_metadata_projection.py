"""Canonical projections from typed run metadata into domain and boundary models."""

from __future__ import annotations

from vibesensor.domain import Car, ConfigurationSnapshot, Symptom
from vibesensor.shared.types.run_schema import RunMetadata

__all__ = [
    "car_from_run_metadata",
    "configuration_snapshot_from_run_metadata",
    "symptom_from_run_metadata",
]


def configuration_snapshot_from_run_metadata(
    metadata: RunMetadata,
) -> ConfigurationSnapshot:
    """Project canonical run metadata into run-capture configuration context."""

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


def car_from_run_metadata(metadata: RunMetadata) -> Car | None:
    """Build case-scoped car context from canonical run metadata only."""

    snapshot = metadata.car
    order_reference_spec = metadata.order_reference_spec
    if snapshot is None and order_reference_spec is None:
        return None
    return Car(
        id=metadata.active_car_id,
        name=metadata.car_name or "Unnamed Car",
        car_type=metadata.car_type or "sedan",
        aspects=snapshot.aspects if snapshot is not None else None,
        variant=metadata.car_variant,
        order_reference_spec=order_reference_spec,
    )


def symptom_from_run_metadata(metadata: RunMetadata) -> Symptom:
    """Build case symptom context from canonical run metadata."""

    return metadata.symptom if metadata.symptom is not None else Symptom.unspecified()


def _non_empty_text(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() == "unknown":
        return None
    return text
