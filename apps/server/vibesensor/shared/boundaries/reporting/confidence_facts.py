"""Prepared report-confidence facts projected from the canonical diagnosis policy."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from vibesensor.domain import (
    DiagnosisAssessment,
    DiagnosisAssessmentFactor,
    DiagnosisAssessmentFactorDetails,
    DiagnosisAssessmentInputs,
    apply_diagnosis_assessment_fallback,
    diagnosis_assessment_from_components,
    score_diagnosis_assessment_inputs,
)
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
    from vibesensor.shared.boundaries.reporting.summary import (
        ReportDiagnosisFactor,
        ReportWholeRunDiagnosisSummary,
    )

__all__ = [
    "ReportConfidenceFacts",
    "ReportConfidenceScoringInputs",
    "apply_report_confidence_fallback",
    "build_report_confidence_facts",
    "project_whole_run_diagnosis_factors",
    "report_confidence_from_diagnosis_summary",
    "score_report_confidence_inputs",
]

ReportConfidenceFacts = DiagnosisAssessment
ReportConfidenceScoringInputs = DiagnosisAssessmentInputs


def build_report_confidence_facts(
    *,
    has_explicit_analysis_metadata: bool,
    primary_candidate: PrimaryReportFacts,
    evidence_facts: ReportEvidenceFacts,
    decision_facts: ReportDecisionFacts,
    context_facts: ReportContextFacts,
) -> ReportConfidenceFacts:
    """Build provisional report confidence from explicit persisted evidence signals."""

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


def report_confidence_from_diagnosis_summary(
    diagnosis_summary: ReportWholeRunDiagnosisSummary,
) -> ReportConfidenceFacts:
    """Project report confidence directly from a persisted whole-run diagnosis summary."""

    return diagnosis_assessment_from_components(
        score_0_to_1=diagnosis_summary.total_score or 0.0,
        data_basis=diagnosis_summary.data_basis,
        raw_backed_sample_count=_raw_backed_sample_count(diagnosis_summary.support_factors),
        supporting_window_count=diagnosis_summary.supporting_window_count,
        supporting_duration_s=diagnosis_summary.supporting_duration_s,
        stable_frequency_min_hz=diagnosis_summary.stable_frequency_min_hz,
        stable_frequency_max_hz=diagnosis_summary.stable_frequency_max_hz,
        supporting_location_count=_supporting_location_count(diagnosis_summary),
        top_support_location=_top_support_location(diagnosis_summary),
        top_support_share=_top_support_share(diagnosis_summary),
        mean_relative_error=_mean_relative_error(diagnosis_summary),
        snr_db=_snr_db(diagnosis_summary),
        alternative_source=diagnosis_summary.alternative_source,
        has_reference_gap=diagnosis_summary.has_reference_gap,
        speed_gap_window_count=_speed_gap_window_count(diagnosis_summary),
        rpm_gap_window_count=_rpm_gap_window_count(diagnosis_summary),
        car_data_reference_scope=_car_data_reference_scope(diagnosis_summary),
        car_data_confidence=_car_data_confidence(diagnosis_summary),
        uses_summary_fallback=diagnosis_summary.uses_summary_fallback,
        fallback_reason=diagnosis_summary.fallback_reason,
        support_factors=tuple(
            _assessment_factor_from_summary_factor(factor)
            for factor in diagnosis_summary.support_factors
        ),
        counterevidence_factors=tuple(
            _assessment_factor_from_summary_factor(factor)
            for factor in diagnosis_summary.counterevidence_factors
        ),
        confidence_gap_to_alternative=diagnosis_summary.confidence_gap_to_alternative,
        ambiguous_diagnosis=diagnosis_summary.ambiguous_diagnosis,
        suspicious=diagnosis_summary.suspicious,
    )


def apply_report_confidence_fallback(
    facts: ReportConfidenceFacts,
    *,
    fallback_reason: str,
) -> ReportConfidenceFacts:
    """Mark report confidence as an explicit fallback without changing its score."""

    return apply_diagnosis_assessment_fallback(facts, fallback_reason=fallback_reason)


def project_whole_run_diagnosis_factors(
    confidence_facts: ReportConfidenceFacts,
) -> tuple[tuple[DiagnosisFactorResponse, ...], tuple[DiagnosisFactorResponse, ...]]:
    """Project stable support and counterevidence rows from canonical confidence facts."""

    support = tuple(_factor_payload(factor) for factor in confidence_facts.support_factors)
    counter = tuple(_factor_payload(factor) for factor in confidence_facts.counterevidence_factors)
    return (support, counter)


def score_report_confidence_inputs(
    inputs: ReportConfidenceScoringInputs,
) -> ReportConfidenceFacts:
    """Apply the canonical diagnosis assessment policy to report inputs."""

    return score_diagnosis_assessment_inputs(inputs)


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
    return DiagnosisAssessment(
        score_0_to_1=max(0.0, min(1.0, confidence)),
        label_key=(
            assessment.label_key if assessment is not None else _label_key_for_score(confidence)
        ),
        pct_text=(
            assessment.pct_text if assessment is not None else f"{max(0.0, confidence) * 100:.0f}%"
        ),
        tier=assessment.tier if assessment is not None else ("A" if confidence < 0.40 else "B"),
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
        car_data_reference_scope=None,
        car_data_confidence=None,
        uses_summary_fallback=True,
        fallback_reason=(assessment.reason if assessment is not None else "") or None,
        signal_keys=(),
        caveat_keys=("summary_only",) if evidence_facts.data_basis == "summary_only" else (),
    )


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


def _factor_payload(factor: DiagnosisAssessmentFactor) -> DiagnosisFactorResponse:
    return {
        "factor_key": cast(DiagnosisFactorKey, factor.factor_key),
        "polarity": cast(DiagnosisFactorPolarity, factor.polarity),
        "severity": cast(DiagnosisFactorSeverity, factor.severity),
        "weight": factor.weight,
        "details": _factor_details_payload(factor.details),
    }


def _factor_details_payload(
    details: DiagnosisAssessmentFactorDetails,
) -> DiagnosisFactorDetailsResponse:
    payload: DiagnosisFactorDetailsResponse = {}
    if details.raw_backed_sample_count is not None:
        payload["raw_backed_sample_count"] = details.raw_backed_sample_count
    if details.supporting_window_count is not None:
        payload["supporting_window_count"] = details.supporting_window_count
    if details.supporting_duration_s is not None:
        payload["supporting_duration_s"] = details.supporting_duration_s
    if details.stable_frequency_min_hz is not None:
        payload["stable_frequency_min_hz"] = details.stable_frequency_min_hz
    if details.stable_frequency_max_hz is not None:
        payload["stable_frequency_max_hz"] = details.stable_frequency_max_hz
    if details.frequency_span_hz is not None:
        payload["frequency_span_hz"] = details.frequency_span_hz
    if details.supporting_location_count is not None:
        payload["supporting_location_count"] = details.supporting_location_count
    if details.top_support_location is not None:
        payload["top_support_location"] = details.top_support_location
    if details.top_support_share is not None:
        payload["top_support_share"] = details.top_support_share
    if details.mean_relative_error is not None:
        payload["mean_relative_error"] = details.mean_relative_error
    if details.snr_db is not None:
        payload["snr_db"] = details.snr_db
    if details.alternative_source is not None:
        payload["alternative_source"] = details.alternative_source
    if details.speed_gap_window_count is not None:
        payload["speed_gap_window_count"] = details.speed_gap_window_count
    if details.rpm_gap_window_count is not None:
        payload["rpm_gap_window_count"] = details.rpm_gap_window_count
    if details.fallback_reason is not None:
        payload["fallback_reason"] = details.fallback_reason
    if details.car_data_reference_scope is not None:
        payload["car_data_reference_scope"] = details.car_data_reference_scope
    if details.car_data_confidence is not None:
        payload["car_data_confidence"] = details.car_data_confidence
    return payload


def _assessment_factor_from_summary_factor(
    factor: object,
) -> DiagnosisAssessmentFactor:
    typed_factor = cast("ReportDiagnosisFactor", factor)
    factor_key = cast(str, typed_factor.factor_key)
    polarity = cast(str, typed_factor.polarity)
    severity = cast(str, typed_factor.severity)
    weight = float(typed_factor.weight)
    raw_details = typed_factor.details
    details = DiagnosisAssessmentFactorDetails(
        raw_backed_sample_count=raw_details.raw_backed_sample_count,
        supporting_window_count=raw_details.supporting_window_count,
        supporting_duration_s=raw_details.supporting_duration_s,
        stable_frequency_min_hz=raw_details.stable_frequency_min_hz,
        stable_frequency_max_hz=raw_details.stable_frequency_max_hz,
        frequency_span_hz=raw_details.frequency_span_hz,
        supporting_location_count=raw_details.supporting_location_count,
        top_support_location=raw_details.top_support_location,
        top_support_share=raw_details.top_support_share,
        mean_relative_error=raw_details.mean_relative_error,
        snr_db=raw_details.snr_db,
        alternative_source=raw_details.alternative_source,
        speed_gap_window_count=raw_details.speed_gap_window_count,
        rpm_gap_window_count=raw_details.rpm_gap_window_count,
        fallback_reason=raw_details.fallback_reason,
        car_data_reference_scope=raw_details.car_data_reference_scope,
        car_data_confidence=raw_details.car_data_confidence,
    )
    return DiagnosisAssessmentFactor(
        factor_key=factor_key,
        polarity=polarity,
        severity=severity,
        weight=weight,
        details=details,
    )


def _raw_backed_sample_count(factors: tuple[object, ...]) -> int:
    for factor in factors:
        typed_factor = cast("ReportDiagnosisFactor", factor)
        if typed_factor.factor_key != "raw_backed":
            continue
        count = typed_factor.details.raw_backed_sample_count
        return int(count) if isinstance(count, int | float) else 0
    return 0


def _supporting_location_count(diagnosis_summary: ReportWholeRunDiagnosisSummary) -> int:
    for factor in (*diagnosis_summary.support_factors, *diagnosis_summary.counterevidence_factors):
        if factor.factor_key not in {
            "localized_support",
            "mixed_support_locations",
        }:
            continue
        count = factor.details.supporting_location_count
        if isinstance(count, int | float):
            return int(count)
    return diagnosis_summary.supporting_sensor_count or 0


def _top_support_location(diagnosis_summary: ReportWholeRunDiagnosisSummary) -> str | None:
    for factor in (*diagnosis_summary.support_factors, *diagnosis_summary.counterevidence_factors):
        if factor.factor_key not in {
            "localized_support",
            "mixed_support_locations",
        }:
            continue
        value = factor.details.top_support_location
        if isinstance(value, str) and value.strip():
            return value
    return diagnosis_summary.dominant_location


def _top_support_share(diagnosis_summary: ReportWholeRunDiagnosisSummary) -> float | None:
    for factor in (*diagnosis_summary.support_factors, *diagnosis_summary.counterevidence_factors):
        if factor.factor_key not in {
            "localized_support",
            "mixed_support_locations",
        }:
            continue
        value = factor.details.top_support_share
        if isinstance(value, int | float):
            return float(value)
    return None


def _mean_relative_error(diagnosis_summary: ReportWholeRunDiagnosisSummary) -> float | None:
    for factor in (*diagnosis_summary.support_factors, *diagnosis_summary.counterevidence_factors):
        if factor.factor_key not in {"tight_order_lock", "loose_order_lock"}:
            continue
        value = factor.details.mean_relative_error
        if isinstance(value, int | float):
            return float(value)
    return None


def _snr_db(diagnosis_summary: ReportWholeRunDiagnosisSummary) -> float | None:
    for factor in (*diagnosis_summary.support_factors, *diagnosis_summary.counterevidence_factors):
        if factor.factor_key not in {"clean_signal", "noisy_signal"}:
            continue
        value = factor.details.snr_db
        if isinstance(value, int | float):
            return float(value)
    return None


def _speed_gap_window_count(diagnosis_summary: ReportWholeRunDiagnosisSummary) -> int:
    for factor in diagnosis_summary.counterevidence_factors:
        if factor.factor_key != "speed_context_gaps":
            continue
        value = factor.details.speed_gap_window_count
        if isinstance(value, int | float):
            return int(value)
    return 0


def _rpm_gap_window_count(diagnosis_summary: ReportWholeRunDiagnosisSummary) -> int:
    for factor in diagnosis_summary.counterevidence_factors:
        if factor.factor_key != "rpm_context_gaps":
            continue
        value = factor.details.rpm_gap_window_count
        if isinstance(value, int | float):
            return int(value)
    return 0


def _car_data_reference_scope(
    diagnosis_summary: ReportWholeRunDiagnosisSummary,
) -> str | None:
    for factor in (*diagnosis_summary.support_factors, *diagnosis_summary.counterevidence_factors):
        value = factor.details.car_data_reference_scope
        if isinstance(value, str) and value.strip():
            return value
    return None


def _car_data_confidence(
    diagnosis_summary: ReportWholeRunDiagnosisSummary,
) -> str | None:
    for factor in (*diagnosis_summary.support_factors, *diagnosis_summary.counterevidence_factors):
        value = factor.details.car_data_confidence
        if isinstance(value, str) and value.strip():
            return value
    return None


def _label_key_for_score(score: float) -> str:
    if score >= 0.75:
        return "CONFIDENCE_HIGH"
    if score >= 0.45:
        return "CONFIDENCE_MEDIUM"
    return "CONFIDENCE_LOW"
