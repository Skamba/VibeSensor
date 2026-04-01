"""Run-context orchestration helpers for recording and explicit history overlays."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict
from typing import cast

from vibesensor.domain import (
    AnalysisSettingsSnapshot,
    CarSnapshot,
    RunContextSnapshot,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.run_context_warning import (
    WARNING_CODE_CAR_SETTINGS_CHANGED,
    RunContextWarning,
    RunContextWarningsInput,
    normalize_run_context_warnings,
)
from vibesensor.shared.types.json_types import JsonObject, is_json_object


def build_run_context_snapshot(
    *,
    analysis_settings_snapshot: AnalysisSettingsSnapshot,
    active_car_snapshot: CarSnapshot | None,
) -> RunContextSnapshot:
    """Build the canonical typed run-context snapshot for the current run."""
    return RunContextSnapshot(
        analysis_settings=analysis_settings_snapshot,
        car=active_car_snapshot,
    )


def apply_run_context_snapshot(
    metadata: JsonObject,
    *,
    analysis_settings_snapshot: AnalysisSettingsSnapshot,
    active_car_snapshot: CarSnapshot | None,
) -> None:
    """Attach only the canonical structured run-context snapshot fields."""
    context_snapshot = build_run_context_snapshot(
        analysis_settings_snapshot=analysis_settings_snapshot,
        active_car_snapshot=active_car_snapshot,
    )
    metadata.update(cast(JsonObject, context_snapshot.to_metadata_dict()))


def apply_legacy_run_context_fields(
    metadata: JsonObject,
    *,
    context_snapshot: RunContextSnapshot,
) -> None:
    """Project legacy flat run-context fields from the canonical snapshot.

    This exists only for boundary compatibility when outward payloads still
    expect historical flat fields next to the canonical nested snapshot.
    """
    for key, value in _analysis_settings_values(context_snapshot.analysis_settings).items():
        if key in metadata or value != 0.0:
            metadata[key] = value
    if context_snapshot.has_car_context:
        metadata["active_car_id"] = context_snapshot.active_car_id
        metadata["car_name"] = context_snapshot.car_name
        metadata["car_type"] = context_snapshot.car_type
        metadata["car_variant"] = context_snapshot.car_variant


def run_context_snapshot_from_metadata(metadata: Mapping[str, object]) -> RunContextSnapshot:
    """Decode the canonical run-context snapshot from persisted metadata.

    Nested snapshot fields are authoritative when present. Legacy flat fields
    are only used as a compatibility fallback when the canonical nested fields
    are absent.
    """
    raw_settings = metadata.get("analysis_settings_snapshot")
    analysis_settings = (
        AnalysisSettingsSnapshot.from_dict(raw_settings)
        if isinstance(raw_settings, Mapping)
        else AnalysisSettingsSnapshot.from_dict(metadata)
    )

    raw_car = metadata.get("active_car_snapshot")
    car = (
        CarSnapshot.from_dict(raw_car)
        if isinstance(raw_car, Mapping)
        else _legacy_car_snapshot_from_metadata(
            metadata,
            analysis_settings=analysis_settings,
        )
    )
    return RunContextSnapshot(analysis_settings=analysis_settings, car=car)


def order_reference_context_complete(metadata: Mapping[str, object]) -> bool:
    """Return True when persisted run metadata is sufficient for order references."""
    raw_sample_rate_hz = _as_float(metadata.get("raw_sample_rate_hz"))
    order_reference_spec = run_context_snapshot_from_metadata(metadata).order_reference_spec
    tire_circumference_m = _as_float(metadata.get("tire_circumference_m"))
    if tire_circumference_m is None and order_reference_spec is not None:
        tire_circumference_m = order_reference_spec.tire_circumference_m
    has_engine_reference = _as_float(metadata.get("engine_rpm")) is not None or (
        order_reference_spec is not None and order_reference_spec.has_engine_reference
    )
    return bool(
        raw_sample_rate_hz
        and tire_circumference_m
        and order_reference_spec is not None
        and order_reference_spec.is_complete
        and has_engine_reference
    )


def add_current_context_warnings(
    warnings: RunContextWarningsInput,
    *,
    metadata: object,
    current_active_car_snapshot: CarSnapshot | None,
) -> list[RunContextWarning]:
    """Return warning models enriched with any current-context warning."""
    normalized = normalize_run_context_warnings(warnings)
    dynamic_warning = _build_car_settings_changed_warning(
        metadata,
        current_active_car_snapshot=current_active_car_snapshot,
    )
    if dynamic_warning is not None and dynamic_warning.code not in {
        warning.code for warning in normalized
    }:
        normalized.append(dynamic_warning)
    return normalized


def _build_car_settings_changed_warning(
    metadata: object,
    *,
    current_active_car_snapshot: CarSnapshot | None,
) -> RunContextWarning | None:
    if not is_json_object(metadata) or current_active_car_snapshot is None:
        return None
    recorded_snapshot_payload = metadata.get("active_car_snapshot")
    if not is_json_object(recorded_snapshot_payload):
        return None
    recorded_snapshot = CarSnapshot.from_dict(recorded_snapshot_payload)
    if _normalized_aspects(recorded_snapshot) == _normalized_aspects(current_active_car_snapshot):
        return None
    return RunContextWarning(
        code=WARNING_CODE_CAR_SETTINGS_CHANGED,
        severity="warn",
        applies_to="order_analysis",
        title={"_i18n_key": "RUN_CONTEXT_WARNING_CAR_SETTINGS_CHANGED_TITLE"},
        detail={
            "_i18n_key": "RUN_CONTEXT_WARNING_CAR_SETTINGS_CHANGED_DETAIL",
            "run_car": _car_label(recorded_snapshot),
            "current_car": _car_label(current_active_car_snapshot),
        },
    )


def _normalized_aspects(snapshot: CarSnapshot) -> tuple[tuple[str, float], ...]:
    normalized = [
        (key, numeric_value)
        for key, value in snapshot.aspects.items()
        if isinstance(key, str) and (numeric_value := _as_float(value)) is not None
    ]
    return tuple(sorted(normalized))


def _car_label(snapshot: CarSnapshot) -> str:
    name = str(snapshot.name or "").strip()
    car_type = str(snapshot.car_type or "").strip()
    if name and car_type:
        return f"{name} ({car_type})"
    if name:
        return name
    if car_type:
        return car_type
    return "captured vehicle profile"


def _analysis_settings_values(snapshot: AnalysisSettingsSnapshot) -> dict[str, float]:
    return {
        key: float(value)
        for key, value in asdict(snapshot).items()
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    }


def _legacy_car_snapshot_from_metadata(
    metadata: Mapping[str, object],
    *,
    analysis_settings: AnalysisSettingsSnapshot,
) -> CarSnapshot | None:
    car_id = _normalized_text(metadata.get("active_car_id") or metadata.get("car_id"))
    name = _normalized_text(metadata.get("car_name") or metadata.get("name"))
    car_type = _normalized_text(metadata.get("car_type"))
    variant = _normalized_text(metadata.get("car_variant") or metadata.get("variant"))
    if not any((car_id, name, car_type, variant)):
        return None
    return CarSnapshot(
        car_id=car_id,
        name=name,
        car_type=car_type,
        variant=variant,
        aspects={
            key: value
            for key, value in _analysis_settings_values(analysis_settings).items()
            if value != 0.0
        },
    )


def _normalized_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
