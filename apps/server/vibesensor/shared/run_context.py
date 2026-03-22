"""Run-context snapshot and trust-warning helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

from vibesensor.domain import (
    AnalysisSettingsSnapshot,
    CarSnapshot,
    OrderReferenceSpec,
    RunContextSnapshot,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.json_utils import i18n_ref
from vibesensor.shared.types.json_types import JsonObject, JsonValue, is_json_object

WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE = "reference_context_incomplete"
WARNING_CODE_CAR_SETTINGS_CHANGED = "car_settings_changed"
WarningSeverity = Literal["warn", "error"]


@dataclass(frozen=True, slots=True)
class RunContextWarning:
    """App-level warning model shared by diagnostics and history workflows."""

    code: str
    severity: WarningSeverity
    applies_to: str
    title: JsonValue
    detail: JsonValue | None = None


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
    """Attach structured run-context snapshot fields to persisted metadata."""
    context_snapshot = build_run_context_snapshot(
        analysis_settings_snapshot=analysis_settings_snapshot,
        active_car_snapshot=active_car_snapshot,
    )
    metadata.update(cast(JsonObject, context_snapshot.to_metadata_dict()))
    if context_snapshot.has_car_context:
        metadata["active_car_id"] = context_snapshot.active_car_id
        metadata["car_name"] = context_snapshot.car_name
        metadata["car_type"] = context_snapshot.car_type
        metadata["car_variant"] = context_snapshot.car_variant


def order_reference_context_complete(metadata: Mapping[str, object]) -> bool:
    """Return True when persisted run metadata is sufficient for order references."""
    raw_sample_rate_hz = _as_float(metadata.get("raw_sample_rate_hz"))
    order_reference_spec = OrderReferenceSpec.from_settings(metadata)
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


def build_summary_warnings(
    metadata: Mapping[str, object],
    *,
    reference_complete: bool,
) -> list[RunContextWarning]:
    """Build language-neutral trust warnings stored with the analysis summary."""
    warnings: list[RunContextWarning] = []
    if not reference_complete or bool(metadata.get("incomplete_for_order_analysis")):
        warnings.append(
            RunContextWarning(
                code=WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
                severity="warn",
                applies_to="order_analysis",
                title=i18n_ref("RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"),
                detail=i18n_ref("RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"),
            )
        )
    return warnings


def add_current_context_warnings(
    warnings: object,
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


def current_car_snapshot_token(current_active_car_snapshot: CarSnapshot | None) -> str:
    """Return a stable cache token for current active-car context."""
    return json.dumps(
        current_active_car_snapshot.to_dict() if current_active_car_snapshot else {},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )


def _build_car_settings_changed_warning(
    metadata: object,
    *,
    current_active_car_snapshot: CarSnapshot | None,
) -> RunContextWarning | None:
    if not is_json_object(metadata) or current_active_car_snapshot is None:
        return None
    recorded_snapshot = metadata.get("active_car_snapshot")
    if not is_json_object(recorded_snapshot):
        return None
    current_dict = current_active_car_snapshot.to_dict()
    if _normalized_aspects(recorded_snapshot) == _normalized_aspects(current_dict):
        return None
    return RunContextWarning(
        code=WARNING_CODE_CAR_SETTINGS_CHANGED,
        severity="warn",
        applies_to="order_analysis",
        title=i18n_ref("RUN_CONTEXT_WARNING_CAR_SETTINGS_CHANGED_TITLE"),
        detail=i18n_ref(
            "RUN_CONTEXT_WARNING_CAR_SETTINGS_CHANGED_DETAIL",
            run_car=_car_label(recorded_snapshot),
            current_car=_car_label(current_dict),
        ),
    )


def normalize_run_context_warnings(warnings: object) -> list[RunContextWarning]:
    if not isinstance(warnings, list):
        return []
    normalized: list[RunContextWarning] = []
    for warning in warnings:
        if isinstance(warning, RunContextWarning):
            normalized.append(warning)
            continue
        if not is_json_object(warning):
            continue
        normalized.append(
            RunContextWarning(
                code=str(warning.get("code") or ""),
                severity=cast(WarningSeverity, str(warning.get("severity") or "warn")),
                applies_to=str(warning.get("applies_to") or "order_analysis"),
                title=warning.get("title"),
                detail=warning.get("detail"),
            )
        )
    return normalized


def _normalized_aspects(snapshot: Mapping[str, object]) -> tuple[tuple[str, float], ...]:
    aspects_raw = snapshot.get("aspects")
    if not isinstance(aspects_raw, Mapping):
        return ()
    normalized = [
        (key, float(value))
        for key, value in aspects_raw.items()
        if isinstance(key, str) and _as_float(value) is not None
    ]
    return tuple(sorted(normalized))


def _car_label(snapshot: Mapping[str, object]) -> str:
    name = str(snapshot.get("name") or "").strip()
    car_type = str(snapshot.get("type") or "").strip()
    if name and car_type:
        return f"{name} ({car_type})"
    if name:
        return name
    if car_type:
        return car_type
    return "captured vehicle profile"
