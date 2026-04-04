"""Section and appendix data builders for PDF mapping."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.domain import TestRun
from vibesensor.shared.boundaries.reporting import PreparedReportFacts
from vibesensor.shared.boundaries.reporting.document import (
    AppendixCData,
    AppendixDData,
    DataTrustItem,
    MeasurementRow,
    ReportLabelValueRow,
    TimelineGraphData,
    TimelineGraphInterval,
)
from vibesensor.use_cases.history.report_document._candidate_resolver import PrimaryCandidateContext

from .composition import ReportDocumentComposition
from .measurements import _evidence_chain_rows
from .narrative_summaries import (
    _context_summary_text,
    _evidence_summary_text,
    _observation_texts,
    _phase_summary_text,
    _run_limits_summary_text,
)

__all__ = [
    "_build_appendix_c_data",
    "_build_appendix_d_data",
    "_build_timeline_graph_data",
]


def _build_timeline_graph_data(
    report_facts: PreparedReportFacts,
    *,
    duration_s: float | None,
) -> TimelineGraphData | None:
    max_interval_end = max(
        (interval.end_t_s or 0.0 for interval in report_facts.run.timeline_intervals),
        default=0.0,
    )
    resolved_duration = max(float(duration_s or 0.0), max_interval_end)
    if resolved_duration <= 0:
        return None
    intervals: list[TimelineGraphInterval] = []
    max_speed = 0.0
    ordered_intervals = sorted(
        report_facts.run.timeline_intervals,
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


def _build_appendix_c_data(
    *,
    primary: PrimaryCandidateContext,
    aggregate: TestRun,
    measurements: list[MeasurementRow],
    report_facts: PreparedReportFacts,
    composition: ReportDocumentComposition,
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
        limits_summary=_run_limits_summary_text(
            report_facts,
            composition,
            tr=tr,
        ),
        speed_band_summary=speed_summary,
        phase_summary=_phase_summary_text(aggregate, report_facts, tr=tr),
        observations=_observation_texts(aggregate, tr=tr),
        suitability_items=data_trust,
    )


def _build_appendix_d_data(
    *,
    date_str: str,
    run_id: str,
    tire_spec_text: str | None,
    sensor_model: str | None,
    firmware_version: str | None,
    sample_count: int,
    sample_rate_hz: str | None,
    tr: Callable[..., str],
) -> AppendixDData:
    rows = [
        ReportLabelValueRow(label=tr("RUN_DATE"), value=date_str),
        ReportLabelValueRow(label=tr("RUN_ID"), value=run_id),
        ReportLabelValueRow(label=tr("TIRE_SIZE"), value=tire_spec_text or tr("UNKNOWN")),
    ]
    sensor_model = str(sensor_model or "").strip()
    if sensor_model and sensor_model.casefold() != tr("UNKNOWN").casefold():
        rows.append(ReportLabelValueRow(label=tr("SENSOR_MODEL"), value=sensor_model))
    firmware_version = str(firmware_version or "").strip()
    if firmware_version and firmware_version.casefold() not in {"none", tr("UNKNOWN").casefold()}:
        rows.append(ReportLabelValueRow(label=tr("FIRMWARE_VERSION"), value=firmware_version))
    rows.extend(
        [
            ReportLabelValueRow(
                label=tr("REPORT_ANALYSIS_ROWS_LABEL"),
                value=str(sample_count),
            ),
            ReportLabelValueRow(
                label=tr("RAW_SAMPLE_RATE_HZ_LABEL"),
                value=sample_rate_hz or tr("UNKNOWN"),
            ),
        ]
    )
    return AppendixDData(rows=rows)
