"""Semantic prepared reporting facts shared across presentation and rendering."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vibesensor.domain import (
        TestRun,
        VibrationOrigin,
    )
    from vibesensor.shared.boundaries.reporting.decision_facts import ReportDecisionFacts
    from vibesensor.shared.boundaries.reporting.evidence_facts import ReportEvidenceFacts
    from vibesensor.shared.boundaries.reporting.findings import PreparedReportFindings
    from vibesensor.shared.boundaries.reporting.sensor_facts import ReportSensorFacts
    from vibesensor.shared.boundaries.reporting.summary import (
        NormalizedReportSummary,
        ReportTimelineInterval,
    )
    from vibesensor.shared.run_context_warning import RunContextWarningsInput
    from vibesensor.shared.types.analysis_views import PeakTableRow

from vibesensor.shared.boundaries.reporting.decision_facts import (
    ActionStatusKey,
    LocationConfidenceKey,
    build_report_decision_facts,
)
from vibesensor.shared.boundaries.reporting.evidence_facts import build_report_evidence_facts
from vibesensor.shared.boundaries.reporting.findings import (
    PreparedReportFindings,
    prepare_report_findings,
)
from vibesensor.shared.boundaries.reporting.projection import (
    normalize_origin_location,
    resolve_report_origin,
)
from vibesensor.shared.boundaries.reporting.sensor_facts import (
    build_report_sensor_facts,
    enrich_location_proof_sensor_facts,
)

__all__ = [
    "ActionStatusKey",
    "LocationConfidenceKey",
    "PreparedReportFacts",
    "ReportRunFacts",
    "prepare_report_facts",
]


@dataclass(frozen=True, slots=True)
class ReportRunFacts:
    """Run-scoped report facts independent from sensor and decision shaping."""

    run_id: str
    origin: VibrationOrigin | None
    origin_location: str
    report_date: str | None
    recorded_utc_offset_seconds: int | None
    duration_s: float | None
    duration_text: str | None
    start_time_utc: str | None
    end_time_utc: str | None
    sample_rate_hz: str | None
    tire_spec_text: str | None
    sample_count: int
    sensor_count: int
    sensor_model: str | None
    firmware_version: str | None
    car_name: str | None
    car_type: str | None
    timeline_intervals: tuple[ReportTimelineInterval, ...]
    peak_table_rows: tuple[PeakTableRow, ...]


@dataclass(frozen=True, slots=True)
class PreparedReportFacts:
    """Canonical grouped report facts for run, sensor, and decision concerns."""

    run: ReportRunFacts
    sensor: ReportSensorFacts
    decision: ReportDecisionFacts
    evidence: ReportEvidenceFacts
    findings: PreparedReportFindings


def prepare_report_facts(
    payload: Mapping[str, object],
    *,
    summary: NormalizedReportSummary,
    test_run: TestRun,
    language: str | None = None,
    warnings: RunContextWarningsInput = None,
) -> PreparedReportFacts:
    """Resolve semantic report facts shared by downstream PDF mapping."""
    origin = resolve_report_origin(test_run)
    origin_location = normalize_origin_location(origin)
    config_snap = test_run.capture.setup.configuration_snapshot
    sensor_facts = build_report_sensor_facts(
        test_run=test_run,
        sensor_locations_active=summary.active_sensor_locations,
        sensor_intensity=summary.sensor_intensity_rows,
    )
    decision_facts = build_report_decision_facts(
        payload,
        test_run=test_run,
        origin_location=origin_location,
        sensor_facts=sensor_facts,
        warnings=warnings,
    )
    evidence_facts = build_report_evidence_facts(
        payload,
        summary=summary,
        primary_candidate=decision_facts.primary_candidate,
        decision_facts=decision_facts,
    )
    sensor_facts = enrich_location_proof_sensor_facts(
        sensor_facts,
        primary_candidate=decision_facts.primary_candidate,
        evidence_data_basis=evidence_facts.data_basis,
    )
    return PreparedReportFacts(
        run=ReportRunFacts(
            run_id=summary.run_id,
            origin=origin,
            origin_location=origin_location,
            report_date=summary.report_date,
            recorded_utc_offset_seconds=(
                summary.metadata.recorded_utc_offset_seconds
                if summary.metadata is not None
                else None
            ),
            duration_s=summary.duration_s,
            duration_text=summary.record_length,
            start_time_utc=summary.start_time_utc,
            end_time_utc=summary.end_time_utc,
            sample_rate_hz=(
                f"{config_snap.raw_sample_rate_hz:g}"
                if config_snap.raw_sample_rate_hz is not None
                else None
            ),
            tire_spec_text=_tire_spec_text(config_snap.tire_spec),
            sample_count=test_run.capture.sample_count,
            sensor_count=summary.sensor_count,
            sensor_model=config_snap.sensor_model,
            firmware_version=config_snap.firmware_version,
            car_name=summary.metadata.car_name if summary.metadata is not None else None,
            car_type=summary.metadata.car_type if summary.metadata is not None else None,
            timeline_intervals=summary.timeline_intervals,
            peak_table_rows=summary.peak_table_rows,
        ),
        sensor=sensor_facts,
        decision=decision_facts,
        evidence=evidence_facts,
        findings=prepare_report_findings(test_run),
    )


def _tire_spec_text(tire_spec: object) -> str | None:
    from vibesensor.domain import TireSpec

    if not isinstance(tire_spec, TireSpec):
        return None
    if tire_spec.width_mm <= 0 or tire_spec.aspect_pct <= 0 or tire_spec.rim_in <= 0:
        return None
    return f"{tire_spec.width_mm:g}/{tire_spec.aspect_pct:g}R{tire_spec.rim_in:g}"
