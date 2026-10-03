"""Semantic prepared reporting facts shared across presentation and rendering."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vibesensor.summary.analysis_metadata import (
    ReportAnalysisMetadata,
    report_analysis_metadata_from_payload,
)

if TYPE_CHECKING:
    from vibesensor.domain.test_run import TestRun
    from vibesensor.domain.vibration_origin import VibrationOrigin
    from vibesensor.report.confidence_facts import ReportConfidenceFacts
    from vibesensor.report.decision_facts import ReportDecisionFacts
    from vibesensor.report.evidence_facts import ReportEvidenceFacts
    from vibesensor.report.sensor_facts import ReportSensorFacts
    from vibesensor.summary.analysis_views import PeakTableRow
    from vibesensor.summary.decoding import (
        NormalizedReportSummary,
        ReportTimelineInterval,
    )

from vibesensor.report.confidence_facts import build_report_confidence_facts
from vibesensor.report.decision_facts import (
    ActionStatusKey,
    LocationConfidenceKey,
    build_report_decision_facts,
)
from vibesensor.report.evidence_facts import build_report_evidence_facts
from vibesensor.report.projection import (
    normalize_origin_location,
    resolve_report_origin,
)
from vibesensor.report.sensor_facts import (
    build_report_sensor_facts,
    enrich_location_proof_sensor_facts,
)
from vibesensor.summary.fallback_reasons import (
    ReportFallbackReason,
    dedupe_report_fallback_reasons,
    derive_report_fallback_reasons,
    finalization_stage_fallback_reasons,
)
from vibesensor.summary.run_context_warning import RunContextWarningsInput

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
    strength_algorithm_version: str | None
    peak_detector_version: str | None
    calibration_profile_id: str | None
    vehicle_baseline_profile_id: str | None
    car_name: str | None
    car_type: str | None
    timeline_intervals: tuple[ReportTimelineInterval, ...]
    peak_table_rows: tuple[PeakTableRow, ...]


@dataclass(frozen=True, slots=True)
class PreparedReportFacts:
    """Canonical grouped report facts for run, sensor, and decision concerns."""

    run: ReportRunFacts
    fallback_reasons: tuple[ReportFallbackReason, ...]
    sensor: ReportSensorFacts
    decision: ReportDecisionFacts
    evidence: ReportEvidenceFacts
    confidence: ReportConfidenceFacts


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
    analysis_metadata = report_analysis_metadata_from_payload(payload)
    fallback_reasons = _report_fallback_reasons(
        analysis_metadata,
        summary=summary,
    )
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
        analysis_metadata,
        summary=summary,
        primary_candidate=decision_facts.primary_candidate,
        decision_facts=decision_facts,
    )
    sensor_facts = enrich_location_proof_sensor_facts(
        sensor_facts,
        primary_candidate=decision_facts.primary_candidate,
        evidence_data_basis=evidence_facts.data_basis,
    )
    confidence_facts = build_report_confidence_facts(
        has_explicit_analysis_metadata=analysis_metadata.present,
        primary_candidate=decision_facts.primary_candidate,
        evidence_facts=evidence_facts,
        decision_facts=decision_facts,
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
            strength_algorithm_version=config_snap.strength_algorithm_version,
            peak_detector_version=config_snap.peak_detector_version,
            calibration_profile_id=config_snap.calibration_profile_id,
            vehicle_baseline_profile_id=config_snap.vehicle_baseline_profile_id,
            car_name=summary.metadata.car_name if summary.metadata is not None else None,
            car_type=summary.metadata.car_type if summary.metadata is not None else None,
            timeline_intervals=summary.timeline_intervals,
            peak_table_rows=summary.peak_table_rows,
        ),
        fallback_reasons=fallback_reasons,
        sensor=sensor_facts,
        decision=decision_facts,
        evidence=evidence_facts,
        confidence=confidence_facts,
    )


def _tire_spec_text(tire_spec: object) -> str | None:
    from vibesensor.domain.tire_spec import TireSpec

    if not isinstance(tire_spec, TireSpec):
        return None
    if tire_spec.width_mm <= 0 or tire_spec.aspect_pct <= 0 or tire_spec.rim_in <= 0:
        return None
    return f"{tire_spec.width_mm:g}/{tire_spec.aspect_pct:g}R{tire_spec.rim_in:g}"


def _report_fallback_reasons(
    analysis_metadata: ReportAnalysisMetadata,
    *,
    summary: NormalizedReportSummary,
) -> tuple[ReportFallbackReason, ...]:
    reasons: list[str] = []
    metadata = summary.metadata
    if metadata is not None:
        reasons.extend(finalization_stage_fallback_reasons(metadata.finalization_stages))
    if analysis_metadata.present:
        reasons.extend(derive_report_fallback_reasons(analysis_metadata))
    else:
        reasons.append("legacy_summary_only")
    return dedupe_report_fallback_reasons(reasons)
