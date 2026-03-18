"""Run-context snapshot and trust-warning helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast

from vibesensor.domain import (
    AnalysisSettingsSnapshot,
    CarSnapshot,
    OrderReferenceSpec,
    RunContextSnapshot,
)
from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.json_utils import i18n_ref
from vibesensor.shared.types.json_types import JsonObject, JsonValue, is_json_object

WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE = "reference_context_incomplete"
WARNING_CODE_CAR_SETTINGS_CHANGED = "car_settings_changed"


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
    metadata.update(context_snapshot.to_metadata_dict())
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
) -> list[JsonObject]:
    """Build language-neutral trust warnings stored with the analysis summary."""
    warnings: list[JsonObject] = []
    if not reference_complete or bool(metadata.get("incomplete_for_order_analysis")):
        warnings.append(
            {
                "code": WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE,
                "severity": "warn",
                "applies_to": "order_analysis",
                "title": i18n_ref("RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_TITLE"),
                "detail": i18n_ref("RUN_CONTEXT_WARNING_REFERENCE_INCOMPLETE_DETAIL"),
            },
        )
    return warnings


def add_current_context_warnings(
    summary: Mapping[str, JsonValue],
    *,
    current_active_car_snapshot: CarSnapshot | None,
) -> JsonObject:
    """Return a summary copy enriched with dynamic current-context warnings."""
    enriched = dict(summary)
    warnings = _normalized_warning_list(enriched.get("warnings"))
    dynamic_warning = _build_car_settings_changed_warning(
        enriched.get("metadata"),
        current_active_car_snapshot=current_active_car_snapshot,
    )
    if dynamic_warning is not None and dynamic_warning["code"] not in {
        str(item.get("code") or "") for item in warnings
    }:
        warnings.append(dynamic_warning)
    enriched["warnings"] = list(warnings)
    return enriched


def localize_warning_list(
    warnings: object,
    *,
    lang: str,
) -> list[JsonObject]:
    """Resolve language-neutral warning entries into response-ready text."""
    localized: list[JsonObject] = []
    for warning in _normalized_warning_list(warnings):
        localized.append(
            {
                "code": str(warning.get("code") or ""),
                "severity": str(warning.get("severity") or "warn"),
                "applies_to": str(warning.get("applies_to") or "order_analysis"),
                "title": _resolve_i18n(lang, warning.get("title")),
                "detail": _resolve_optional_i18n(lang, warning.get("detail")),
            },
        )
    return localized


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
) -> JsonObject | None:
    if not is_json_object(metadata) or current_active_car_snapshot is None:
        return None
    recorded_snapshot = metadata.get("active_car_snapshot")
    if not is_json_object(recorded_snapshot):
        return None
    current_dict = current_active_car_snapshot.to_dict()
    if _normalized_aspects(recorded_snapshot) == _normalized_aspects(current_dict):
        return None
    return {
        "code": WARNING_CODE_CAR_SETTINGS_CHANGED,
        "severity": "warn",
        "applies_to": "order_analysis",
        "title": i18n_ref("RUN_CONTEXT_WARNING_CAR_SETTINGS_CHANGED_TITLE"),
        "detail": i18n_ref(
            "RUN_CONTEXT_WARNING_CAR_SETTINGS_CHANGED_DETAIL",
            run_car=_car_label(recorded_snapshot),
            current_car=_car_label(current_dict),
        ),
    }


def _normalized_warning_list(warnings: object) -> list[JsonObject]:
    if not isinstance(warnings, list):
        return []
    return [warning for warning in warnings if is_json_object(warning)]


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


def _resolve_optional_i18n(lang: str, value: object) -> str | None:
    resolved = _resolve_i18n(lang, value).strip()
    return resolved or None


def _resolve_i18n(lang: str, value: object) -> str:
    from functools import partial

    from vibesensor.adapters.pdf.mapping import resolve_i18n

    return cast("str", resolve_i18n(lang, value, tr=partial(_tr, lang)))
