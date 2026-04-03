"""Focused builder for canonical report-document field mapping.

Owns the mapping from resolved report sections and prepared report inputs into
``ReportDocument``. Keeps the field assignment explicit and testable while
the orchestration layer handles section resolution.
"""

from __future__ import annotations

from vibesensor.domain import LocationHotspotRow, LocationIntensitySummary
from vibesensor.shared.boundaries.reporting.contracts import PreparedReportInput
from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    AppendixBData,
    AppendixCData,
    AppendixDData,
    DataTrustItem,
    FindingPresentation,
    NextStep,
    PatternEvidence,
    PeakRow,
    Report,
    ReportDocument,
    SystemFindingCard,
    VerdictPageData,
)
from vibesensor.use_cases.history.report_document._candidate_resolver import PrimaryCandidateContext


def build_report_document_data(
    *,
    prepared: PreparedReportInput,
    report: Report,
    report_date_text: str,
    report_start_time_utc: str | None,
    report_end_time_utc: str | None,
    primary: PrimaryCandidateContext,
    title: str,
    observed: PatternEvidence,
    system_cards: list[SystemFindingCard],
    next_steps: list[NextStep],
    data_trust: list[DataTrustItem],
    pattern_evidence: PatternEvidence,
    peak_rows: list[PeakRow],
    findings: list[FindingPresentation],
    top_causes: list[FindingPresentation],
    sensor_intensity: list[LocationIntensitySummary],
    hotspot_rows: list[LocationHotspotRow],
    verdict_page: VerdictPageData | None = None,
    appendix_a: AppendixAData | None = None,
    appendix_b: AppendixBData | None = None,
    appendix_c: AppendixCData | None = None,
    appendix_d: AppendixDData | None = None,
) -> ReportDocument:
    """Map resolved report sections into ``ReportDocument``.

    All section resolution (candidate selection, card building, etc.) is done
    before this function is called.  This builder only performs field
    assignment and simple fallback defaults so it stays easily testable.
    """
    report_facts = prepared.report_facts
    summary_metadata = prepared.summary.metadata
    return ReportDocument(
        title=title,
        run_datetime=report_date_text,
        run_id=report.run_id,
        duration_text=report_facts.duration_text,
        start_time_utc=report_start_time_utc,
        end_time_utc=report_end_time_utc,
        sample_rate_hz=report_facts.sample_rate_hz,
        tire_spec_text=report_facts.tire_spec_text,
        sample_count=report_facts.sample_count,
        sensor_count=primary.sensor_count,
        sensor_locations=list(report_facts.sensor_locations_active),
        sensor_model=report_facts.sensor_model,
        firmware_version=report_facts.firmware_version,
        car_name=report.car_name
        or (summary_metadata.car_name if summary_metadata is not None else None),
        car_type=report.car_type
        or (summary_metadata.car_type if summary_metadata is not None else None),
        observed=observed,
        system_cards=system_cards,
        next_steps=next_steps,
        data_trust=data_trust,
        pattern_evidence=pattern_evidence,
        peak_rows=peak_rows,
        lang=report.lang,
        certainty_tier_key=primary.tier,
        findings=findings,
        top_causes=top_causes,
        sensor_intensity_by_location=sensor_intensity,
        location_hotspot_rows=hotspot_rows,
        verdict_page=verdict_page or VerdictPageData(),
        appendix_a=appendix_a or AppendixAData(),
        appendix_b=appendix_b or AppendixBData(),
        appendix_c=appendix_c or AppendixCData(),
        appendix_d=appendix_d or AppendixDData(),
    )
