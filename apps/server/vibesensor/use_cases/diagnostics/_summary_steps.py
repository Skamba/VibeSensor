"""Step-building helpers for diagnostics summary orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from statistics import median as _median

from vibesensor.domain import LocationIntensitySummary, RunSuitability
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.types.run_schema import RunMetadata

from ._analysis_models import (
    FindingsBuilder,
    FindingsBundle,
    FindingsBundleRequest,
)
from ._types import AccelStatistics, Sample
from .findings import _build_findings
from .phase_segmentation import DrivingPhase
from .run_analysis_projection import build_phase_timeline, build_sensor_analysis
from .run_data_preparation import PreparedRunData
from .statistics import (
    _strength_band_key,
    compute_frame_integrity_counts,
    compute_reference_completeness,
)
from .top_cause_selection import select_top_causes


def build_findings_bundle(
    request: FindingsBundleRequest,
    *,
    findings_builder: FindingsBuilder | None = None,
) -> FindingsBundle:
    """Build findings plus derived diagnosis narrative fields."""
    builder = findings_builder or _build_findings
    prepared = request.prepared
    domain_findings = builder(request.findings_request)
    domain_findings = tuple(
        finding
        if finding.confidence_assessment is not None
        else finding.with_confidence_assessment(
            strength_band_key=request.overall_strength_band_key or "",
            steady_speed=prepared.is_steady_speed,
            has_reference_gaps=request.has_reference_gaps,
            sensor_count=request.sensor_count,
        )
        for finding in domain_findings
    )
    diagnostic_findings = tuple(finding for finding in domain_findings if not finding.is_reference)
    phase_timeline = build_phase_timeline(
        prepared.phase_segments,
        domain_findings,
        min_confidence=0.25,
    )
    return FindingsBundle(
        most_likely_origin=VibrationOrigin.from_ranked_findings(diagnostic_findings),
        phase_timeline=tuple(phase_timeline),
        domain_findings=domain_findings,
        domain_top_causes=select_top_causes(domain_findings),
    )


def build_sensor_bundle(
    samples: Sequence[Sample],
    *,
    language: str,
    per_sample_phases: Sequence[DrivingPhase],
) -> tuple[list[str], set[str], list[LocationIntensitySummary]]:
    """Build location-scoped sensor summaries used by analysis and reports."""
    return build_sensor_analysis(
        samples=samples,
        language=language,
        per_sample_phases=list(per_sample_phases),
    )


def build_run_suitability_bundle(
    context: RunMetadata,
    samples: Sequence[Sample],
    *,
    prepared: PreparedRunData,
    accel_stats: AccelStatistics,
) -> tuple[bool, RunSuitability | None, str | None]:
    """Build run-suitability checks and related confidence context."""
    reference_complete = compute_reference_completeness(context)
    sensor_ids = {client_id for sample in samples if (client_id := sample.client_id)}
    total_dropped, total_overflow = compute_frame_integrity_counts(samples)
    run_suitability = RunSuitability.evaluate(
        steady_speed=prepared.is_steady_speed,
        speed_sufficient=prepared.speed_sufficient,
        sensor_count=len(sensor_ids),
        reference_complete=reference_complete,
        sat_count=accel_stats["sat_count"],
        total_dropped=total_dropped,
        total_overflow=total_overflow,
    )
    amp_metric_values = accel_stats["amp_metric_values"]
    overall_strength_band_key = (
        _strength_band_key(_median(amp_metric_values)) if amp_metric_values else None
    )
    return reference_complete, run_suitability, overall_strength_band_key
