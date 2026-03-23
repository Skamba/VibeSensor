"""Section builders extracted from the PDF report mapper."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from vibesensor.adapters.pdf.report_data import DataTrustItem, NextStep
from vibesensor.domain import RecommendedAction
from vibesensor.report_i18n import is_i18n_ref, resolve_i18n
from vibesensor.shared.boundaries.analysis_payload import RunSuitabilityCheck, SummaryWarningPayload

__all__ = [
    "build_data_trust",
    "build_next_steps",
]


def build_next_steps(
    *,
    recommended_actions: Sequence[RecommendedAction],
    tier: str,
    cert_reason: str,
    lang: str,
    tr: Callable[..., str],
) -> list[NextStep]:
    """Build next-step actions from prepared report facts."""
    if tier == "A":
        return [
            NextStep(action=action, why=cert_reason)
            for action in (
                tr("TIER_A_CAPTURE_WIDER_SPEED"),
                tr("TIER_A_CAPTURE_MORE_SENSORS"),
                tr("TIER_A_CAPTURE_REFERENCE_DATA"),
            )
        ]

    next_steps: list[NextStep] = []
    for action in recommended_actions:
        next_steps.append(
            NextStep(
                action=_resolve_step_value(action.instruction, lang=lang, tr=tr),
                why=_resolve_optional_step_value(action.rationale, lang=lang, tr=tr),
                confirm=_resolve_optional_step_value(
                    action.confirmation_signal,
                    lang=lang,
                    tr=tr,
                ),
                falsify=_resolve_optional_step_value(
                    action.falsification_signal,
                    lang=lang,
                    tr=tr,
                ),
                eta=action.estimated_duration,
            ),
        )
    return next_steps


def _resolve_step_value(value: object, *, lang: str, tr: Callable[..., str]) -> str:
    """Resolve a required step field into report text."""
    if isinstance(value, str) and value.isupper() and "_" in value:
        translated = str(tr(value))
        if translated and translated != value:
            return translated
    return resolve_i18n(lang, value, tr=tr) if is_i18n_ref(value) else str(value or "")


def _resolve_optional_step_value(
    value: object,
    *,
    lang: str,
    tr: Callable[..., str],
) -> str | None:
    """Resolve an optional step field into report text or ``None``."""
    resolved = _resolve_step_value(value, lang=lang, tr=tr).strip()
    return resolved or None


def build_data_trust(
    *,
    suitability_checks: Sequence[RunSuitabilityCheck],
    warnings: Sequence[SummaryWarningPayload],
    lang: str,
    tr: Callable[..., str],
) -> list[DataTrustItem]:
    """Build the data-trust checklist from prepared report facts."""
    data_trust: list[DataTrustItem] = []
    for proj in suitability_checks:
        data_trust.append(
            DataTrustItem(
                check=_resolve_check_text(proj.get("check_key"), lang=lang, tr=tr),
                state=str(proj.get("state") or "warn"),
                detail=_resolve_detail_text(proj.get("explanation"), lang=lang, tr=tr),
            ),
        )
    for warning in warnings:
        data_trust.append(
            DataTrustItem(
                check=_resolve_detail_text(warning.get("title"), lang=lang, tr=tr) or "",
                state=str(warning.get("severity") or "warn"),
                detail=_resolve_detail_text(warning.get("detail"), lang=lang, tr=tr),
            ),
        )
    return data_trust


def _resolve_check_text(value: object, *, lang: str, tr: Callable[..., str]) -> str:
    """Resolve the checklist label text."""
    if is_i18n_ref(value):
        return resolve_i18n(lang, value, tr=tr)
    if isinstance(value, str) and value.startswith("SUITABILITY_CHECK_"):
        return str(tr(value))
    return str(value or "")


def _resolve_detail_text(value: object, *, lang: str, tr: Callable[..., str]) -> str | None:
    """Resolve the checklist detail text."""
    if is_i18n_ref(value) or isinstance(value, list):
        resolved = resolve_i18n(lang, value, tr=tr).strip()
    else:
        resolved = str(value or "").strip()
    return resolved or None
