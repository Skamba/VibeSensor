"""Boundary codecs for persisted run-context snapshots."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import (
    RunContextSnapshot,
)
from vibesensor.shared.boundaries.analysis_settings_snapshot_codec import (
    analysis_settings_snapshot_from_mapping,
    analysis_settings_snapshot_to_metadata,
)
from vibesensor.shared.boundaries.car_snapshot_codec import (
    car_snapshot_from_mapping,
    car_snapshot_to_metadata,
)
from vibesensor.shared.types.json_types import JsonObject


def run_context_snapshot_from_metadata(metadata: Mapping[str, object]) -> RunContextSnapshot:
    """Decode the canonical nested run-context snapshot from persisted metadata."""

    settings = analysis_settings_snapshot_from_mapping(metadata.get("analysis_settings_snapshot"))
    car = car_snapshot_from_mapping(metadata.get("active_car_snapshot"))
    return RunContextSnapshot(analysis_settings=settings, car=car)


def run_context_snapshot_to_metadata(snapshot: RunContextSnapshot) -> JsonObject:
    """Project a typed run-context snapshot back to the canonical metadata shape."""

    metadata: JsonObject = {
        "analysis_settings_snapshot": analysis_settings_snapshot_to_metadata(
            snapshot.analysis_settings,
        ),
    }
    if (car_metadata := car_snapshot_to_metadata(snapshot.car)) is not None:
        metadata["active_car_snapshot"] = car_metadata
    return metadata
