"""Stable report/history fallback reason codes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

from vibesensor.shared.boundaries.codecs.scalars import coerce_count, text_or_none

__all__ = [
    "REPORT_FALLBACK_REASONS_METADATA_KEY",
    "REPORT_FALLBACK_REASON_VALUES",
    "ReportFallbackReason",
    "dedupe_report_fallback_reasons",
    "derive_report_fallback_reasons",
    "finalization_stage_fallback_reasons",
    "normalize_report_fallback_reasons",
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
    "whole_run_analysis_pending",
    "whole_run_analysis_failed",
    "legacy_summary_only",
    "sidecar_summary_mismatch",
    "whole_run_evidence_missing",
    "whole_run_evidence_incomplete",
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
        "whole_run_analysis_pending",
        "whole_run_analysis_failed",
        "legacy_summary_only",
        "sidecar_summary_mismatch",
        "whole_run_evidence_missing",
        "whole_run_evidence_incomplete",
    }
)


def normalize_report_fallback_reasons(raw_reasons: object) -> tuple[ReportFallbackReason, ...]:
    if not isinstance(raw_reasons, list | tuple):
        return ()
    return dedupe_report_fallback_reasons(
        reason
        for raw_reason in raw_reasons
        if (reason := text_or_none(raw_reason)) in REPORT_FALLBACK_REASON_VALUES
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
    analysis_metadata: Mapping[str, object],
    *,
    has_whole_run_context_intervals: bool,
    has_whole_run_order_summaries: bool,
    has_whole_run_spatial_summaries: bool,
    has_whole_run_diagnosis_summaries: bool,
) -> tuple[ReportFallbackReason, ...]:
    reasons: list[str] = []
    reasons.extend(_raw_capture_fallback_reasons(analysis_metadata))
    reasons.extend(
        _whole_run_fallback_reasons(
            analysis_metadata,
            has_whole_run_context_intervals=has_whole_run_context_intervals,
            has_whole_run_order_summaries=has_whole_run_order_summaries,
            has_whole_run_spatial_summaries=has_whole_run_spatial_summaries,
            has_whole_run_diagnosis_summaries=has_whole_run_diagnosis_summaries,
        )
    )
    return dedupe_report_fallback_reasons(reasons)


def _raw_capture_fallback_reasons(
    analysis_metadata: Mapping[str, object],
) -> tuple[ReportFallbackReason, ...]:
    reasons: list[str] = []
    if analysis_metadata.get("raw_capture_available") is False:
        reasons.append("raw_capture_not_configured")
    finalize_status = text_or_none(analysis_metadata.get("raw_capture_finalize_status"))
    if finalize_status == "timeout":
        reasons.append("raw_capture_finalize_timeout")
    elif finalize_status == "failed":
        reasons.append("raw_capture_finalize_failed")
    loss_policy_severity = text_or_none(analysis_metadata.get("raw_capture_loss_policy_severity"))
    if loss_policy_severity == "fatal" or bool(
        analysis_metadata.get("raw_capture_loss_policy_gate_whole_run")
    ):
        reasons.append("raw_capture_loss_exceeded")
    raw_capture_mode = text_or_none(analysis_metadata.get("raw_capture_mode"))
    raw_backed_sample_count = coerce_count(analysis_metadata.get("raw_backed_sample_count"))
    if raw_capture_mode == "summary_only" or (
        raw_capture_mode is None and raw_backed_sample_count <= 0
    ):
        reasons.append("legacy_summary_only")
    return dedupe_report_fallback_reasons(reasons)


def _whole_run_fallback_reasons(
    analysis_metadata: Mapping[str, object],
    *,
    has_whole_run_context_intervals: bool,
    has_whole_run_order_summaries: bool,
    has_whole_run_spatial_summaries: bool,
    has_whole_run_diagnosis_summaries: bool,
) -> tuple[ReportFallbackReason, ...]:
    if has_whole_run_diagnosis_summaries:
        return ()
    if _has_sidecar_summary_mismatch(
        analysis_metadata,
        has_whole_run_order_summaries=has_whole_run_order_summaries,
        has_whole_run_spatial_summaries=has_whole_run_spatial_summaries,
    ):
        return ("sidecar_summary_mismatch",)
    has_partial_whole_run_inputs = bool(
        has_whole_run_context_intervals
        or has_whole_run_order_summaries
        or has_whole_run_spatial_summaries
        or analysis_metadata.get("whole_run_artifacts_available")
        or analysis_metadata.get("whole_run_context_available")
        or analysis_metadata.get("whole_run_order_family_summaries_available")
        or analysis_metadata.get("whole_run_spatial_coherence_available")
    )
    if has_partial_whole_run_inputs:
        return ("whole_run_evidence_incomplete",)
    raw_capture_mode = text_or_none(analysis_metadata.get("raw_capture_mode"))
    raw_backed_sample_count = coerce_count(analysis_metadata.get("raw_backed_sample_count"))
    if raw_capture_mode in {"raw_backed", "partial_raw_backed"} or raw_backed_sample_count > 0:
        return ("whole_run_evidence_missing",)
    return ()


def _has_sidecar_summary_mismatch(
    analysis_metadata: Mapping[str, object],
    *,
    has_whole_run_order_summaries: bool,
    has_whole_run_spatial_summaries: bool,
) -> bool:
    if (
        bool(analysis_metadata.get("whole_run_diagnosis_summaries_available"))
        and coerce_count(analysis_metadata.get("whole_run_diagnosis_summary_count")) > 0
    ):
        return True
    if (
        bool(analysis_metadata.get("whole_run_order_family_summaries_available"))
        and coerce_count(analysis_metadata.get("whole_run_order_family_summary_count")) > 0
        and not has_whole_run_order_summaries
    ):
        return True
    return bool(
        bool(analysis_metadata.get("whole_run_spatial_coherence_available"))
        and coerce_count(analysis_metadata.get("whole_run_spatial_coherence_summary_count")) > 0
        and not has_whole_run_spatial_summaries
    )
