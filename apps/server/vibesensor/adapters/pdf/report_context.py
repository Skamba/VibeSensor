"""PDF-side factory and bridge helpers for report mapping context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.adapters.pdf.report_data import PatternEvidence
from vibesensor.shared.boundaries.report_prepared_input import PreparedReportInput
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.time_utils import (
    format_timestamp_in_recorded_timezone,
    format_utc_timestamp,
    utc_now_iso,
)

if TYPE_CHECKING:
    from vibesensor.adapters.pdf._candidate_resolver import PrimaryCandidateContext
    from vibesensor.domain import Finding, LocationIntensitySummary, TestRun, VibrationOrigin

__all__ = [
    "ReportMappingContext",
    "observed_signature",
    "prepare_report_mapping_context",
]


@dataclass(frozen=True)
class ReportMappingContext:
    """Normalized structural context assembled on the PDF side for report mapping."""

    car_name: str | None
    car_type: str | None
    date_str: str
    origin: VibrationOrigin | None
    origin_location: str
    sensor_locations_active: list[str]
    duration_text: str | None
    start_time_utc: str | None
    end_time_utc: str | None
    sample_rate_hz: str | None
    tire_spec_text: str | None
    sample_count: int
    sensor_model: str | None
    firmware_version: str | None
    domain_aggregate: TestRun

    def top_report_candidate(self) -> Finding | None:
        """Return the primary report candidate (first effective top cause or finding)."""
        effective = self.domain_aggregate.effective_top_causes()
        if effective:
            return effective[0]
        non_ref = self.domain_aggregate.non_reference_findings
        if non_ref:
            return non_ref[0]
        all_findings = self.domain_aggregate.findings
        return all_findings[0] if all_findings else None

    def has_significant_location_intensity(
        self,
        sensor_intensity: list[LocationIntensitySummary],
    ) -> bool:
        """Whether any sensor location shows significant above-noise intensity."""
        for row in sensor_intensity:
            p95 = _as_float(row.p95_intensity_db)
            if p95 is not None and p95 > 0:
                return True
        return False


def observed_signature(primary: PrimaryCandidateContext) -> PatternEvidence:
    """Build the observed-signature block for the report template."""
    return PatternEvidence(
        primary_system=primary.primary_system,
        strongest_location=primary.primary_location,
        speed_band=primary.primary_speed,
        strength_label=primary.strength_text,
        strength_peak_db=primary.strength_db,
        certainty_label=primary.certainty_label_text,
        certainty_pct=primary.certainty_pct,
        certainty_reason=primary.certainty_reason,
    )


def prepare_report_mapping_context(
    prepared: PreparedReportInput,
) -> ReportMappingContext:
    """Build the adapter-owned report mapping context from the canonical handoff."""
    report_facts = prepared.report_facts
    report_date = prepared.renderer_payload.report_date or utc_now_iso()
    date_str = format_timestamp_in_recorded_timezone(
        report_date,
        prepared.renderer_payload.recorded_utc_offset_seconds,
    ) or str(report_date)
    return ReportMappingContext(
        car_name=prepared.renderer_payload.car_name,
        car_type=prepared.renderer_payload.car_type,
        date_str=date_str,
        origin=report_facts.origin,
        origin_location=report_facts.origin_location,
        sensor_locations_active=list(report_facts.sensor_locations_active),
        duration_text=report_facts.duration_text,
        start_time_utc=format_utc_timestamp(report_facts.start_time_utc),
        end_time_utc=format_utc_timestamp(report_facts.end_time_utc),
        sample_rate_hz=report_facts.sample_rate_hz,
        tire_spec_text=report_facts.tire_spec_text,
        sample_count=report_facts.sample_count,
        sensor_model=report_facts.sensor_model,
        firmware_version=report_facts.firmware_version,
        domain_aggregate=prepared.domain_test_run,
    )
