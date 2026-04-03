"""Section and appendix data builders for PDF mapping."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.adapters.pdf._candidate_resolver import PrimaryCandidateContext
from vibesensor.adapters.pdf.report_context import ReportMappingContext
from vibesensor.adapters.pdf.report_data import (
    AppendixAData,
    AppendixBData,
    AppendixCData,
    AppendixDData,
    DataTrustItem,
    FindingPresentation,
    MeasurementRow,
    NextStep,
    RankedCandidateRow,
    Report,
    ReportLabelValueRow,
    TimelineGraphData,
    TimelineGraphInterval,
    TopologyIntensityRow,
    VerdictPageData,
)
from vibesensor.domain import Finding, LocationIntensitySummary, TestRun
from vibesensor.shared.boundaries.report_prepared_input import (
    PreparedAppendixADisplay,
    PreparedAppendixBSummaryDisplay,
    PreparedReportFacts,
    PreparedVerdictDisplay,
)
from vibesensor.shared.report_presentation import display_location

from .measurements import _evidence_chain_rows, _sensor_observation_matrix_rows
from .narrative_summaries import (
    _context_summary_text,
    _evidence_summary_text,
    _observation_texts,
    _phase_summary_text,
    _run_limits_summary_text,
)

__all__ = [
    "_build_appendix_a_data",
    "_build_appendix_b_data",
    "_build_appendix_c_data",
    "_build_appendix_d_data",
    "_build_timeline_graph_data",
    "_build_verdict_page_data",
    "_finding_to_presentation",
]


def _build_timeline_graph_data(
    report_facts: PreparedReportFacts,
    *,
    duration_s: float | None,
) -> TimelineGraphData | None:
    max_interval_end = max(
        (interval.end_t_s or 0.0 for interval in report_facts.timeline_intervals),
        default=0.0,
    )
    resolved_duration = max(float(duration_s or 0.0), max_interval_end)
    if resolved_duration <= 0:
        return None
    intervals: list[TimelineGraphInterval] = []
    max_speed = 0.0
    ordered_intervals = sorted(
        report_facts.timeline_intervals,
        key=lambda interval: (
            interval.start_t_s is None,
            interval.start_t_s or 0.0,
            interval.end_t_s or 0.0,
        ),
    )
    for interval in ordered_intervals:
        if interval.start_t_s is None or interval.end_t_s is None:
            continue
        start_t_s = max(0.0, interval.start_t_s)
        end_t_s = min(resolved_duration, interval.end_t_s)
        if end_t_s <= start_t_s:
            continue
        present_speeds = [
            speed for speed in (interval.speed_min_kmh, interval.speed_max_kmh) if speed is not None
        ]
        if present_speeds:
            max_speed = max(max_speed, *present_speeds)
        intervals.append(
            TimelineGraphInterval(
                phase_label=interval.phase,
                start_t_s=start_t_s,
                end_t_s=end_t_s,
                speed_min_kmh=interval.speed_min_kmh,
                speed_max_kmh=interval.speed_max_kmh,
                has_fault_evidence=interval.has_fault_evidence,
            ),
        )
    if not intervals:
        return None
    speed_ceiling_kmh = max(10.0, max_speed * 1.10 if max_speed > 0 else 10.0)
    return TimelineGraphData(
        duration_s=resolved_duration,
        speed_ceiling_kmh=speed_ceiling_kmh,
        intervals=tuple(intervals),
    )


def _build_verdict_page_data(
    *,
    verdict: PreparedVerdictDisplay,
    proof_summary: str | None,
    timeline_graph: TimelineGraphData | None,
) -> VerdictPageData:
    return VerdictPageData(
        speed_window_label=verdict.speed_window_label,
        suspected_source=verdict.suspected_source,
        inspect_first=verdict.inspect_first,
        action_status=verdict.action_status,
        action_status_note=verdict.action_status_note,
        reason_sentence=verdict.reason_sentence,
        dominant_corner=verdict.dominant_corner,
        runner_up_corner=verdict.runner_up_corner,
        location_confidence=verdict.location_confidence,
        coverage_label=verdict.coverage_label,
        also_consider=verdict.also_consider,
        proof_summary=proof_summary,
        proof_caveat=verdict.proof_caveat,
        proof_panel_title=verdict.proof_panel_title,
        timeline_graph=timeline_graph,
        footer_routes=verdict.footer_routes,
    )


def _build_appendix_a_data(
    *,
    appendix: PreparedAppendixADisplay,
    next_steps: list[NextStep],
) -> AppendixAData:
    if appendix.mode == "recapture":
        return AppendixAData(
            mode="recapture",
            capture_issues=list(appendix.capture_issues),
            capture_changes=[step.action for step in next_steps],
            capture_conditions=list(appendix.capture_conditions),
        )
    return AppendixAData(
        mode="workflow",
        primary_source=appendix.primary_source,
        alternative_source=appendix.alternative_source,
        why_primary_first=appendix.why_primary_first,
        why_alternative_next=appendix.why_alternative_next,
        next_if_clean=appendix.next_if_clean,
        ranked_candidates=[
            RankedCandidateRow(
                source_name=row.source_name,
                confidence_pct=row.confidence_pct,
                inspect_first=row.inspect_first,
                path_role=row.path_role,
                reason=row.reason,
            )
            for row in appendix.ranked_candidates
        ],
    )


def _build_appendix_b_data(
    *,
    aggregate: TestRun,
    appendix: PreparedAppendixBSummaryDisplay,
    sensor_locations: list[str],
    sensor_intensity: list[LocationIntensitySummary],
    tr: Callable[..., str],
) -> AppendixBData:
    ranked_rows = sorted(
        sensor_intensity,
        key=lambda row: (
            row.p95_intensity_db if row.p95_intensity_db is not None else float("-inf"),
        ),
        reverse=True,
    )
    intensity_rows = [
        TopologyIntensityRow(
            location=display_location(row.location, short=False, tr=tr),
            p95_db=row.p95_intensity_db,
            coverage_state=(
                tr("REPORT_COVERAGE_STATE_PARTIAL")
                if row.partial_coverage or row.sample_coverage_warning
                else tr("REPORT_COVERAGE_STATE_COMPLETE")
            ),
        )
        for row in ranked_rows
    ]
    sensor_observation_rows = _sensor_observation_matrix_rows(
        aggregate,
        sensor_locations=sensor_locations,
        tr=tr,
    )
    return AppendixBData(
        dominant_corner=appendix.dominant_corner,
        runner_up_corner=appendix.runner_up_corner,
        dominance_ratio_text=appendix.dominance_ratio_text,
        location_confidence=appendix.location_confidence,
        coverage_label=appendix.coverage_label,
        coverage_notes=list(appendix.coverage_notes),
        intensity_rows=intensity_rows,
        sensor_observation_rows=sensor_observation_rows,
    )


def _build_appendix_c_data(
    *,
    primary: PrimaryCandidateContext,
    aggregate: TestRun,
    measurements: list[MeasurementRow],
    report_facts: PreparedReportFacts,
    data_trust: list[DataTrustItem],
    tr: Callable[..., str],
) -> AppendixCData:
    evidence_rows = _evidence_chain_rows(aggregate, measurements=measurements, tr=tr)
    speed_windows = [row.speed_window for row in evidence_rows if row.speed_window]
    speed_summary = (
        ", ".join(dict.fromkeys(speed_windows))
        if speed_windows
        else tr("REPORT_SPEED_SUMMARY_NONE")
    )
    return AppendixCData(
        evidence_chain_rows=evidence_rows,
        measurement_rows=measurements,
        evidence_summary=_evidence_summary_text(aggregate, primary, report_facts, tr=tr),
        measurement_guide=tr("REPORT_MEASUREMENT_GUIDE"),
        context_summary=_context_summary_text(primary, report_facts, tr=tr),
        limits_summary=_run_limits_summary_text(report_facts, tr=tr),
        speed_band_summary=speed_summary,
        phase_summary=_phase_summary_text(aggregate, report_facts, tr=tr),
        observations=_observation_texts(aggregate, tr=tr),
        suitability_items=data_trust,
    )


def _build_appendix_d_data(
    *,
    context: ReportMappingContext,
    report: Report,
    tr: Callable[..., str],
) -> AppendixDData:
    rows = [
        ReportLabelValueRow(label=tr("RUN_DATE"), value=context.date_str),
        ReportLabelValueRow(label=tr("RUN_ID"), value=report.run_id),
        ReportLabelValueRow(label=tr("TIRE_SIZE"), value=context.tire_spec_text or tr("UNKNOWN")),
    ]
    sensor_model = str(context.sensor_model or "").strip()
    if sensor_model and sensor_model.casefold() != tr("UNKNOWN").casefold():
        rows.append(ReportLabelValueRow(label=tr("SENSOR_MODEL"), value=sensor_model))
    firmware_version = str(context.firmware_version or "").strip()
    if firmware_version and firmware_version.casefold() not in {"none", tr("UNKNOWN").casefold()}:
        rows.append(ReportLabelValueRow(label=tr("FIRMWARE_VERSION"), value=firmware_version))
    rows.extend(
        [
            ReportLabelValueRow(
                label=tr("REPORT_ANALYSIS_ROWS_LABEL"),
                value=str(context.sample_count),
            ),
            ReportLabelValueRow(
                label=tr("RAW_SAMPLE_RATE_HZ_LABEL"),
                value=context.sample_rate_hz or tr("UNKNOWN"),
            ),
        ]
    )
    return AppendixDData(rows=rows)


def _finding_to_presentation(f: Finding) -> FindingPresentation:
    """Convert a domain ``Finding`` to a presentation-ready snapshot."""
    return FindingPresentation(
        suspected_source=str(f.suspected_source),
        severity=f.severity,
        strongest_location=f.strongest_location,
        peak_classification=f.peaks.classification,
        order=f.order,
        frequency_hz=f.frequency_hz,
        effective_confidence=f.effective_confidence,
    )
