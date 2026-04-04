"""Canonical context-to-document mapping for report rendering."""

from __future__ import annotations

from vibesensor.shared.boundaries.reporting import PreparedReportInput
from vibesensor.shared.boundaries.reporting.document import (
    ReportDocument,
    ReportDocumentContext,
)

from .composition import compose_report_document_context

__all__ = ["build_report_document", "build_report_document_data"]


def build_report_document_data(context: ReportDocumentContext) -> ReportDocument:
    """Map one canonical build context into the adapter-facing report document."""

    return ReportDocument(
        title=context.title,
        run_datetime=context.run_datetime,
        run_id=context.run_id,
        duration_text=context.duration_text,
        start_time_utc=context.start_time_utc,
        end_time_utc=context.end_time_utc,
        sample_rate_hz=context.sample_rate_hz,
        tire_spec_text=context.tire_spec_text,
        sample_count=context.sample_count,
        sensor_count=context.sensor_count,
        sensor_locations=list(context.sensor_locations),
        sensor_model=context.sensor_model,
        firmware_version=context.firmware_version,
        car_name=context.car_name,
        car_type=context.car_type,
        observed=context.observed,
        system_cards=list(context.system_cards),
        next_steps=list(context.next_steps),
        data_trust=list(context.data_trust),
        pattern_evidence=context.pattern_evidence,
        peak_rows=list(context.peak_rows),
        lang=context.language,
        certainty_tier_key=context.certainty_tier_key,
        findings=list(context.findings),
        top_causes=list(context.top_causes),
        sensor_intensity_by_location=list(context.sensor_intensity_by_location),
        location_hotspot_rows=list(context.location_hotspot_rows),
        verdict_page=context.verdict_page,
        appendix_a=context.appendix_a,
        appendix_b=context.appendix_b,
        appendix_c=context.appendix_c,
        appendix_d=context.appendix_d,
    )


def build_report_document(prepared: PreparedReportInput) -> ReportDocument:
    """Build the canonical report document from prepared report input."""

    return build_report_document_data(compose_report_document_context(prepared))
