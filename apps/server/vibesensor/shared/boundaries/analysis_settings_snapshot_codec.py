"""Boundary codecs for ``AnalysisSettingsSnapshot``."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping

from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.shared.analysis_settings_schema import (
    ANALYSIS_SETTINGS_FIELDS,
    sanitize_analysis_settings,
)
from vibesensor.shared.types.json_types import JsonObject

type ScalarSettingValue = int | float | bool | str
type ScalarSettings = tuple[tuple[str, ScalarSettingValue], ...]

_ANALYSIS_SETTINGS_PAIRS: tuple[
    tuple[str, Callable[[AnalysisSettingsSnapshot], float]],
    ...,
] = (
    ("tire_width_mm", lambda snapshot: snapshot.tire_width_mm),
    ("tire_aspect_pct", lambda snapshot: snapshot.tire_aspect_pct),
    ("rim_in", lambda snapshot: snapshot.rim_in),
    ("final_drive_ratio", lambda snapshot: snapshot.final_drive_ratio),
    ("current_gear_ratio", lambda snapshot: snapshot.current_gear_ratio),
    ("wheel_bandwidth_pct", lambda snapshot: snapshot.wheel_bandwidth_pct),
    ("driveshaft_bandwidth_pct", lambda snapshot: snapshot.driveshaft_bandwidth_pct),
    ("engine_bandwidth_pct", lambda snapshot: snapshot.engine_bandwidth_pct),
    ("speed_uncertainty_pct", lambda snapshot: snapshot.speed_uncertainty_pct),
    (
        "tire_diameter_uncertainty_pct",
        lambda snapshot: snapshot.tire_diameter_uncertainty_pct,
    ),
    (
        "final_drive_uncertainty_pct",
        lambda snapshot: snapshot.final_drive_uncertainty_pct,
    ),
    ("gear_uncertainty_pct", lambda snapshot: snapshot.gear_uncertainty_pct),
    ("min_abs_band_hz", lambda snapshot: snapshot.min_abs_band_hz),
    ("max_band_half_width_pct", lambda snapshot: snapshot.max_band_half_width_pct),
    ("tire_deflection_factor", lambda snapshot: snapshot.tire_deflection_factor),
)


def analysis_settings_snapshot_from_mapping(payload: object) -> AnalysisSettingsSnapshot:
    """Decode one raw mapping into a typed analysis-settings snapshot."""

    if not isinstance(payload, Mapping):
        return AnalysisSettingsSnapshot()
    return AnalysisSettingsSnapshot(
        tire_width_mm=_float_or(payload.get("tire_width_mm")),
        tire_aspect_pct=_float_or(payload.get("tire_aspect_pct")),
        rim_in=_float_or(payload.get("rim_in")),
        final_drive_ratio=_float_or(payload.get("final_drive_ratio")),
        current_gear_ratio=_float_or(payload.get("current_gear_ratio")),
        wheel_bandwidth_pct=_float_or(payload.get("wheel_bandwidth_pct")),
        driveshaft_bandwidth_pct=_float_or(payload.get("driveshaft_bandwidth_pct")),
        engine_bandwidth_pct=_float_or(payload.get("engine_bandwidth_pct")),
        speed_uncertainty_pct=_float_or(payload.get("speed_uncertainty_pct")),
        tire_diameter_uncertainty_pct=_float_or(payload.get("tire_diameter_uncertainty_pct")),
        final_drive_uncertainty_pct=_float_or(payload.get("final_drive_uncertainty_pct")),
        gear_uncertainty_pct=_float_or(payload.get("gear_uncertainty_pct")),
        min_abs_band_hz=_float_or(payload.get("min_abs_band_hz")),
        max_band_half_width_pct=_float_or(payload.get("max_band_half_width_pct")),
        tire_deflection_factor=_float_or(payload.get("tire_deflection_factor"), default=1.0),
    )


def analysis_settings_snapshot_to_metadata(snapshot: AnalysisSettingsSnapshot) -> JsonObject:
    """Project a typed snapshot into the canonical persisted metadata shape."""

    metadata: JsonObject = {}
    for key, value in _analysis_settings_values(snapshot):
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
) -> tuple[tuple[str, float], ...]:
    return tuple((key, read_value(snapshot)) for key, read_value in _ANALYSIS_SETTINGS_PAIRS)


def _float_or(value: object, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else default
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            numeric = float(text)
        except ValueError:
            return default
        return numeric if math.isfinite(numeric) else default
    return default


__all__ = [
    "ScalarSettingValue",
    "ScalarSettings",
    "ANALYSIS_SETTINGS_FIELDS",
    "analysis_settings_snapshot_from_mapping",
    "analysis_settings_snapshot_items",
    "analysis_settings_snapshot_to_metadata",
    "sanitize_analysis_settings",
]
