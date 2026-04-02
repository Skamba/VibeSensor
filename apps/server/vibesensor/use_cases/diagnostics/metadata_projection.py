"""Focused projections from canonical run metadata into other typed boundaries."""

from __future__ import annotations

from vibesensor.domain import Car, ConfigurationSnapshot, Symptom, TireSpec
from vibesensor.shared.boundaries.analysis_settings_snapshot_codec import (
    ScalarSettings,
    analysis_settings_snapshot_items,
)
from vibesensor.shared.order_reference_settings import order_reference_mapping_from_spec
from vibesensor.shared.types.run_schema import RunMetadata

__all__ = [
    "metadata_analysis_settings_items",
    "metadata_car",
    "metadata_configuration_snapshot",
    "metadata_symptom",
]


def metadata_analysis_settings_items(metadata: RunMetadata) -> ScalarSettings:
    """Flatten analysis settings only at the test-run/report boundary."""

    return analysis_settings_snapshot_items(metadata.analysis_settings)


def metadata_configuration_snapshot(metadata: RunMetadata) -> ConfigurationSnapshot:
    """Project canonical run metadata into the run-capture configuration boundary."""

    settings = metadata.analysis_settings
    tire_spec = TireSpec.from_aspects(
        {
            key: value
            for key in ("tire_width_mm", "tire_aspect_pct", "rim_in")
            if (value := _positive_float(getattr(settings, key))) is not None
        },
        deflection_factor=settings.tire_deflection_factor or 1.0,
    )
    return ConfigurationSnapshot(
        sensor_model=_non_empty_text(metadata.sensor_model),
        firmware_version=_non_empty_text(metadata.firmware_version),
        raw_sample_rate_hz=(
            float(metadata.raw_sample_rate_hz) if metadata.raw_sample_rate_hz is not None else None
        ),
        feature_interval_s=metadata.feature_interval_s,
        final_drive_ratio=metadata.final_drive_ratio,
        tire_spec=tire_spec,
    )


def metadata_car(metadata: RunMetadata) -> Car | None:
    """Build case-scoped car context from canonical run metadata."""

    snapshot = metadata.car
    order_reference_spec = metadata.order_reference_spec
    if snapshot is None and order_reference_spec is None:
        return None
    return Car(
        id=metadata.active_car_id,
        name=metadata.car_name or "Unnamed Car",
        car_type=metadata.car_type or "sedan",
        aspects=(
            snapshot.aspects
            if snapshot is not None and snapshot.aspects
            else (
                order_reference_mapping_from_spec(order_reference_spec)
                if order_reference_spec is not None
                else None
            )
        ),
        variant=metadata.car_variant,
        order_reference_spec=order_reference_spec,
    )


def metadata_symptom(metadata: RunMetadata) -> Symptom:
    """Build a case symptom from canonical run metadata."""

    return metadata.symptom if metadata.symptom is not None else Symptom.unspecified()


def _non_empty_text(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() == "unknown":
        return None
    return text


def _positive_float(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        numeric = float(value)
        return numeric if numeric > 0 else None
    return None
