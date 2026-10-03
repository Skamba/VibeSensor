"""Prepared report-confidence facts for the summary diagnosis.

The headline score, label and percentage are the primary finding's own
confidence, exactly as the UI shows it. The scored assessment only contributes
the support and counterevidence factors that explain it.
"""

from __future__ import annotations

from dataclasses import replace

from vibesensor.domain.diagnosis_assessment import (
    DiagnosisAssessment,
    DiagnosisAssessmentInputs,
    score_diagnosis_assessment_inputs,
)
from vibesensor.report.decision_facts import ReportDecisionFacts
from vibesensor.report.evidence_facts import ReportEvidenceFacts
from vibesensor.report.projection import PrimaryReportFacts

__all__ = [
    "ReportConfidenceFacts",
    "ReportConfidenceScoringInputs",
    "build_report_confidence_facts",
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
) -> ReportConfidenceFacts:
    """Build report confidence for the summary diagnosis's primary finding."""

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

    scored = score_report_confidence_inputs(
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
        )
    )
    return _with_finding_headline(scored, primary_candidate=primary_candidate)


def _with_finding_headline(
    assessment: ReportConfidenceFacts,
    *,
    primary_candidate: PrimaryReportFacts,
) -> ReportConfidenceFacts:
    finding = primary_candidate.domain_primary
    if finding is None:
        return assessment
    finding_assessment = finding.confidence_assessment
    if finding_assessment is None:
        label_key, _tone, pct_text = finding.confidence_label()
        return replace(
            assessment,
            score_0_to_1=finding.effective_confidence,
            label_key=label_key,
            pct_text=pct_text,
        )
    return replace(
        assessment,
        score_0_to_1=finding.effective_confidence,
        label_key=finding_assessment.label_key,
        pct_text=finding_assessment.pct_text,
        tier=finding_assessment.tier,
    )


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


def _label_key_for_score(score: float) -> str:
    if score >= 0.75:
        return "CONFIDENCE_HIGH"
    if score >= 0.45:
        return "CONFIDENCE_MEDIUM"
    return "CONFIDENCE_LOW"
