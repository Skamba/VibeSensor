"""Deterministic whole-run diagnosis ranking over persisted context/order/spatial summaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from vibesensor.shared.boundaries.reporting.confidence_facts import (
    ReportConfidenceFacts,
    ReportConfidenceScoringInputs,
    project_whole_run_diagnosis_factors,
    score_report_confidence_inputs,
)
from vibesensor.shared.types.whole_run_analysis import WholeRunContextInterval
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import OrderTraceSummary
from vibesensor.use_cases.diagnostics.spatial_evidence_contracts import SpatialEvidenceSummary
from vibesensor.use_cases.diagnostics.whole_run_diagnosis_contracts import (
    DiagnosisExemplarReference,
    DiagnosisFactor,
    DiagnosisFactorDetails,
    WholeRunDiagnosisSummary,
)

__all__ = ["build_whole_run_diagnosis_summaries"]

_CLOSE_ALTERNATIVE_SCORE_GAP = 0.10
_AMBIGUOUS_DIAGNOSIS_SCORE_GAP = 0.05


@dataclass(frozen=True, slots=True)
class _CandidateEvaluation:
    order_summary: OrderTraceSummary
    spatial_summary: SpatialEvidenceSummary | None
    confidence: ReportConfidenceFacts
    support_factors: tuple[DiagnosisFactor, ...]
    counterevidence_factors: tuple[DiagnosisFactor, ...]
    alternative_source: str | None
    confidence_gap_to_alternative: float | None


def build_whole_run_diagnosis_summaries(
    *,
    analysis_metadata: Mapping[str, object],
    context_intervals: tuple[WholeRunContextInterval, ...],
    order_summaries: tuple[OrderTraceSummary, ...],
    spatial_summaries: tuple[SpatialEvidenceSummary, ...],
) -> tuple[WholeRunDiagnosisSummary, ...]:
    """Rank persisted whole-run candidates into compact diagnosis summaries."""

    if not order_summaries:
        return ()
    spatial_by_key = {summary.candidate_key: summary for summary in spatial_summaries}
    initial = tuple(
        _evaluate_candidate(
            analysis_metadata=analysis_metadata,
            order_summary=order_summary,
            spatial_summary=spatial_by_key.get(order_summary.hypothesis_key),
            alternative_source=None,
            confidence_gap_to_alternative=None,
        )
        for order_summary in order_summaries
    )
    final = tuple(
        _reevaluate_with_alternative(candidate, initial, analysis_metadata) for candidate in initial
    )
    ranked = sorted(
        final,
        key=lambda candidate: (
            -candidate.confidence.score_0_to_1,
            -_factor_weight_sum(candidate.support_factors),
            _factor_weight_sum(candidate.counterevidence_factors),
            -candidate.order_summary.lock_score,
            -candidate.order_summary.support_ratio,
            candidate.order_summary.hypothesis_key,
        ),
    )
    summaries: list[WholeRunDiagnosisSummary] = []
    for rank, candidate in enumerate(ranked, start=1):
        summaries.append(
            WholeRunDiagnosisSummary(
                diagnosis_key=candidate.order_summary.hypothesis_key,
                suspected_source=candidate.order_summary.suspected_source,
                rank=rank,
                data_basis=candidate.confidence.data_basis,  # type: ignore[arg-type]
                support_score=round(_factor_weight_sum(candidate.support_factors), 2),
                counterevidence_score=round(
                    _factor_weight_sum(candidate.counterevidence_factors), 2
                ),
                total_score=round(candidate.confidence.score_0_to_1, 2),
                order_hypothesis_key=candidate.order_summary.hypothesis_key,
                spatial_candidate_key=(
                    candidate.spatial_summary.candidate_key
                    if candidate.spatial_summary is not None
                    else None
                ),
                location_proof_basis=(
                    candidate.spatial_summary.proof_basis
                    if candidate.spatial_summary is not None
                    else None
                ),
                supporting_window_count=candidate.order_summary.matched_window_count,
                supporting_duration_s=_supporting_duration_s(candidate.order_summary),
                supporting_sensor_count=(
                    candidate.spatial_summary.supporting_sensor_count
                    if candidate.spatial_summary is not None
                    else None
                ),
                stable_frequency_min_hz=candidate.order_summary.stable_frequency_min_hz,
                stable_frequency_max_hz=candidate.order_summary.stable_frequency_max_hz,
                dominant_location=(
                    candidate.spatial_summary.dominant_location
                    if candidate.spatial_summary is not None
                    else None
                ),
                runner_up_location=(
                    candidate.spatial_summary.runner_up_location
                    if candidate.spatial_summary is not None
                    else None
                ),
                dominant_phase=candidate.order_summary.dominant_phase,
                dominant_speed_band=candidate.order_summary.dominant_speed_band,
                location_separation_db=(
                    candidate.spatial_summary.location_separation_db
                    if candidate.spatial_summary is not None
                    else None
                ),
                dominance_ratio=(
                    candidate.spatial_summary.dominance_ratio
                    if candidate.spatial_summary is not None
                    else None
                ),
                alternative_source=candidate.alternative_source,
                confidence_gap_to_alternative=candidate.confidence_gap_to_alternative,
                ambiguous_diagnosis=bool(
                    candidate.confidence_gap_to_alternative is not None
                    and candidate.confidence_gap_to_alternative <= _AMBIGUOUS_DIAGNOSIS_SCORE_GAP
                ),
                ambiguous_location=(
                    candidate.spatial_summary.ambiguous_location
                    if candidate.spatial_summary is not None
                    else False
                ),
                suspicious=_is_suspicious(candidate),
                weak_spatial_separation=(
                    candidate.spatial_summary.weak_spatial_separation
                    if candidate.spatial_summary is not None
                    else False
                ),
                has_reference_gap=candidate.confidence.has_reference_gap,
                uses_summary_fallback=candidate.confidence.uses_summary_fallback,
                fallback_reason=candidate.confidence.fallback_reason,
                exemplar_references=_exemplar_references(candidate, context_intervals),
                support_factors=candidate.support_factors,
                counterevidence_factors=candidate.counterevidence_factors,
            )
        )
    return tuple(summaries)


def _reevaluate_with_alternative(
    candidate: _CandidateEvaluation,
    initial: tuple[_CandidateEvaluation, ...],
    analysis_metadata: Mapping[str, object],
) -> _CandidateEvaluation:
    alternative = _closest_alternative_candidate(candidate, initial)
    if alternative is None:
        return candidate
    score_gap = abs(candidate.confidence.score_0_to_1 - alternative.confidence.score_0_to_1)
    if score_gap > _CLOSE_ALTERNATIVE_SCORE_GAP:
        return candidate
    return _evaluate_candidate(
        analysis_metadata=analysis_metadata,
        order_summary=candidate.order_summary,
        spatial_summary=candidate.spatial_summary,
        alternative_source=alternative.order_summary.suspected_source,
        confidence_gap_to_alternative=round(score_gap, 2),
    )


def _closest_alternative_candidate(
    candidate: _CandidateEvaluation,
    evaluations: tuple[_CandidateEvaluation, ...],
) -> _CandidateEvaluation | None:
    alternatives = [
        other
        for other in evaluations
        if other.order_summary.hypothesis_key != candidate.order_summary.hypothesis_key
        and other.order_summary.suspected_source != candidate.order_summary.suspected_source
    ]
    if not alternatives:
        return None
    return min(
        alternatives,
        key=lambda other: (
            abs(candidate.confidence.score_0_to_1 - other.confidence.score_0_to_1),
            -other.confidence.score_0_to_1,
            other.order_summary.hypothesis_key,
        ),
    )


def _evaluate_candidate(
    *,
    analysis_metadata: Mapping[str, object],
    order_summary: OrderTraceSummary,
    spatial_summary: SpatialEvidenceSummary | None,
    alternative_source: str | None,
    confidence_gap_to_alternative: float | None,
) -> _CandidateEvaluation:
    scoring_inputs = ReportConfidenceScoringInputs(
        base_confidence=_base_confidence(order_summary, spatial_summary),
        data_basis=_data_basis(analysis_metadata, spatial_summary),
        raw_backed_sample_count=_count(analysis_metadata.get("raw_backed_sample_count")),
        supporting_window_count=order_summary.matched_window_count,
        supporting_duration_s=_supporting_duration_s(order_summary),
        stable_frequency_min_hz=order_summary.stable_frequency_min_hz,
        stable_frequency_max_hz=order_summary.stable_frequency_max_hz,
        supporting_location_count=_supporting_location_count(spatial_summary),
        top_support_location=_top_support_location(spatial_summary),
        top_support_share=_top_support_share(spatial_summary),
        mean_relative_error=order_summary.mean_relative_error,
        snr_db=_snr_db(order_summary),
        alternative_source=alternative_source,
        has_reference_gap=_has_reference_gap(order_summary),
        weak_spatial=bool(spatial_summary and spatial_summary.weak_spatial_separation),
        context_traceable=True,
        context_source=_context_source(analysis_metadata),
        speed_gap_window_count=_count(
            analysis_metadata.get("whole_run_context_missing_speed_window_count")
        )
        + _count(analysis_metadata.get("whole_run_context_stale_speed_window_count")),
        rpm_gap_window_count=_count(
            analysis_metadata.get("whole_run_context_missing_rpm_window_count")
        )
        + _count(analysis_metadata.get("whole_run_context_stale_rpm_window_count")),
    )
    confidence = score_report_confidence_inputs(scoring_inputs)
    support_payloads, counter_payloads = project_whole_run_diagnosis_factors(confidence)
    return _CandidateEvaluation(
        order_summary=order_summary,
        spatial_summary=spatial_summary,
        confidence=confidence,
        support_factors=tuple(_diagnosis_factor_from_payload(row) for row in support_payloads),
        counterevidence_factors=tuple(
            _diagnosis_factor_from_payload(row) for row in counter_payloads
        ),
        alternative_source=alternative_source,
        confidence_gap_to_alternative=confidence_gap_to_alternative,
    )


def _base_confidence(
    order_summary: OrderTraceSummary,
    spatial_summary: SpatialEvidenceSummary | None,
) -> float:
    components = [
        order_summary.support_ratio,
        order_summary.reference_coverage_ratio,
        order_summary.contiguous_support_ratio,
        order_summary.lock_score,
        max(0.0, 1.0 - order_summary.drift_score),
    ]
    if order_summary.mean_relative_error is not None:
        components.append(max(0.0, 1.0 - min(order_summary.mean_relative_error / 0.25, 1.0)))
    if spatial_summary is not None:
        if spatial_summary.coherence_ratio is not None:
            components.append(spatial_summary.coherence_ratio)
        components.append(
            min(
                1.0,
                spatial_summary.supporting_window_count
                / max(1, spatial_summary.total_window_count),
            )
        )
        if spatial_summary.dominance_ratio is not None:
            components.append(min(1.0, max(0.0, spatial_summary.dominance_ratio - 1.0)))
    return sum(components) / len(components) if components else 0.0


def _data_basis(
    analysis_metadata: Mapping[str, object],
    spatial_summary: SpatialEvidenceSummary | None,
) -> str:
    raw_capture_mode = str(analysis_metadata.get("raw_capture_mode") or "").strip().lower()
    if raw_capture_mode in {"raw_backed", "summary_only"}:
        return raw_capture_mode
    if (
        spatial_summary is not None
        and spatial_summary.proof_basis == "supporting_windows_summary_only"
    ):
        return "summary_only"
    return "raw_backed"


def _context_source(analysis_metadata: Mapping[str, object]) -> str:
    if bool(analysis_metadata.get("whole_run_context_available")):
        return "whole_run"
    if _data_basis(analysis_metadata, None) == "summary_only":
        return "summary_only"
    return "legacy"


def _supporting_duration_s(order_summary: OrderTraceSummary) -> float | None:
    durations = [
        interval.end_t_s - interval.start_t_s
        for interval in order_summary.support_intervals
        if interval.start_t_s is not None
        and interval.end_t_s is not None
        and interval.end_t_s >= interval.start_t_s
    ]
    if not durations:
        return None
    return sum(durations)


def _snr_db(order_summary: OrderTraceSummary) -> float | None:
    if order_summary.peak_intensity_db is None or order_summary.mean_vibration_strength_db is None:
        return None
    return order_summary.peak_intensity_db - order_summary.mean_vibration_strength_db


def _has_reference_gap(order_summary: OrderTraceSummary) -> bool:
    return order_summary.reference_coverage_ratio < 0.999


def _supporting_location_count(spatial_summary: SpatialEvidenceSummary | None) -> int:
    if spatial_summary is None:
        return 0
    return len(
        [row for row in spatial_summary.location_summaries if row.supporting_window_count > 0]
    )


def _top_support_location(spatial_summary: SpatialEvidenceSummary | None) -> str | None:
    if spatial_summary is None or not spatial_summary.location_summaries:
        return None
    return spatial_summary.location_summaries[0].location


def _top_support_share(spatial_summary: SpatialEvidenceSummary | None) -> float | None:
    if spatial_summary is None or not spatial_summary.location_summaries:
        return None
    total = sum(row.supporting_window_count for row in spatial_summary.location_summaries)
    if total <= 0:
        return None
    return spatial_summary.location_summaries[0].supporting_window_count / total


def _diagnosis_factor_from_payload(payload: Mapping[str, object]) -> DiagnosisFactor:
    details_payload = payload.get("details")
    details_mapping = details_payload if isinstance(details_payload, Mapping) else {}
    return DiagnosisFactor(
        factor_key=str(payload.get("factor_key")),  # type: ignore[arg-type]
        polarity=str(payload.get("polarity")),  # type: ignore[arg-type]
        severity=str(payload.get("severity")),  # type: ignore[arg-type]
        weight=_optional_float(payload.get("weight")) or 0.0,
        details=DiagnosisFactorDetails(
            raw_backed_sample_count=_optional_count(details_mapping.get("raw_backed_sample_count")),
            supporting_window_count=_optional_count(details_mapping.get("supporting_window_count")),
            supporting_duration_s=_optional_float(details_mapping.get("supporting_duration_s")),
            stable_frequency_min_hz=_optional_float(details_mapping.get("stable_frequency_min_hz")),
            stable_frequency_max_hz=_optional_float(details_mapping.get("stable_frequency_max_hz")),
            frequency_span_hz=_optional_float(details_mapping.get("frequency_span_hz")),
            supporting_location_count=_optional_count(
                details_mapping.get("supporting_location_count")
            ),
            top_support_location=_optional_text(details_mapping.get("top_support_location")),
            top_support_share=_optional_float(details_mapping.get("top_support_share")),
            mean_relative_error=_optional_float(details_mapping.get("mean_relative_error")),
            snr_db=_optional_float(details_mapping.get("snr_db")),
            alternative_source=_optional_text(details_mapping.get("alternative_source")),
            speed_gap_window_count=_optional_count(details_mapping.get("speed_gap_window_count")),
            rpm_gap_window_count=_optional_count(details_mapping.get("rpm_gap_window_count")),
            fallback_reason=_optional_text(details_mapping.get("fallback_reason")),
        ),
    )


def _exemplar_references(
    candidate: _CandidateEvaluation,
    context_intervals: tuple[WholeRunContextInterval, ...],
) -> tuple[DiagnosisExemplarReference, ...]:
    references: list[DiagnosisExemplarReference] = []
    order_summary = candidate.order_summary
    if order_summary.exemplar_interval_index is not None:
        references.append(
            DiagnosisExemplarReference(
                kind="order_support_interval",
                order_hypothesis_key=order_summary.hypothesis_key,
                support_interval_index=order_summary.exemplar_interval_index,
                phase=order_summary.dominant_phase,
                speed_band=order_summary.dominant_speed_band,
            )
        )
    if (
        candidate.spatial_summary is not None
        and candidate.spatial_summary.dominant_location is not None
    ):
        references.append(
            DiagnosisExemplarReference(
                kind="spatial_location",
                spatial_candidate_key=candidate.spatial_summary.candidate_key,
                location=candidate.spatial_summary.dominant_location,
            )
        )
    context_interval = _matching_context_interval(order_summary, context_intervals)
    if context_interval is not None:
        references.append(
            DiagnosisExemplarReference(
                kind="whole_run_context_interval",
                context_segment_index=context_interval.segment_index,
                phase=context_interval.phase.value,
                speed_band=context_interval.speed_band,
            )
        )
    return tuple(references)


def _matching_context_interval(
    order_summary: OrderTraceSummary,
    context_intervals: tuple[WholeRunContextInterval, ...],
) -> WholeRunContextInterval | None:
    if not context_intervals:
        return None
    desired_phase = _normalized_text(order_summary.dominant_phase)
    desired_speed_band = _normalized_speed_band(order_summary.dominant_speed_band)
    for interval in context_intervals:
        if desired_phase and _normalized_text(interval.phase.value) != desired_phase:
            continue
        if desired_speed_band:
            interval_band = _normalized_speed_band(interval.speed_band)
            if interval_band and interval_band != desired_speed_band:
                continue
        return interval
    if desired_phase:
        for interval in context_intervals:
            if _normalized_text(interval.phase.value) == desired_phase:
                return interval
    return context_intervals[0]


def _is_suspicious(candidate: _CandidateEvaluation) -> bool:
    suspicious_factor_keys = {
        "drifting_frequency",
        "mixed_support_locations",
        "weak_spatial",
        "close_alternative",
    }
    if (
        candidate.confidence_gap_to_alternative is not None
        and candidate.confidence_gap_to_alternative <= _AMBIGUOUS_DIAGNOSIS_SCORE_GAP
    ):
        return True
    return any(
        factor.factor_key in suspicious_factor_keys for factor in candidate.counterevidence_factors
    )


def _factor_weight_sum(factors: tuple[DiagnosisFactor, ...]) -> float:
    return sum(factor.weight for factor in factors)


def _count(value: object) -> int:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def _optional_count(value: object) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _normalized_text(value: str | None) -> str:
    return str(value or "").strip().lower()


def _normalized_speed_band(value: str | None) -> str:
    text = _normalized_text(value)
    return text.replace("km/h", "").replace(" ", "")
