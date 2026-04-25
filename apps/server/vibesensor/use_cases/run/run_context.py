"""Run-context helpers for recording metadata and current-context warnings."""

from __future__ import annotations

from vibesensor.domain import AnalysisSettingsSnapshot, CarSnapshot, RunContextSnapshot
from vibesensor.shared.order_reference_settings import (
    order_reference_mapping_from_spec,
    order_reference_spec_from_mapping,
)
from vibesensor.shared.run_context_warning import (
    WARNING_CODE_CAR_SETTINGS_CHANGED,
    RunContextWarning,
    RunContextWarningsInput,
    normalize_run_context_warnings,
)
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
    return bool(
        raw_sample_rate_hz
        and tire_circumference_m
        and order_reference_spec is not None
        and order_reference_spec.is_complete
        and order_reference_spec.has_engine_reference
    )


def add_current_context_warnings(
    warnings: RunContextWarningsInput,
    *,
    metadata: RunMetadata | None,
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
    metadata: RunMetadata | None,
    *,
    current_active_car_snapshot: CarSnapshot | None,
) -> RunContextWarning | None:
    if current_active_car_snapshot is None or metadata is None:
        return None
    recorded_car = metadata.car
    recorded_settings = _normalized_recorded_order_reference(metadata)
    if recorded_car is None:
        return None
    if recorded_settings == _normalized_current_car_settings(current_active_car_snapshot):
        return None
    return RunContextWarning(
        code=WARNING_CODE_CAR_SETTINGS_CHANGED,
        severity="warn",
        applies_to="order_analysis",
        title={"_i18n_key": "RUN_CONTEXT_WARNING_CAR_SETTINGS_CHANGED_TITLE"},
        detail={
            "_i18n_key": "RUN_CONTEXT_WARNING_CAR_SETTINGS_CHANGED_DETAIL",
            "run_car": _car_label(recorded_car.name, recorded_car.car_type),
            "current_car": _car_label(
                current_active_car_snapshot.name,
                current_active_car_snapshot.car_type,
            ),
        },
    )


def _normalized_recorded_order_reference(
    metadata: RunMetadata,
) -> tuple[tuple[str, float | str], ...]:
    spec = metadata.order_reference_spec
    if spec is None:
        return ()
    return tuple(sorted(order_reference_mapping_from_spec(spec).items()))


def _normalized_current_car_settings(
    snapshot: CarSnapshot,
) -> tuple[tuple[str, float | str], ...]:
    spec = order_reference_spec_from_mapping(snapshot.aspects)
    if spec is None:
        return ()
    return tuple(sorted(order_reference_mapping_from_spec(spec).items()))


def _car_label(name_value: str | None, car_type_value: str | None) -> str:
    name = str(name_value or "").strip()
    car_type = str(car_type_value or "").strip()
    if name and car_type:
        return f"{name} ({car_type})"
    if name:
        return name
    if car_type:
        return car_type
    return "captured vehicle profile"
