"""Action and trust-list builders for summary-to-report mapping."""

from __future__ import annotations

from collections.abc import Callable

from ..report.report_data import DataTrustItem, NextStep
from .report_mapping_common import is_i18n_ref, resolve_i18n


def build_next_steps_from_summary(
    summary: dict,
    *,
    tier: str,
    cert_reason: str,
    lang: str,
    tr: Callable,
) -> list[NextStep]:
    """Build next-step actions from a run summary dict."""
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
    test_plan = [step for step in summary.get("test_plan", []) if isinstance(step, dict)]
    for step in test_plan:
        next_steps.append(
            NextStep(
                action=_resolve_step_value(step.get("what"), lang=lang, tr=tr),
                why=_resolve_optional_step_value(step.get("why"), lang=lang, tr=tr),
                confirm=_resolve_optional_step_value(step.get("confirm"), lang=lang, tr=tr),
                falsify=_resolve_optional_step_value(step.get("falsify"), lang=lang, tr=tr),
                eta=str(step.get("eta") or "") or None,
            )
        )
    return next_steps


def _resolve_step_value(value: object, *, lang: str, tr: Callable) -> str:
    """Resolve a required step field into report text."""
    return resolve_i18n(lang, value, tr=tr) if is_i18n_ref(value) else str(value or "")


def _resolve_optional_step_value(
    value: object,
    *,
    lang: str,
    tr: Callable,
) -> str | None:
    """Resolve an optional step field into report text or ``None``."""
    resolved = _resolve_step_value(value, lang=lang, tr=tr).strip()
    return resolved or None


def build_data_trust_from_summary(
    summary: dict,
    *,
    lang: str,
    tr: Callable,
) -> list[DataTrustItem]:
    """Build the data-trust checklist from run_suitability items."""
    data_trust: list[DataTrustItem] = []
    for item in summary.get("run_suitability", []):
        if not isinstance(item, dict):
            continue
        check_text = _resolve_check_text(item.get("check"), lang=lang, tr=tr)
        detail = _resolve_detail_text(item.get("explanation"), lang=lang, tr=tr)
        data_trust.append(
            DataTrustItem(
                check=check_text,
                state=str(item.get("state") or "warn"),
                detail=detail,
            )
        )
    for warning in summary.get("warnings", []):
        if not isinstance(warning, dict):
            continue
        data_trust.append(
            DataTrustItem(
                check=_resolve_detail_text(warning.get("title"), lang=lang, tr=tr) or "",
                state=str(warning.get("severity") or "warn"),
                detail=_resolve_detail_text(warning.get("detail"), lang=lang, tr=tr),
            )
        )
    return data_trust


def _resolve_check_text(value: object, *, lang: str, tr: Callable[..., str]) -> str:
    """Resolve the checklist label text."""
    if is_i18n_ref(value):
        return resolve_i18n(lang, value, tr=tr)
    if isinstance(value, str) and value.startswith("SUITABILITY_CHECK_"):
        return str(tr(value))
    return str(value or "")


def _resolve_detail_text(value: object, *, lang: str, tr: Callable) -> str | None:
    """Resolve the checklist detail text."""
    if is_i18n_ref(value) or isinstance(value, list):
        resolved = resolve_i18n(lang, value, tr=tr).strip()
    else:
        resolved = str(value or "").strip()
    return resolved or None
