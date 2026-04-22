"""Rendering-facing report-document output assembly."""

from __future__ import annotations

from vibesensor.shared.boundaries.reporting.document import ReportDocument
from vibesensor.shared.time_utils import format_utc_timestamp

from .document_context import ReportDocumentContext
from .document_sections import ReportDocumentSections
from .verdict_page import build_observed_signature

__all__ = ["assemble_report_document"]


def assemble_report_document(
    *,
    context: ReportDocumentContext,
    sections: ReportDocumentSections,
) -> ReportDocument:
    """Assemble the final PDF-facing document from context and prebuilt sections."""

    return ReportDocument(
        title=context.tr("REPORT_FOOTER_TITLE"),
        run_datetime=context.run_datetime,
        run_id=context.run_facts.run_id,
        duration_text=context.run_facts.duration_text,
        start_time_utc=format_utc_timestamp(context.run_facts.start_time_utc),
        end_time_utc=format_utc_timestamp(context.run_facts.end_time_utc),
        sample_rate_hz=context.run_facts.sample_rate_hz,
        tire_spec_text=context.run_facts.tire_spec_text,
        sample_count=context.run_facts.sample_count,
        sensor_count=context.primary.sensor_count,
        sensor_locations=list(context.sensor_facts.active_locations),
        sensor_model=context.run_facts.sensor_model,
        firmware_version=context.run_facts.firmware_version,
        car_name=context.run_facts.car_name,
        car_type=context.run_facts.car_type,
        observed=build_observed_signature(context.primary, tr=context.tr),
        system_cards=list(sections.system_cards),
        next_steps=list(sections.next_steps),
        data_trust=list(sections.data_trust),
        pattern_evidence=sections.pattern_evidence,
        peak_rows=list(sections.peak_rows),
        lang=context.lang,
        certainty_tier_key=context.primary.tier,
        findings=list(context.findings),
        top_causes=list(context.top_causes),
        sensor_intensity_by_location=list(context.sensor_facts.active_intensity),
        location_hotspot_rows=list(context.sensor_facts.location_hotspot_rows),
        proof_sensor_intensity_by_location=list(context.sensor_facts.proof_intensity),
        proof_location_hotspot_rows=list(context.sensor_facts.proof_location_hotspot_rows),
        verdict_page=sections.verdict_page,
        appendix_a=sections.appendix_a,
        appendix_b=sections.appendix_b,
        appendix_c=sections.appendix_c,
        traceability_rows=list(sections.traceability_rows),
    )
