"""Boundary serialization helpers for run-context summary warnings."""

from __future__ import annotations

from functools import partial

from vibesensor.report_i18n import tr as _tr
from vibesensor.shared.boundaries.analysis_payload import SummaryWarningPayload
from vibesensor.shared.json_utils import payload_value_from_json
from vibesensor.shared.run_context_warning import (
    RunContextWarning,
    normalize_run_context_warnings,
)
from vibesensor.shared.types.json_types import JsonObject


def summary_warning_payload(warning: RunContextWarning) -> SummaryWarningPayload:
    """Serialize a run-context warning into the persisted/API summary payload shape."""
    payload: SummaryWarningPayload = {
        "code": warning.code,
        "severity": warning.severity,
        "applies_to": warning.applies_to,
        "title": payload_value_from_json(warning.title),
        "detail": payload_value_from_json(warning.detail),
    }
    return payload


def summary_warning_payloads(warnings: object) -> list[SummaryWarningPayload]:
    """Serialize warning models into the summary payload list shape."""
    return [
        summary_warning_payload(warning) for warning in normalize_run_context_warnings(warnings)
    ]


def localize_warning_list(
    warnings: object,
    *,
    lang: str,
) -> list[JsonObject]:
    """Resolve warning models into response-ready text at the HTTP boundary."""
    localized: list[JsonObject] = []
    for warning in normalize_run_context_warnings(warnings):
        localized.append(
            {
                "code": warning.code,
                "severity": warning.severity,
                "applies_to": warning.applies_to,
                "title": _resolve_i18n(lang, warning.title),
                "detail": _resolve_optional_i18n(lang, warning.detail),
            },
        )
    return localized


def _resolve_optional_i18n(lang: str, value: object) -> str | None:
    resolved = _resolve_i18n(lang, value).strip()
    return resolved or None


def _resolve_i18n(lang: str, value: object) -> str:
    from vibesensor.report_i18n import resolve_i18n

    return resolve_i18n(lang, value, tr=partial(_tr, lang))
