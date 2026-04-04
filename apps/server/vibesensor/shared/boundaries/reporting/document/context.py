"""Immutable build-time context for report-document assembly."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain import LocationHotspotRow, LocationIntensitySummary

from ..findings import FindingPresentation
from .appendices import AppendixAData, AppendixBData, AppendixCData, AppendixDData
from .panels import DataTrustItem, NextStep, PatternEvidence, SystemFindingCard
from .sections import PeakRow, VerdictPageData

__all__ = ["ReportDocumentContext"]


@dataclass(frozen=True, slots=True)
class ReportDocumentContext:
    """Canonical pre-render report-document state built from prepared report input."""

    title: str
    run_datetime: str
    run_id: str
    duration_text: str | None
    start_time_utc: str | None
    end_time_utc: str | None
    sample_rate_hz: str | None
    tire_spec_text: str | None
    sample_count: int
    sensor_count: int
    sensor_locations: tuple[str, ...]
    sensor_model: str | None
    firmware_version: str | None
    car_name: str | None
    car_type: str | None
    observed: PatternEvidence
    system_cards: tuple[SystemFindingCard, ...]
    next_steps: tuple[NextStep, ...]
    data_trust: tuple[DataTrustItem, ...]
    pattern_evidence: PatternEvidence
    peak_rows: tuple[PeakRow, ...]
    language: str
    certainty_tier_key: str
    findings: tuple[FindingPresentation, ...]
    top_causes: tuple[FindingPresentation, ...]
    sensor_intensity_by_location: tuple[LocationIntensitySummary, ...]
    location_hotspot_rows: tuple[LocationHotspotRow, ...]
    verdict_page: VerdictPageData
    appendix_a: AppendixAData
    appendix_b: AppendixBData
    appendix_c: AppendixCData
    appendix_d: AppendixDData
