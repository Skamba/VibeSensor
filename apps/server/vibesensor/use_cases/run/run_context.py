"""Run-context helpers for recording metadata and current-context warnings."""

from __future__ import annotations

from collections.abc import Mapping

from vibesensor.domain import AnalysisSettingsSnapshot, CarSnapshot, RunContextSnapshot
from vibesensor.shared.boundaries.run_metadata_codec import run_metadata_from_mapping
from vibesensor.shared.run_context_warning import (
    WARNING_CODE_CAR_SETTINGS_CHANGED,
    RunContextWarning,
    RunContextWarningsInput,
    normalize_run_context_warnings,
)
from vibesensor.shared.types.json_types import is_json_object
from vibesensor.shared.types.run_schema import RunMetadata


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


def order_reference_context_complete(metadata: RunMetadata) -> bool:
    """Return True when typed run metadata is sufficient for order references."""
    raw_sample_rate_hz = metadata.raw_sample_rate_hz
    order_reference_spec = metadata.order_reference_spec
    tire_circumference_m = metadata.tire_circumference_m
    has_engine_reference = metadata.explicit_engine_rpm is not None or (
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
    metadata: RunMetadata | Mapping[str, object] | object,
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
    metadata: RunMetadata | Mapping[str, object] | object,
    *,
    current_active_car_snapshot: CarSnapshot | None,
) -> RunContextWarning | None:
    if current_active_car_snapshot is None:
        return None
    if isinstance(metadata, RunMetadata):
        recorded_snapshot = metadata.car
    elif is_json_object(metadata):
        recorded_snapshot = run_metadata_from_mapping(metadata).car
    else:
        return None
    if recorded_snapshot is None:
        return None
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
        (str(key), float(value))
        for key, value in snapshot.aspects.items()
        if isinstance(key, str) and isinstance(value, (int, float))
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
