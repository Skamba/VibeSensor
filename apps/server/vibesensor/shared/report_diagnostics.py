"""Canonical report diagnostic helpers shared by history prep and PDF mapping."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from vibesensor.domain import RunSuitability, SuitabilityCheck
from vibesensor.report_i18n import is_i18n_ref, resolve_i18n
from vibesensor.shared.run_context_warning import (
    RunContextWarning,
    RunContextWarningsInput,
    WarningSeverity,
)
from vibesensor.shared.types.json_types import JsonObject, is_json_array, is_json_object

__all__ = [
    "LocalizedDiagnostic",
    "check_state",
    "first_nonpass_detail",
    "has_warning_code",
    "localized_diagnostics",
    "nonpass_detail_lines",
    "report_suitability_checks",
    "report_warnings",
]


@dataclass(frozen=True, slots=True)
class LocalizedDiagnostic:
    label: str
    state: str
    detail: str | None


def report_suitability_checks(suitability: RunSuitability | None) -> tuple[SuitabilityCheck, ...]:
    """Return the canonical report-facing suitability checks."""
    return () if suitability is None else suitability.checks


def report_warnings(
    payload: Mapping[str, object],
    *,
    warnings: RunContextWarningsInput = None,
) -> tuple[RunContextWarning, ...]:
    """Return canonical report-facing warnings from the explicit override or payload."""
    source = warnings
    if source is None:
        raw_warnings = payload.get("warnings")
        source = raw_warnings if is_json_array(raw_warnings) else None
    return tuple(_normalized_report_warnings(source))


def localized_diagnostics(
    *,
    suitability_checks: Sequence[SuitabilityCheck],
    warnings: Sequence[RunContextWarning],
    lang: str,
    tr: Callable[..., str],
) -> tuple[LocalizedDiagnostic, ...]:
    """Resolve report diagnostics into localized report-ready label/detail rows."""
    diagnostics: list[LocalizedDiagnostic] = []
    for check in suitability_checks:
        diagnostics.append(
            LocalizedDiagnostic(
                label=_resolve_check_text(check.check_key, lang=lang, tr=tr),
                state=check.state,
                detail=_resolve_detail_text(check.explanation_i18n_ref(), lang=lang, tr=tr),
            )
        )
    for warning in warnings:
        diagnostics.append(
            LocalizedDiagnostic(
                label=_resolve_detail_text(warning.title, lang=lang, tr=tr) or warning.code,
                state=warning.severity,
                detail=_resolve_detail_text(warning.detail, lang=lang, tr=tr),
            )
        )
    return tuple(diagnostics)


def first_nonpass_detail(
    *,
    suitability_checks: Sequence[SuitabilityCheck],
    warnings: Sequence[RunContextWarning],
    lang: str,
    tr: Callable[..., str],
) -> str | None:
    """Return the first localized non-pass diagnostic detail shown to the user."""
    for check in suitability_checks:
        if check.state.strip().lower() == "pass":
            continue
        detail = _resolve_detail_text(check.explanation_i18n_ref(), lang=lang, tr=tr)
        if detail:
            return detail
        label = _resolve_check_text(check.check_key, lang=lang, tr=tr)
        if label:
            return label
    for warning in warnings:
        detail = _resolve_detail_text(warning.detail, lang=lang, tr=tr)
        if detail:
            return detail
        title = _resolve_detail_text(warning.title, lang=lang, tr=tr)
        if title:
            return title
    return None


def nonpass_detail_lines(
    *,
    suitability_checks: Sequence[SuitabilityCheck],
    warnings: Sequence[RunContextWarning],
    lang: str,
    tr: Callable[..., str],
) -> tuple[str, ...]:
    """Return all localized non-pass diagnostic details shown on the recapture path."""
    lines: list[str] = []
    for check in suitability_checks:
        if check.state.strip().lower() == "pass":
            continue
        detail = _resolve_detail_text(check.explanation_i18n_ref(), lang=lang, tr=tr)
        label = _resolve_check_text(check.check_key, lang=lang, tr=tr)
        text = detail or label
        if text:
            lines.append(text)
    for warning in warnings:
        detail = _resolve_detail_text(warning.detail, lang=lang, tr=tr)
        title = _resolve_detail_text(warning.title, lang=lang, tr=tr)
        warning_text = detail or title
        if warning_text:
            lines.append(warning_text)
    return tuple(lines)


def check_state(
    suitability_checks: Sequence[SuitabilityCheck],
    check_key: str,
) -> str:
    """Return the canonical state for one report suitability check."""
    target = check_key.strip().upper()
    for check in suitability_checks:
        key = check.check_key.strip().upper()
        if key == target:
            return check.state.strip().lower()
    return ""


def has_warning_code(warnings: Sequence[RunContextWarning], code: str) -> bool:
    """Return whether any canonical warning matches the requested code."""
    target = code.strip().lower()
    return any(warning.code.strip().lower() == target for warning in warnings)


def _normalized_report_warnings(
    warnings: RunContextWarningsInput,
) -> list[RunContextWarning]:
    if warnings is None:
        return []
    normalized: list[RunContextWarning] = []
    for index, warning in enumerate(warnings):
        if isinstance(warning, RunContextWarning):
            normalized.append(warning)
            continue
        if not is_json_object(warning):
            raise ValueError(
                "Report warning at index "
                f"{index} must be a warning object, got {type(warning).__name__}"
            )
        normalized.append(_warning_from_payload(warning))
    return normalized


def _warning_from_payload(payload: JsonObject) -> RunContextWarning:
    title = payload.get("title")
    if title is None:
        raise ValueError("Report warning payload requires non-null 'title'")
    return RunContextWarning(
        code=_required_text(payload, "code"),
        severity=_required_warning_severity(payload),
        applies_to=_required_text(payload, "applies_to"),
        title=title,
        detail=payload.get("detail"),
    )


def _required_text(payload: JsonObject, field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str):
        raise ValueError(f"Report warning payload requires string field {field!r}")
    text = value.strip()
    if not text:
        raise ValueError(f"Report warning payload requires non-empty string field {field!r}")
    return text


def _required_warning_severity(payload: JsonObject) -> WarningSeverity:
    severity = _required_text(payload, "severity").lower()
    if severity not in {"warn", "error"}:
        raise ValueError(f"Unsupported report warning severity: {severity!r}")
    return cast(WarningSeverity, severity)


def _resolve_check_text(value: object, *, lang: str, tr: Callable[..., str]) -> str:
    if is_i18n_ref(value):
        return resolve_i18n(lang, value, tr=tr)
    if isinstance(value, str) and value.startswith("SUITABILITY_CHECK_"):
        return str(tr(value))
    return str(value or "")


def _resolve_detail_text(value: object, *, lang: str, tr: Callable[..., str]) -> str | None:
    if is_i18n_ref(value) or isinstance(value, list):
        resolved = resolve_i18n(lang, value, tr=tr).strip()
    else:
        resolved = str(value or "").strip()
    return resolved or None
