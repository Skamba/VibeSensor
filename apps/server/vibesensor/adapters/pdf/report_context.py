"""Report context assembly for the PDF mapper.

Owns :class:`ReportMappingContext` plus
:func:`prepare_report_mapping_context`, which bridge prepared report facts
into normalized context consumed by ``mapping.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.adapters.pdf.report_data import PatternEvidence
from vibesensor.domain import (
    Finding,
    LocationIntensitySummary,
    TestRun,
    VibrationOrigin,
)
from vibesensor.shared.boundaries.analysis_payload import AnalysisSummary
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.time_utils import utc_now_iso

if TYPE_CHECKING:
    from vibesensor.adapters.pdf._candidate_resolver import PrimaryCandidateContext
    from vibesensor.use_cases.history.report_preparation import PreparedReportFacts

__all__ = [
    "ReportMappingContext",
    "prepare_report_mapping_context",
]


@dataclass(frozen=True)
class ReportMappingContext:
    """Normalized structural context pulled from an analysis summary.

    Owns display-ready metadata access, primary hotspot / candidate
    selection helpers, and report-mapping decisions that were previously
    spread across helper functions and ``dict.get(...)`` calls.

    Domain ``Finding`` objects are available alongside payload dicts so
    that business decisions (classification, ranking, actionability) use
    the domain model while rendering-level evidence detail comes from
    the payloads.
    """

    car_name: str | None
    car_type: str | None
    date_str: str
    origin: VibrationOrigin | None
    origin_location: str
    sensor_locations_active: list[str]
    # Typed run metadata (replaces dict[str, object] + type: ignore).
    duration_text: str | None
    start_time_utc: str | None
    end_time_utc: str | None
    sample_rate_hz: str | None
    tire_spec_text: str | None
    sample_count: int
    sensor_model: str | None
    firmware_version: str | None
    # Domain aggregate — the primary data source for business decisions.
    domain_aggregate: TestRun

    # -- candidate selection ------------------------------------------------

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

    # -- intensity queries --------------------------------------------------

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

    # -- observed signature -------------------------------------------------

    def observed_signature(self, primary: PrimaryCandidateContext) -> PatternEvidence:
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
    summary: AnalysisSummary,
    *,
    report_facts: PreparedReportFacts,
    test_run: TestRun,
) -> ReportMappingContext:
    """Extract structural summary context for report mapping.

    Consumes the prepared domain ``TestRun`` aggregate and history-prepared
    semantic report facts so downstream business decisions stay domain-first
    without calling back into history-layer interpretation helpers.
    """
    meta = summary["metadata"]
    car_name = str(meta.get("car_name") or "").strip() or None
    car_type = str(meta.get("car_type") or "").strip() or None
    report_date = str(summary["report_date"] or "") or utc_now_iso()
    date_str = str(report_date)[:19].replace("T", " ") + " UTC"

    return ReportMappingContext(
        car_name=car_name,
        car_type=car_type,
        date_str=date_str,
        origin=report_facts.origin,
        origin_location=report_facts.origin_location,
        sensor_locations_active=list(report_facts.sensor_locations_active),
        duration_text=report_facts.duration_text,
        start_time_utc=report_facts.start_time_utc,
        end_time_utc=report_facts.end_time_utc,
        sample_rate_hz=report_facts.sample_rate_hz,
        tire_spec_text=report_facts.tire_spec_text,
        sample_count=report_facts.sample_count,
        sensor_model=report_facts.sensor_model,
        firmware_version=report_facts.firmware_version,
        domain_aggregate=test_run,
    )
