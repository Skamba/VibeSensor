"""Canonical projections from typed run metadata into domain models."""

from __future__ import annotations

from vibesensor.domain import Car, Symptom
from vibesensor.shared.types.run_schema import RunMetadata

__all__ = [
    "car_from_run_metadata",
    "symptom_from_run_metadata",
]


def car_from_run_metadata(metadata: RunMetadata) -> Car | None:
    """Build case-scoped car context from canonical run metadata only."""

    run_car = metadata.car
    order_reference_spec = metadata.order_reference_spec
    if run_car is None and order_reference_spec is None:
        return None
    return Car(
        id=metadata.active_car_id,
        name=metadata.car_name or "Unnamed Car",
        car_type=metadata.car_type or "sedan",
        variant=metadata.car_variant,
        order_reference_spec=order_reference_spec,
    )


def symptom_from_run_metadata(metadata: RunMetadata) -> Symptom:
    """Build case symptom context from canonical run metadata."""

    return metadata.symptom if metadata.symptom is not None else Symptom.unspecified()
