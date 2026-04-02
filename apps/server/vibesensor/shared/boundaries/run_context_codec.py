"""Boundary codecs for persisted run-context and metadata snapshots."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict

from vibesensor.domain import (
    AnalysisSettingsSnapshot,
    CarSnapshot,
    RunContextSnapshot,
    RunMetadataSnapshot,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.types.json_types import JsonObject


def run_context_snapshot_from_metadata(metadata: Mapping[str, object]) -> RunContextSnapshot:
    """Decode the canonical nested run-context snapshot from persisted metadata."""

    raw_settings = metadata.get("analysis_settings_snapshot")
    settings = (
        AnalysisSettingsSnapshot.from_dict(raw_settings)
        if isinstance(raw_settings, Mapping)
        else AnalysisSettingsSnapshot()
    )
    raw_car = metadata.get("active_car_snapshot")
    car = CarSnapshot.from_dict(raw_car) if isinstance(raw_car, Mapping) else None
    return RunContextSnapshot(analysis_settings=settings, car=car)


def run_context_snapshot_to_metadata(snapshot: RunContextSnapshot) -> JsonObject:
    """Project a typed run-context snapshot back to the canonical metadata shape."""

    settings_dict = asdict(snapshot.analysis_settings)
    metadata: JsonObject = {
        "analysis_settings_snapshot": {
            key: value
            for key, value in settings_dict.items()
            if isinstance(value, (int, float)) and math.isfinite(float(value))
        },
    }
    if snapshot.car is not None:
        metadata["active_car_snapshot"] = {
            "id": snapshot.car.car_id,
            "name": snapshot.car.name,
            "type": snapshot.car.car_type,
            "variant": snapshot.car.variant,
            "aspects": dict(snapshot.car.aspects),
        }
    return metadata


def run_metadata_snapshot_from_metadata(
    metadata: Mapping[str, object],
    *,
    fallback_run_id: str | None = None,
) -> RunMetadataSnapshot:
    """Decode the diagnostics-owned metadata snapshot from persisted metadata."""

    run_id = _non_empty_text(metadata.get("run_id")) or _non_empty_text(
        metadata.get("recording_id")
    )
    if run_id is None:
        run_id = fallback_run_id or ""
    return RunMetadataSnapshot(
        run_id=run_id,
        case_id=_non_empty_text(metadata.get("case_id")) or "",
        sensor_mac=_non_empty_text(metadata.get("sensor_mac")),
        sensor_model=_non_empty_text(metadata.get("sensor_model")),
        firmware_version=_non_empty_text(metadata.get("firmware_version")),
        raw_sample_rate_hz=_as_float(metadata.get("raw_sample_rate_hz")),
        feature_interval_s=_as_float(metadata.get("feature_interval_s")),
        summary_version=_as_int(metadata.get("_summary_version")) or 1,
    )


def _non_empty_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None
