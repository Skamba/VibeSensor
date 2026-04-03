"""Focused builder for canonical report-document field mapping."""

from __future__ import annotations

from vibesensor.shared.boundaries.reporting.document import ReportDocument

from .assembly import ReportDocumentAssembly


def build_report_document_data(assembly: ReportDocumentAssembly) -> ReportDocument:
    """Map resolved report sections into ``ReportDocument``.

    All section resolution (candidate selection, card building, etc.) is done
    before this function is called.  This builder only performs field
    assignment and simple fallback defaults so it stays easily testable.
    """
    prepared = assembly.prepared
    report = assembly.report
    sections = assembly.sections
    report_facts = prepared.report_facts
    summary_metadata = prepared.summary.metadata
    return ReportDocument(
        title=sections.title,
        run_datetime=sections.report_date_text,
        run_id=report.run_id,
        duration_text=report_facts.duration_text,
        start_time_utc=sections.report_start_time_utc,
        end_time_utc=sections.report_end_time_utc,
        sample_rate_hz=report_facts.sample_rate_hz,
        tire_spec_text=report_facts.tire_spec_text,
        sample_count=report_facts.sample_count,
        sensor_count=sections.primary.sensor_count,
        sensor_locations=list(report_facts.sensor_locations_active),
        sensor_model=report_facts.sensor_model,
        firmware_version=report_facts.firmware_version,
        car_name=report.car_name
        or (summary_metadata.car_name if summary_metadata is not None else None),
        car_type=report.car_type
        or (summary_metadata.car_type if summary_metadata is not None else None),
        observed=sections.observed,
        system_cards=list(sections.system_cards),
        next_steps=list(sections.next_steps),
        data_trust=list(sections.data_trust),
        pattern_evidence=sections.pattern_evidence,
        peak_rows=list(sections.peak_rows),
        lang=report.lang,
        certainty_tier_key=sections.primary.tier,
        findings=list(sections.findings),
        top_causes=list(sections.top_causes),
        sensor_intensity_by_location=list(sections.sensor_intensity),
        location_hotspot_rows=list(sections.hotspot_rows),
        verdict_page=sections.verdict_page,
        appendix_a=sections.appendix_a,
        appendix_b=sections.appendix_b,
        appendix_c=sections.appendix_c,
        appendix_d=sections.appendix_d,
    )
