"""Prepared report-confidence facts derived from persisted evidence quality."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.domain import Finding
from vibesensor.shared.boundaries.reporting.decision_facts import ReportDecisionFacts
from vibesensor.shared.boundaries.reporting.evidence_facts import ReportEvidenceFacts
from vibesensor.shared.boundaries.reporting.projection import PrimaryReportFacts

if TYPE_CHECKING:
    from vibesensor.shared.boundaries.reporting.facts import ReportContextFacts

__all__ = [
    "ReportConfidenceFacts",
    "build_report_confidence_facts",
]


@dataclass(frozen=True, slots=True)
class ReportConfidenceFacts:
    """Explicit report-confidence inputs and the bounded score derived from them."""

    score_0_to_1: float
    label_key: str
    pct_text: str
    tier: str
    data_basis: str
    raw_backed_sample_count: int
    supporting_window_count: int | None
    supporting_duration_s: float | None
    stable_frequency_min_hz: float | None
    stable_frequency_max_hz: float | None
    supporting_location_count: int
    top_support_location: str | None
    top_support_share: float | None
    mean_relative_error: float | None
    snr_db: float | None
    alternative_source: str | None
    has_reference_gap: bool
    uses_summary_fallback: bool
    fallback_reason: str | None
    signal_keys: tuple[str, ...]
    caveat_keys: tuple[str, ...]


def build_report_confidence_facts(
    *,
    has_explicit_analysis_metadata: bool,
    primary_candidate: PrimaryReportFacts,
    evidence_facts: ReportEvidenceFacts,
    decision_facts: ReportDecisionFacts,
    context_facts: ReportContextFacts,
) -> ReportConfidenceFacts:
    """Build bounded report confidence from explicit persisted evidence signals."""

    finding_evidence = (
        primary_candidate.domain_primary.evidence
        if primary_candidate.domain_primary is not None
        else None
    )
    supporting_window_count = evidence_facts.supporting_window_count
    supporting_duration_s = evidence_facts.supporting_duration_s
    stable_frequency_min_hz = evidence_facts.stable_frequency_min_hz
    stable_frequency_max_hz = evidence_facts.stable_frequency_max_hz
    frequency_span_hz = _frequency_span_hz(
        stable_frequency_min_hz=stable_frequency_min_hz,
        stable_frequency_max_hz=stable_frequency_max_hz,
    )
    supporting_location_count, top_support_location, top_support_share = _support_location_summary(
        evidence_facts=evidence_facts,
    )
    mean_relative_error = (
        finding_evidence.mean_relative_error if finding_evidence is not None else None
    )
    snr_db = finding_evidence.snr_db if finding_evidence is not None else None
    alternative_source = (
        decision_facts.alternative_source if decision_facts.alternative_source_visible else None
    )
    if _should_use_summary_fallback(
        has_explicit_analysis_metadata=has_explicit_analysis_metadata,
        primary_candidate=primary_candidate,
        evidence_facts=evidence_facts,
        mean_relative_error=mean_relative_error,
        snr_db=snr_db,
    ):
        return _summary_fallback_confidence(
            primary_candidate=primary_candidate,
            evidence_facts=evidence_facts,
            alternative_source=alternative_source,
            mean_relative_error=mean_relative_error,
            snr_db=snr_db,
            supporting_location_count=supporting_location_count,
            top_support_location=top_support_location,
            top_support_share=top_support_share,
        )

    score = (
        max(0.0, min(0.70, 0.25 + (primary_candidate.confidence * 0.40)))
        if primary_candidate.domain_primary is not None
        else 0.0
    )
    signal_keys: list[str] = []
    caveat_keys: list[str] = []

    if evidence_facts.data_basis == "raw_backed":
        score += 0.10
        signal_keys.append("raw_backed")
    else:
        score -= 0.05
        caveat_keys.append("summary_only")

    if context_facts.traceable:
        if context_facts.source == "legacy":
            score -= 0.05
            caveat_keys.append("legacy_context")
        else:
            if context_facts.has_speed_gaps:
                score -= 0.04
                caveat_keys.append("speed_context_gaps")
            if context_facts.has_rpm_gaps:
                score -= 0.04
                caveat_keys.append("rpm_context_gaps")

    if supporting_window_count is not None:
        if supporting_window_count >= 4:
            score += 0.10
            signal_keys.append("repeated_support")
        elif supporting_window_count >= 2:
            score += 0.05
            signal_keys.append("repeated_support")
        elif supporting_window_count <= 1:
            score -= 0.10
            caveat_keys.append("sparse_support")

    if supporting_duration_s is not None:
        if supporting_duration_s >= 1.0:
            score += 0.08
            signal_keys.append("sustained_support")
        elif supporting_duration_s >= 0.5:
            score += 0.04
            signal_keys.append("sustained_support")
        elif supporting_duration_s > 0:
            score -= 0.06
            caveat_keys.append("brief_support")

    if frequency_span_hz is not None:
        if frequency_span_hz <= 0.5:
            score += 0.08
            signal_keys.append("stable_frequency")
        elif frequency_span_hz <= 1.0:
            score += 0.04
            signal_keys.append("stable_frequency")
        elif frequency_span_hz > 1.5:
            score -= 0.06
            caveat_keys.append("drifting_frequency")

    if mean_relative_error is not None:
        if mean_relative_error <= 0.05:
            score += 0.08
            signal_keys.append("tight_order_lock")
        elif mean_relative_error >= 0.15:
            score -= 0.08
            caveat_keys.append("loose_order_lock")

    if top_support_share is not None:
        if top_support_share >= 0.67:
            score += 0.08
            signal_keys.append("localized_support")
        elif supporting_location_count > 1 and top_support_share < 0.55:
            score -= 0.10
            caveat_keys.append("mixed_support_locations")

    if snr_db is not None:
        if snr_db >= 6.0:
            score += 0.05
            signal_keys.append("clean_signal")
        elif snr_db < 3.0:
            score -= 0.06
            caveat_keys.append("noisy_signal")

    if primary_candidate.weak_spatial:
        score -= 0.10
        caveat_keys.append("weak_spatial")

    if alternative_source is not None:
        score -= 0.10
        caveat_keys.append("close_alternative")

    if evidence_facts.has_reference_gap:
        score -= 0.06
        caveat_keys.append("incomplete_reference")

    rounded_score = _rounded_score(score)
    label_key = _label_key_for_score(rounded_score)
    caveat_key_set = set(caveat_keys)
    tier = (
        "C"
        if label_key == "CONFIDENCE_HIGH"
        and not caveat_key_set.intersection(
            {
                "summary_only",
                "drifting_frequency",
                "loose_order_lock",
                "mixed_support_locations",
                "weak_spatial",
                "close_alternative",
                "incomplete_reference",
                "legacy_context",
                "speed_context_gaps",
                "rpm_context_gaps",
                "noisy_signal",
            }
        )
        else ("B" if label_key != "CONFIDENCE_LOW" else "A")
    )
    return ReportConfidenceFacts(
        score_0_to_1=rounded_score,
        label_key=label_key,
        pct_text=f"{rounded_score * 100:.0f}%",
        tier=tier,
        data_basis=evidence_facts.data_basis,
        raw_backed_sample_count=evidence_facts.raw_backed_sample_count,
        supporting_window_count=supporting_window_count,
        supporting_duration_s=supporting_duration_s,
        stable_frequency_min_hz=stable_frequency_min_hz,
        stable_frequency_max_hz=stable_frequency_max_hz,
        supporting_location_count=supporting_location_count,
        top_support_location=top_support_location,
        top_support_share=top_support_share,
        mean_relative_error=mean_relative_error,
        snr_db=snr_db,
        alternative_source=alternative_source,
        has_reference_gap=evidence_facts.has_reference_gap,
        uses_summary_fallback=False,
        fallback_reason=None,
        signal_keys=tuple(dict.fromkeys(signal_keys)),
        caveat_keys=tuple(dict.fromkeys(caveat_keys)),
    )


def _should_use_summary_fallback(
    *,
    has_explicit_analysis_metadata: bool,
    primary_candidate: PrimaryReportFacts,
    evidence_facts: ReportEvidenceFacts,
    mean_relative_error: float | None,
    snr_db: float | None,
) -> bool:
    if not has_explicit_analysis_metadata and evidence_facts.data_basis == "summary_only":
        return True
    return bool(
        primary_candidate.domain_primary is not None
        and evidence_facts.data_basis == "summary_only"
        and not primary_candidate.domain_primary.matched_points
        and (
            evidence_facts.supporting_window_count is None
            or evidence_facts.supporting_window_count <= 0
        )
        and mean_relative_error is None
        and snr_db is None
    )


def _summary_fallback_confidence(
    *,
    primary_candidate: PrimaryReportFacts,
    evidence_facts: ReportEvidenceFacts,
    alternative_source: str | None,
    mean_relative_error: float | None,
    snr_db: float | None,
    supporting_location_count: int,
    top_support_location: str | None,
    top_support_share: float | None,
) -> ReportConfidenceFacts:
    confidence = (
        primary_candidate.confidence if primary_candidate.domain_primary is not None else 0.0
    )
    assessment = (
        primary_candidate.domain_primary.confidence_assessment
        if primary_candidate.domain_primary is not None
        else None
    )
    label_key = assessment.label_key if assessment is not None else _label_key_for_score(confidence)
    pct_text = (
        assessment.pct_text if assessment is not None else f"{max(0.0, confidence) * 100:.0f}%"
    )
    tier = assessment.tier if assessment is not None else ("A" if confidence < 0.40 else "B")
    fallback_reason = (assessment.reason if assessment is not None else "") or None
    caveat_keys = ("summary_only",) if evidence_facts.data_basis == "summary_only" else ()
    return ReportConfidenceFacts(
        score_0_to_1=max(0.0, min(1.0, confidence)),
        label_key=label_key,
        pct_text=pct_text,
        tier=tier,
        data_basis=evidence_facts.data_basis,
        raw_backed_sample_count=evidence_facts.raw_backed_sample_count,
        supporting_window_count=evidence_facts.supporting_window_count,
        supporting_duration_s=evidence_facts.supporting_duration_s,
        stable_frequency_min_hz=evidence_facts.stable_frequency_min_hz,
        stable_frequency_max_hz=evidence_facts.stable_frequency_max_hz,
        supporting_location_count=supporting_location_count,
        top_support_location=top_support_location,
        top_support_share=top_support_share,
        mean_relative_error=mean_relative_error,
        snr_db=snr_db,
        alternative_source=alternative_source,
        has_reference_gap=evidence_facts.has_reference_gap,
        uses_summary_fallback=True,
        fallback_reason=fallback_reason,
        signal_keys=(),
        caveat_keys=caveat_keys,
    )


def _frequency_span_hz(
    *,
    stable_frequency_min_hz: float | None,
    stable_frequency_max_hz: float | None,
) -> float | None:
    if stable_frequency_min_hz is None or stable_frequency_max_hz is None:
        return None
    span = stable_frequency_max_hz - stable_frequency_min_hz
    return span if math.isfinite(span) and span >= 0 else None


def _support_location_summary(
    *,
    evidence_facts: ReportEvidenceFacts,
) -> tuple[int, str | None, float | None]:
    if (
        evidence_facts.supporting_window_count is None
        or evidence_facts.supporting_window_count <= 0
        or not evidence_facts.supporting_location_counts
    ):
        return (0, None, None)
    total = sum(count for _, count in evidence_facts.supporting_location_counts)
    if total <= 0:
        return (0, None, None)
    top_location, top_count = evidence_facts.supporting_location_counts[0]
    return (
        len(evidence_facts.supporting_location_counts),
        top_location,
        top_count / total,
    )


def _rounded_score(score: float) -> float:
    bounded = max(0.10, min(0.90, score))
    return round(bounded / 0.05) * 0.05


def _label_key_for_score(score: float) -> str:
    if score >= Finding.CONFIDENCE_HIGH_THRESHOLD:
        return "CONFIDENCE_HIGH"
    if score >= Finding.CONFIDENCE_MEDIUM_THRESHOLD:
        return "CONFIDENCE_MEDIUM"
    return "CONFIDENCE_LOW"
