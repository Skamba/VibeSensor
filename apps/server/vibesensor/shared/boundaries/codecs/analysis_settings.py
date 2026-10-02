"""Boundary codecs for ``AnalysisSettingsSnapshot``."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import fields
from typing import Any, cast

from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.shared.analysis_settings_schema import (
    ANALYSIS_SETTINGS_FIELDS,
    sanitize_analysis_settings,
)
from vibesensor.shared.boundaries.codecs.scalars import float_or
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.settings_types import (
    AnalysisSettingsPayload,
    analysis_settings_axle_from_mapping,
)

type ScalarSettingValue = int | float | bool | str
type ScalarSettings = tuple[tuple[str, ScalarSettingValue], ...]

_AXLE_KEY = "default_axle_for_speed"


def analysis_settings_snapshot_from_mapping(payload: object) -> AnalysisSettingsSnapshot:
    """Decode one raw mapping into a typed analysis-settings snapshot.

    Missing or non-numeric values fall back to the snapshot field defaults.
    """

    if not isinstance(payload, Mapping):
        return AnalysisSettingsSnapshot()
    values: dict[str, float | str] = {}
    for snapshot_field in fields(AnalysisSettingsSnapshot):
        raw = payload.get(snapshot_field.name)
        if snapshot_field.name == _AXLE_KEY:
            values[_AXLE_KEY] = analysis_settings_axle_from_mapping(raw) or "rear"
        else:
            values[snapshot_field.name] = float_or(raw, default=cast(float, snapshot_field.default))
    return AnalysisSettingsSnapshot(**cast(dict[str, Any], values))


def analysis_settings_snapshot_to_metadata(snapshot: AnalysisSettingsSnapshot) -> JsonObject:
    """Project a typed snapshot into the canonical persisted metadata shape."""

    metadata: JsonObject = {}
    has_axle_specific_tire_setup = any(
        value > 0.0
        for value in (
            snapshot.front_tire_width_mm,
            snapshot.front_tire_aspect_pct,
            snapshot.front_rim_in,
            snapshot.rear_tire_width_mm,
            snapshot.rear_tire_aspect_pct,
            snapshot.rear_rim_in,
        )
    )
    for key, value in _analysis_settings_values(snapshot):
        if isinstance(value, str):
            if has_axle_specific_tire_setup:
                metadata[key] = value
            continue
        if (
            key
            in {
                "front_tire_width_mm",
                "front_tire_aspect_pct",
                "front_rim_in",
                "rear_tire_width_mm",
                "rear_tire_aspect_pct",
                "rear_rim_in",
            }
            and value <= 0.0
        ):
            continue
        if math.isfinite(float(value)):
            metadata[key] = value
    return metadata


def analysis_settings_snapshot_items(snapshot: AnalysisSettingsSnapshot) -> ScalarSettings:
    """Flatten the canonical snapshot into ordered scalar key/value pairs."""

    metadata = analysis_settings_snapshot_to_metadata(snapshot)
    default_values = analysis_settings_snapshot_to_metadata(AnalysisSettingsSnapshot())
    items: list[tuple[str, ScalarSettingValue]] = []
    for key, value in metadata.items():
        if default_values.get(key) != value and isinstance(value, bool | int | float | str):
            items.append((key, value))
    return tuple(sorted(items))


def _analysis_settings_values(
    snapshot: AnalysisSettingsSnapshot,
) -> tuple[tuple[str, float | str], ...]:
    # Payload field order keeps persisted metadata keys in their historical order.
    return tuple((key, getattr(snapshot, key)) for key in AnalysisSettingsPayload.__annotations__)


__all__ = [
    "ScalarSettingValue",
    "ScalarSettings",
    "ANALYSIS_SETTINGS_FIELDS",
    "analysis_settings_snapshot_from_mapping",
    "analysis_settings_snapshot_items",
    "analysis_settings_snapshot_to_metadata",
    "sanitize_analysis_settings",
]
