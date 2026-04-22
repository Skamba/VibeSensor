"""Adapter-local render plans for the current PDF surface."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain import LocationHotspotRow, LocationIntensitySummary
from vibesensor.shared.boundaries.reporting import FindingPresentation
from vibesensor.shared.boundaries.reporting.document import (
    AppendixAData,
    AppendixBData,
    AppendixCData,
    NextStep,
    ReportDocument,
    ReportLabelValueRow,
    VerdictPageData,
)
from vibesensor.shared.types.analysis_views import PeakTableRow

__all__ = [
    "AppendixAPageRenderPlan",
    "AppendixBRenderPlan",
    "AppendixCRenderPlan",
    "Page1RenderPlan",
    "PeakTableRow",
    "ReportPdfRenderPlan",
    "build_appendix_b_render_plan",
    "build_appendix_c_render_plan",
    "build_page1_render_plan",
]


@dataclass(frozen=True, slots=True)
class Page1RenderPlan:
    """Focused page-1 render data with no appendix/document baggage."""

    title: str
    lang: str
    run_datetime: str | None
    duration_text: str | None
    car_name: str | None
    car_type: str | None
    sensor_count: int
    sensor_locations: tuple[str, ...]
    sensor_intensity_by_location: tuple[LocationIntensitySummary, ...]
    location_hotspot_rows: tuple[LocationHotspotRow, ...]
    proof_sensor_intensity_by_location: tuple[LocationIntensitySummary, ...]
    proof_location_hotspot_rows: tuple[LocationHotspotRow, ...]
    verdict_page: VerdictPageData
    next_steps: tuple[NextStep, ...]
    findings: tuple[FindingPresentation, ...]
    top_causes: tuple[FindingPresentation, ...]


@dataclass(frozen=True, slots=True)
class AppendixAPageRenderPlan:
    """One renderable Appendix-A page plan."""

    lang: str
    appendix: AppendixAData
    trace_rows: tuple[ReportLabelValueRow, ...]
    steps: tuple[NextStep, ...]
    start_number: int
    continued: bool


@dataclass(frozen=True, slots=True)
class AppendixBRenderPlan:
    """Spatial proof appendix render data."""

    lang: str
    appendix: AppendixBData
    findings: tuple[FindingPresentation, ...]
    top_causes: tuple[FindingPresentation, ...]
    sensor_locations: tuple[str, ...]
    sensor_intensity_by_location: tuple[LocationIntensitySummary, ...]
    location_hotspot_rows: tuple[LocationHotspotRow, ...]
    proof_sensor_intensity_by_location: tuple[LocationIntensitySummary, ...]
    proof_location_hotspot_rows: tuple[LocationHotspotRow, ...]


@dataclass(frozen=True, slots=True)
class AppendixCRenderPlan:
    """Evidence appendix render data."""

    lang: str
    appendix: AppendixCData
    trace_rows: tuple[ReportLabelValueRow, ...]
    action_status_note: str | None


@dataclass(frozen=True, slots=True)
class ReportPdfRenderPlan:
    """Top-level PDF render plan assembled once from the document boundary."""

    document_title: str
    page1: Page1RenderPlan
    appendix_a_pages: tuple[AppendixAPageRenderPlan, ...]
    appendix_b: AppendixBRenderPlan | None
    appendix_c: AppendixCRenderPlan
    recapture_mode: bool
    total_pages: int


def build_page1_render_plan(data: ReportDocument) -> Page1RenderPlan:
    """Project the document boundary into the page-1-only render model."""

    proof_sensor_intensity = (
        tuple(data.proof_sensor_intensity_by_location)
        if data.proof_sensor_intensity_by_location
        else tuple(data.sensor_intensity_by_location)
    )
    proof_location_hotspot_rows = (
        tuple(data.proof_location_hotspot_rows)
        if data.proof_location_hotspot_rows
        else tuple(data.location_hotspot_rows)
    )
    return Page1RenderPlan(
        title=data.title,
        lang=data.lang,
        run_datetime=data.run_datetime,
        duration_text=data.duration_text,
        car_name=data.car_name,
        car_type=data.car_type,
        sensor_count=data.sensor_count,
        sensor_locations=tuple(data.sensor_locations),
        sensor_intensity_by_location=tuple(data.sensor_intensity_by_location),
        location_hotspot_rows=tuple(data.location_hotspot_rows),
        proof_sensor_intensity_by_location=proof_sensor_intensity,
        proof_location_hotspot_rows=proof_location_hotspot_rows,
        verdict_page=data.verdict_page,
        next_steps=tuple(data.next_steps),
        findings=tuple(data.findings),
        top_causes=tuple(data.top_causes),
    )


def build_appendix_b_render_plan(data: ReportDocument) -> AppendixBRenderPlan:
    """Project the document boundary into the spatial-proof appendix model."""

    proof_sensor_intensity = (
        tuple(data.proof_sensor_intensity_by_location)
        if data.proof_sensor_intensity_by_location
        else tuple(data.sensor_intensity_by_location)
    )
    proof_location_hotspot_rows = (
        tuple(data.proof_location_hotspot_rows)
        if data.proof_location_hotspot_rows
        else tuple(data.location_hotspot_rows)
    )
    return AppendixBRenderPlan(
        lang=data.lang,
        appendix=data.appendix_b,
        findings=tuple(data.findings),
        top_causes=tuple(data.top_causes),
        sensor_locations=tuple(data.sensor_locations),
        sensor_intensity_by_location=tuple(data.sensor_intensity_by_location),
        location_hotspot_rows=tuple(data.location_hotspot_rows),
        proof_sensor_intensity_by_location=proof_sensor_intensity,
        proof_location_hotspot_rows=proof_location_hotspot_rows,
    )


def build_appendix_c_render_plan(data: ReportDocument) -> AppendixCRenderPlan:
    """Project the document boundary into the evidence appendix model."""

    return AppendixCRenderPlan(
        lang=data.lang,
        appendix=data.appendix_c,
        trace_rows=tuple(data.traceability_rows),
        action_status_note=data.verdict_page.action_status_note,
    )
