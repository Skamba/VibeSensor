"""Run-context snapshot and trust-warning helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping

from vibesensor.use_cases.diagnostics import i18n_ref
from vibesensor.infra.config.analysis_settings import DEFAULT_ANALYSIS_SETTINGS, tire_circumference_m_from_spec
from vibesensor.shared.types.json_types import JsonObject, JsonValue, is_json_object
from vibesensor.shared.utils.json_utils import as_float_or_none as _as_float
from vibesensor.report_i18n import tr as _tr

ANALYSIS_SETTINGS_SNAPSHOT_KEYS: tuple[str, ...] = tuple(DEFAULT_ANALYSIS_SETTINGS.keys())

WARNING_CODE_REFERENCE_CONTEXT_INCOMPLETE = "reference_context_incomplete"
WARNING_CODE_CAR_SETTINGS_CHANGED = "car_settings_changed"


def build_run_context_snapshot(
    *,
    analysis_settings_snapshot: Mapping[str, object],
    active_car_snapshot: Mapping[str, object] | None,
) -> JsonObject:
    """Build a structured run-context snapshot for persisted metadata."""
    settings_snapshot: JsonObject = {}
    for key in ANALYSIS_SETTINGS_SNAPSHOT_KEYS:
        value = _as_float(analysis_settings_snapshot.get(key))
        if value is not None:
            settings_snapshot[key] = value
    snapshot: JsonObject = {"analysis_settings_snapshot": settings_snapshot}
    if active_car_snapshot is not None:
        snapshot["active_car_snapshot"] = _sanitize_car_snapshot(active_car_snapshot)
    return snapshot


def apply_run_context_snapshot(
    metadata: JsonObject,
    *,
    analysis_settings_snapshot: Mapping[str, object],
    active_car_snapshot: Mapping[str, object] | None,
) -> None:
    """Attach structured run-context snapshot fields to persisted metadata."""
    context_snapshot = build_run_context_snapshot(
        analysis_settings_snapshot=analysis_settings_snapshot,
        active_car_snapshot=active_car_snapshot,
    )
    metadata.update(context_snapshot)
    car_snapshot = context_snapshot.get("active_car_snapshot")
    if isinstance(car_snapshot, dict):
        metadata["active_car_id"] = car_snapshot.get("id")
        metadata["car_name"] = car_snapshot.get("name")
        metadata["car_type"] = car_snapshot.get("type")
        metadata["car_variant"] = car_snapshot.get("variant")


def order_reference_context_complete(metadata: Mapping[str, object]) -> bool:
    """Return True when persisted run metadata is sufficient for order references."""
    raw_sample_rate_hz = _as_float(metadata.get("raw_sample_rate_hz"))
    tire_circumference_m = _as_float(metadata.get("tire_circumference_m"))
    if tire_circumference_m is None:
        tire_circumference_m = tire_circumference_m_from_spec(
            _as_float(metadata.get("tire_width_mm")),
            _as_float(metadata.get("tire_aspect_pct")),
            _as_float(metadata.get("rim_in")),
            deflection_factor=_as_float(metadata.get("tire_deflection_factor")),
        )
    has_engine_reference = _as_float(metadata.get("engine_rpm")) is not None or (
        _as_float(metadata.get("final_drive_ratio")) is not None
        and _as_float(metadata.get("current_gear_ratio")) is not None
    )
    return bool(raw_sample_rate_hz and tire_circumference_m and has_engine_reference)


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
    current_active_car_snapshot: Mapping[str, object] | None,
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


def current_car_snapshot_token(current_active_car_snapshot: Mapping[str, object] | None) -> str:
    """Return a stable cache token for current active-car context."""
    return json.dumps(
        _sanitize_car_snapshot(current_active_car_snapshot) if current_active_car_snapshot else {},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )


def _build_car_settings_changed_warning(
    metadata: object,
    *,
    current_active_car_snapshot: Mapping[str, object] | None,
) -> JsonObject | None:
    if not is_json_object(metadata) or current_active_car_snapshot is None:
        return None
    recorded_snapshot = metadata.get("active_car_snapshot")
    if not is_json_object(recorded_snapshot):
        return None
    if _normalized_aspects(recorded_snapshot) == _normalized_aspects(current_active_car_snapshot):
        return None
    return {
        "code": WARNING_CODE_CAR_SETTINGS_CHANGED,
        "severity": "warn",
        "applies_to": "order_analysis",
        "title": i18n_ref("RUN_CONTEXT_WARNING_CAR_SETTINGS_CHANGED_TITLE"),
        "detail": i18n_ref(
            "RUN_CONTEXT_WARNING_CAR_SETTINGS_CHANGED_DETAIL",
            run_car=_car_label(recorded_snapshot),
            current_car=_car_label(current_active_car_snapshot),
        ),
    }


def _normalized_warning_list(warnings: object) -> list[JsonObject]:
    if not isinstance(warnings, list):
        return []
    return [warning for warning in warnings if is_json_object(warning)]


def _sanitize_car_snapshot(snapshot: Mapping[str, object]) -> JsonObject:
    aspects_raw = snapshot.get("aspects")
    aspects = aspects_raw if isinstance(aspects_raw, Mapping) else {}
    return {
        "id": str(snapshot.get("id") or "").strip() or None,
        "name": str(snapshot.get("name") or "").strip() or None,
        "type": str(snapshot.get("type") or "").strip() or None,
        "variant": str(snapshot.get("variant") or "").strip() or None,
        "aspects": {
            key: value
            for key in ANALYSIS_SETTINGS_SNAPSHOT_KEYS
            if (value := _as_float(aspects.get(key))) is not None
        },
    }


def _normalized_aspects(snapshot: Mapping[str, object]) -> tuple[tuple[str, float], ...]:
    aspects_raw = snapshot.get("aspects")
    if not isinstance(aspects_raw, Mapping):
        return ()
    normalized = [
        (key, float(value))
        for key in ANALYSIS_SETTINGS_SNAPSHOT_KEYS
        if (value := _as_float(aspects_raw.get(key))) is not None
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

    return resolve_i18n(lang, value, tr=partial(_tr, lang))
