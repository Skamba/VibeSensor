"""Focused builder for ReportTemplateData field mapping.

Owns the mapping from resolved report sections and context into a
``ReportTemplateData`` instance.  Keeps the mapping explicit and testable
while the orchestration layer (``mapping.py``) handles section resolution.
"""

from __future__ import annotations

from vibesensor.adapters.pdf._candidate_resolver import PrimaryCandidateContext
from vibesensor.adapters.pdf.report_context import ReportMappingContext
from vibesensor.adapters.pdf.report_data import (
    DataTrustItem,
    FindingPresentation,
    NextStep,
    PatternEvidence,
    PeakRow,
    Report,
    ReportTemplateData,
    SystemFindingCard,
)
from vibesensor.domain import LocationHotspotRow, LocationIntensitySummary


def build_template_data(
    *,
    context: ReportMappingContext,
    report: Report,
    primary: PrimaryCandidateContext,
    title: str,
    observed: PatternEvidence,
    system_cards: list[SystemFindingCard],
    next_steps: list[NextStep],
    data_trust: list[DataTrustItem],
    pattern_evidence: PatternEvidence,
    peak_rows: list[PeakRow],
    version_marker: str,
    findings: list[FindingPresentation],
    top_causes: list[FindingPresentation],
    sensor_intensity: list[LocationIntensitySummary],
    hotspot_rows: list[LocationHotspotRow],
) -> ReportTemplateData:
    """Map resolved report sections into ``ReportTemplateData``.

    All section resolution (candidate selection, card building, etc.) is done
    before this function is called.  This builder only performs field
    assignment and simple fallback defaults so it stays easily testable.
    """
    return ReportTemplateData(
        title=title,
        run_datetime=context.date_str,
        run_id=report.run_id,
        duration_text=context.duration_text,
        start_time_utc=context.start_time_utc,
        end_time_utc=context.end_time_utc,
        sample_rate_hz=context.sample_rate_hz,
        tire_spec_text=context.tire_spec_text,
        sample_count=context.sample_count,
        sensor_count=primary.sensor_count,
        sensor_locations=context.sensor_locations_active,
        sensor_model=context.sensor_model,
        firmware_version=context.firmware_version,
        car_name=report.car_name or context.car_name,
        car_type=report.car_type or context.car_type,
        observed=observed,
        system_cards=system_cards,
        next_steps=next_steps,
        data_trust=data_trust,
        pattern_evidence=pattern_evidence,
        peak_rows=peak_rows,
        version_marker=version_marker,
        lang=report.lang,
        certainty_tier_key=primary.tier,
        findings=findings,
        top_causes=top_causes,
        sensor_intensity_by_location=sensor_intensity,
        location_hotspot_rows=hotspot_rows,
    )
