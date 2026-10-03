"""Stable report/history fallback reason codes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

from vibesensor.common.scalars import text_or_none
from vibesensor.summary.analysis_metadata import ReportAnalysisMetadata

__all__ = [
    "REPORT_FALLBACK_REASONS_METADATA_KEY",
    "REPORT_FALLBACK_REASON_VALUES",
    "ReportFallbackReason",
    "dedupe_report_fallback_reasons",
    "derive_report_fallback_reasons",
    "finalization_stage_fallback_reasons",
]

REPORT_FALLBACK_REASONS_METADATA_KEY = "fallback_reasons"

type ReportFallbackReason = Literal[
    "raw_capture_not_configured",
    "raw_capture_loss_exceeded",
    "raw_capture_finalize_timeout",
    "raw_capture_finalize_failed",
    "raw_capture_finalize_unsettled",
    "persistence_finalize_unsettled",
    "history_not_ready",
    "analysis_pending",
    "analysis_failed",
    "legacy_summary_only",
]

REPORT_FALLBACK_REASON_VALUES: frozenset[ReportFallbackReason] = frozenset(
    {
        "raw_capture_not_configured",
        "raw_capture_loss_exceeded",
        "raw_capture_finalize_timeout",
        "raw_capture_finalize_failed",
        "raw_capture_finalize_unsettled",
        "persistence_finalize_unsettled",
        "history_not_ready",
        "analysis_pending",
        "analysis_failed",
        "legacy_summary_only",
    }
)


def dedupe_report_fallback_reasons(
    reasons: Iterable[str],
) -> tuple[ReportFallbackReason, ...]:
    result: list[ReportFallbackReason] = []
    seen: set[str] = set()
    for reason in reasons:
        if reason in seen or reason not in REPORT_FALLBACK_REASON_VALUES:
            continue
        seen.add(reason)
        result.append(reason)
    return tuple(result)


def finalization_stage_fallback_reasons(
    finalization_stages: Iterable[object],
) -> tuple[ReportFallbackReason, ...]:
    stages = {str(getattr(stage, "stage_name", "")): stage for stage in finalization_stages}
    raw_stage = stages.get("FinalizeRawCaptureStage")
    resolve_stage = stages.get("ResolvePostAnalysisCandidateStage")
    raw_context = getattr(raw_stage, "diagnostic_context", {}) if raw_stage is not None else {}
    resolve_context = (
        getattr(resolve_stage, "diagnostic_context", {}) if resolve_stage is not None else {}
    )
    raw_status = (
        text_or_none(raw_context.get("raw_capture_status"))
        if isinstance(raw_context, Mapping)
        else None
    )
    resolve_reason = (
        text_or_none(resolve_context.get("reason"))
        if isinstance(resolve_context, Mapping)
        else None
    )
    reasons: list[str] = []
    if resolve_reason == "persistence_finalize_unsettled":
        reasons.append("persistence_finalize_unsettled")
    if raw_status == "not_configured":
        reasons.append("raw_capture_not_configured")
    if resolve_reason == "raw_capture_finalize_unsettled" or (
        raw_stage is not None and getattr(raw_stage, "status", "") == "degraded"
    ):
        if raw_status in {"timeout", "enqueue_timeout"}:
            reasons.append("raw_capture_finalize_timeout")
        elif raw_status == "failed":
            reasons.append("raw_capture_finalize_failed")
        else:
            reasons.append("raw_capture_finalize_unsettled")
    if resolve_reason == "history_not_ready":
        reasons.append("history_not_ready")
    return dedupe_report_fallback_reasons(reasons)


def derive_report_fallback_reasons(
    analysis_metadata: ReportAnalysisMetadata,
) -> tuple[ReportFallbackReason, ...]:
    """Return why an analysis could not use full raw-capture evidence."""
    reasons: list[str] = []
    if analysis_metadata.raw_capture_available is False:
        reasons.append("raw_capture_not_configured")
    if analysis_metadata.raw_capture_finalize_status == "timeout":
        reasons.append("raw_capture_finalize_timeout")
    elif analysis_metadata.raw_capture_finalize_status == "failed":
        reasons.append("raw_capture_finalize_failed")
    if analysis_metadata.has_fatal_raw_capture_loss:
        reasons.append("raw_capture_loss_exceeded")
    if analysis_metadata.is_summary_only_capture:
        reasons.append("legacy_summary_only")
    return dedupe_report_fallback_reasons(reasons)
