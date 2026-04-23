"""Prepared report-confidence facts derived from persisted evidence quality."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast

from vibesensor.domain import Finding
from vibesensor.shared.boundaries.reporting.decision_facts import ReportDecisionFacts
from vibesensor.shared.boundaries.reporting.evidence_facts import ReportEvidenceFacts
from vibesensor.shared.boundaries.reporting.projection import PrimaryReportFacts
from vibesensor.shared.types.history_analysis_contracts import (
    DiagnosisFactorDetailsResponse,
    DiagnosisFactorKey,
    DiagnosisFactorPolarity,
    DiagnosisFactorResponse,
    DiagnosisFactorSeverity,
)

if TYPE_CHECKING:
    from vibesensor.shared.boundaries.reporting.facts import ReportContextFacts

__all__ = [
    "apply_report_confidence_fallback",
    "ReportConfidenceFacts",
    "ReportConfidenceScoringInputs",
    "build_report_confidence_facts",
    "project_whole_run_diagnosis_factors",
    "score_report_confidence_inputs",
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
    speed_gap_window_count: int
    rpm_gap_window_count: int
    uses_summary_fallback: bool
    fallback_reason: str | None
    signal_keys: tuple[str, ...]
    caveat_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReportConfidenceScoringInputs:
    """Normalized inputs for deterministic non-fallback confidence scoring."""

    base_confidence: float
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
    weak_spatial: bool
    context_traceable: bool
    context_source: str
    speed_gap_window_count: int
    rpm_gap_window_count: int


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

    return score_report_confidence_inputs(
        ReportConfidenceScoringInputs(
            base_confidence=primary_candidate.confidence
            if primary_candidate.domain_primary
            else 0.0,
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
            weak_spatial=primary_candidate.weak_spatial,
            context_traceable=context_facts.traceable,
            context_source=context_facts.source,
            speed_gap_window_count=context_facts.speed_gap_window_count,
            rpm_gap_window_count=context_facts.rpm_gap_window_count,
        )
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
        speed_gap_window_count=0,
        rpm_gap_window_count=0,
        uses_summary_fallback=True,
        fallback_reason=fallback_reason,
        signal_keys=(),
        caveat_keys=caveat_keys,
    )


def apply_report_confidence_fallback(
    facts: ReportConfidenceFacts,
    *,
    fallback_reason: str,
) -> ReportConfidenceFacts:
    """Mark report confidence as an explicit fallback without changing its core score."""

    caveat_keys = list(facts.caveat_keys)
    if facts.data_basis == "summary_only" and "summary_only" not in caveat_keys:
        caveat_keys.append("summary_only")
    return replace(
        facts,
        uses_summary_fallback=True,
        fallback_reason=fallback_reason,
        caveat_keys=tuple(caveat_keys),
    )


def project_whole_run_diagnosis_factors(
    confidence_facts: ReportConfidenceFacts,
) -> tuple[tuple[DiagnosisFactorResponse, ...], tuple[DiagnosisFactorResponse, ...]]:
    """Project stable support and counterevidence factors from current confidence facts."""

    support_factors: list[DiagnosisFactorResponse] = []
    counter_factors: list[DiagnosisFactorResponse] = []
    signal_keys = set(confidence_facts.signal_keys)
    caveat_keys = set(confidence_facts.caveat_keys)

    for factor_key in (
        "raw_backed",
        "repeated_support",
        "sustained_support",
        "stable_frequency",
        "tight_order_lock",
        "localized_support",
        "clean_signal",
    ):
        if factor_key not in signal_keys:
            continue
        support_factors.append(
            _factor_payload(
                factor_key=cast(DiagnosisFactorKey, factor_key),
                polarity="support",
                weight=_support_factor_weight(factor_key, confidence_facts),
                details=_factor_details(factor_key, confidence_facts),
            )
        )

    for factor_key in (
        "summary_only",
        "legacy_context",
        "speed_context_gaps",
        "rpm_context_gaps",
        "sparse_support",
        "brief_support",
        "drifting_frequency",
        "loose_order_lock",
        "mixed_support_locations",
        "noisy_signal",
        "weak_spatial",
        "close_alternative",
        "incomplete_reference",
    ):
        if factor_key not in caveat_keys:
            continue
        counter_factors.append(
            _factor_payload(
                factor_key=cast(DiagnosisFactorKey, factor_key),
                polarity="counterevidence",
                weight=_counter_factor_weight(factor_key, confidence_facts),
                details=_factor_details(factor_key, confidence_facts),
            )
        )

    return (tuple(support_factors), tuple(counter_factors))


def score_report_confidence_inputs(
    inputs: ReportConfidenceScoringInputs,
) -> ReportConfidenceFacts:
    """Apply canonical non-fallback confidence scoring to normalized signal inputs."""

    score = max(0.0, min(0.70, 0.25 + (inputs.base_confidence * 0.40)))
    signal_keys: list[str] = []
    caveat_keys: list[str] = []
    frequency_span_hz = _frequency_span_hz(
        stable_frequency_min_hz=inputs.stable_frequency_min_hz,
        stable_frequency_max_hz=inputs.stable_frequency_max_hz,
    )

    if inputs.data_basis == "raw_backed":
        score += 0.10
        signal_keys.append("raw_backed")
    else:
        score -= 0.05
        caveat_keys.append("summary_only")

    if inputs.context_traceable:
        if inputs.context_source == "legacy":
            score -= 0.05
            caveat_keys.append("legacy_context")
        else:
            if inputs.speed_gap_window_count > 0:
                score -= 0.04
                caveat_keys.append("speed_context_gaps")
            if inputs.rpm_gap_window_count > 0:
                score -= 0.04
                caveat_keys.append("rpm_context_gaps")

    supporting_window_count = inputs.supporting_window_count
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

    supporting_duration_s = inputs.supporting_duration_s
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

    if inputs.mean_relative_error is not None:
        if inputs.mean_relative_error <= 0.05:
            score += 0.08
            signal_keys.append("tight_order_lock")
        elif inputs.mean_relative_error >= 0.15:
            score -= 0.08
            caveat_keys.append("loose_order_lock")

    if inputs.top_support_share is not None:
        if inputs.top_support_share >= 0.67:
            score += 0.08
            signal_keys.append("localized_support")
        elif inputs.supporting_location_count > 1 and inputs.top_support_share < 0.55:
            score -= 0.10
            caveat_keys.append("mixed_support_locations")

    if inputs.snr_db is not None:
        if inputs.snr_db >= 6.0:
            score += 0.05
            signal_keys.append("clean_signal")
        elif inputs.snr_db < 3.0:
            score -= 0.06
            caveat_keys.append("noisy_signal")

    if inputs.weak_spatial:
        score -= 0.10
        caveat_keys.append("weak_spatial")

    if inputs.alternative_source is not None:
        score -= 0.10
        caveat_keys.append("close_alternative")

    if inputs.has_reference_gap:
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
        data_basis=inputs.data_basis,
        raw_backed_sample_count=inputs.raw_backed_sample_count,
        supporting_window_count=inputs.supporting_window_count,
        supporting_duration_s=inputs.supporting_duration_s,
        stable_frequency_min_hz=inputs.stable_frequency_min_hz,
        stable_frequency_max_hz=inputs.stable_frequency_max_hz,
        supporting_location_count=inputs.supporting_location_count,
        top_support_location=inputs.top_support_location,
        top_support_share=inputs.top_support_share,
        mean_relative_error=inputs.mean_relative_error,
        snr_db=inputs.snr_db,
        alternative_source=inputs.alternative_source,
        has_reference_gap=inputs.has_reference_gap,
        speed_gap_window_count=inputs.speed_gap_window_count,
        rpm_gap_window_count=inputs.rpm_gap_window_count,
        uses_summary_fallback=False,
        fallback_reason=None,
        signal_keys=tuple(dict.fromkeys(signal_keys)),
        caveat_keys=tuple(dict.fromkeys(caveat_keys)),
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


def _factor_payload(
    *,
    factor_key: DiagnosisFactorKey,
    polarity: DiagnosisFactorPolarity,
    weight: float,
    details: DiagnosisFactorDetailsResponse,
) -> DiagnosisFactorResponse:
    return {
        "factor_key": factor_key,
        "polarity": polarity,
        "severity": _factor_severity(weight),
        "weight": weight,
        "details": details,
    }


def _factor_severity(weight: float) -> DiagnosisFactorSeverity:
    if weight >= 0.10:
        return "high"
    if weight >= 0.07:
        return "medium"
    return "low"


def _support_factor_weight(factor_key: str, facts: ReportConfidenceFacts) -> float:
    if factor_key == "raw_backed":
        return 0.10
    if factor_key == "repeated_support":
        if facts.supporting_window_count is not None and facts.supporting_window_count >= 4:
            return 0.10
        return 0.05
    if factor_key == "sustained_support":
        if facts.supporting_duration_s is not None and facts.supporting_duration_s >= 1.0:
            return 0.08
        return 0.04
    if factor_key == "stable_frequency":
        frequency_span_hz = _frequency_span_hz(
            stable_frequency_min_hz=facts.stable_frequency_min_hz,
            stable_frequency_max_hz=facts.stable_frequency_max_hz,
        )
        if frequency_span_hz is not None and frequency_span_hz <= 0.5:
            return 0.08
        return 0.04
    if factor_key == "tight_order_lock":
        return 0.08
    if factor_key == "localized_support":
        return 0.08
    if factor_key == "clean_signal":
        return 0.05
    raise ValueError(f"unsupported support factor key: {factor_key}")


def _counter_factor_weight(factor_key: str, facts: ReportConfidenceFacts) -> float:
    if factor_key in {"summary_only", "legacy_context"}:
        return 0.05
    if factor_key in {"speed_context_gaps", "rpm_context_gaps"}:
        return 0.04
    if factor_key in {
        "brief_support",
        "drifting_frequency",
        "noisy_signal",
        "incomplete_reference",
    }:
        return 0.06
    if factor_key in {
        "sparse_support",
        "loose_order_lock",
        "mixed_support_locations",
        "weak_spatial",
        "close_alternative",
    }:
        return 0.10 if factor_key != "loose_order_lock" else 0.08
    if factor_key == "summary_only" and facts.uses_summary_fallback:
        return 0.05
    raise ValueError(f"unsupported counterevidence factor key: {factor_key}")


def _factor_details(
    factor_key: str,
    facts: ReportConfidenceFacts,
) -> DiagnosisFactorDetailsResponse:
    details: DiagnosisFactorDetailsResponse = {}
    if factor_key == "raw_backed":
        details["raw_backed_sample_count"] = facts.raw_backed_sample_count
    elif factor_key in {"repeated_support", "sparse_support"}:
        details["supporting_window_count"] = facts.supporting_window_count
    elif factor_key == "sustained_support" or factor_key == "brief_support":
        details["supporting_duration_s"] = facts.supporting_duration_s
    elif factor_key in {"stable_frequency", "drifting_frequency"}:
        details["stable_frequency_min_hz"] = facts.stable_frequency_min_hz
        details["stable_frequency_max_hz"] = facts.stable_frequency_max_hz
        details["frequency_span_hz"] = _frequency_span_hz(
            stable_frequency_min_hz=facts.stable_frequency_min_hz,
            stable_frequency_max_hz=facts.stable_frequency_max_hz,
        )
    elif factor_key == "tight_order_lock" or factor_key == "loose_order_lock":
        details["mean_relative_error"] = facts.mean_relative_error
    elif factor_key == "localized_support" or factor_key == "mixed_support_locations":
        details["supporting_location_count"] = facts.supporting_location_count
        details["top_support_location"] = facts.top_support_location
        details["top_support_share"] = facts.top_support_share
    elif factor_key == "clean_signal" or factor_key == "noisy_signal":
        details["snr_db"] = facts.snr_db
    elif factor_key == "close_alternative":
        details["alternative_source"] = facts.alternative_source
    elif factor_key == "speed_context_gaps":
        details["speed_gap_window_count"] = facts.speed_gap_window_count
    elif factor_key == "rpm_context_gaps":
        details["rpm_gap_window_count"] = facts.rpm_gap_window_count
    elif factor_key == "summary_only" and facts.uses_summary_fallback:
        details["fallback_reason"] = facts.fallback_reason
    return details
