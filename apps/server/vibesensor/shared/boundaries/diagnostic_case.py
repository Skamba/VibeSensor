"""Decode persisted diagnostic summaries into domain DiagnosticCase models."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import Car, OrderReferenceSpec
from vibesensor.domain.diagnostic_case import DiagnosticCase, Symptom
from vibesensor.shared.boundaries.run_metadata_codec import run_metadata_from_mapping
from vibesensor.shared.boundaries import test_run_reconstruction as _test_run_reconstruction
from vibesensor.shared.boundaries.car_snapshot_codec import car_snapshot_from_mapping
from vibesensor.shared.types.run_schema import RunMetadata


def _require_authoritative_case_id(summary: Mapping[str, object]) -> str:
    case_id = summary.get("case_id")
    if isinstance(case_id, str):
        normalized_case_id = case_id.strip()
        if normalized_case_id:
            return normalized_case_id
    raise ValueError("Cannot decode DiagnosticCase from summary without authoritative case_id")


def diagnostic_case_from_summary(summary: Mapping[str, object]) -> DiagnosticCase:
    metadata = summary.get("metadata")
    meta = metadata if isinstance(metadata, Mapping) else {}
    car = car_from_metadata(meta)
    symptoms = (symptom_from_metadata(meta),)
    test_run = _test_run_reconstruction.test_run_from_summary(summary)
    case = DiagnosticCase(
        case_id=_require_authoritative_case_id(summary),
        car=car,
        symptoms=symptoms,
        test_plan=test_run.test_plan,
    )
    return case.add_run(test_run)


def car_from_metadata(metadata: RunMetadata | Mapping[str, object]) -> Car | None:
    """Build optional case-scoped car context from canonical run metadata."""

    if isinstance(metadata, RunMetadata):
        snapshot = metadata.car
        order_reference_spec = metadata.order_reference_spec
    else:
        snapshot = car_snapshot_from_mapping(metadata.get("active_car_snapshot"))
        raw_settings = metadata.get("analysis_settings_snapshot")
        if isinstance(raw_settings, Mapping):
            order_reference_spec = OrderReferenceSpec.from_settings(raw_settings)
        elif snapshot is not None and snapshot.aspects:
            order_reference_spec = OrderReferenceSpec.from_settings(snapshot.aspects)
        else:
            order_reference_spec = None

    if snapshot is None and order_reference_spec is None:
        return None
    return Car(
        id=snapshot.car_id if snapshot is not None else None,
        name=snapshot.name if snapshot is not None and snapshot.name else "Unnamed Car",
        car_type=snapshot.car_type if snapshot is not None and snapshot.car_type else "sedan",
        aspects=snapshot.aspects if snapshot is not None and snapshot.aspects else None,
        variant=snapshot.variant if snapshot is not None else None,
        order_reference_spec=order_reference_spec,
    )


def symptom_from_metadata(metadata: RunMetadata | Mapping[str, object]) -> Symptom:
    """Build case symptom context from run metadata at a boundary seam."""
    if isinstance(metadata, RunMetadata):
        return metadata.symptom if metadata.symptom is not None else Symptom.unspecified()
    typed_metadata = run_metadata_from_mapping(metadata)
    return typed_metadata.symptom if typed_metadata.symptom is not None else Symptom.unspecified()
