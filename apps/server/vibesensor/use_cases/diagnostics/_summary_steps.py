"""Step-building helpers for diagnostics summary orchestration."""

from __future__ import annotations

from collections.abc import Callable
from statistics import median as _median

from vibesensor.domain import DrivingPhaseInterval, LocationIntensitySummary, RunSuitability
from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.types.json_types import JsonObject

from ._types import AccelStatistics, Sample
from .findings import _build_findings
from .phase_segmentation import DrivingPhase
from .run_data_preparation import (
    PreparedRunData,
    build_phase_timeline,
    build_sensor_analysis,
)
from .statistics import (
    _strength_band_key,
    compute_frame_integrity_counts,
    compute_reference_completeness,
)
from .top_cause_selection import select_top_causes


def build_findings_bundle(
    metadata: JsonObject,
    samples: list[Sample],
    *,
    language: str,
    prepared: PreparedRunData,
    overall_strength_band_key: str | None,
    has_reference_gaps: bool,
    sensor_count: int,
    findings_builder: Callable[..., tuple[DomainFinding, ...]] | None = None,
) -> tuple[
    VibrationOrigin | None,
    list[DrivingPhaseInterval],
    tuple[DomainFinding, ...],
    tuple[DomainFinding, ...],
]:
    """Build findings plus derived diagnosis narrative fields."""
    builder = findings_builder or _build_findings
    domain_findings = builder(
        metadata=metadata,
        samples=samples,
        speed_sufficient=prepared.speed_sufficient,
        steady_speed=prepared.is_steady_speed,
        speed_stddev_kmh=prepared.speed_stddev_kmh,
        speed_non_null_pct=prepared.speed_non_null_pct,
        raw_sample_rate_hz=prepared.raw_sample_rate_hz,
        lang=language,
        per_sample_phases=prepared.per_sample_phases,
        run_noise_baseline_g=prepared.run_noise_baseline_g,
    )
    domain_findings = tuple(
        finding
        if finding.confidence_assessment is not None
        else finding.with_confidence_assessment(
            strength_band_key=overall_strength_band_key or "",
            steady_speed=prepared.is_steady_speed,
            has_reference_gaps=has_reference_gaps,
            sensor_count=sensor_count,
        )
        for finding in domain_findings
    )
    diagnostic_findings = tuple(finding for finding in domain_findings if not finding.is_reference)
    phase_timeline = build_phase_timeline(
        prepared.phase_segments,
        domain_findings,
        min_confidence=0.25,
    )
    return (
        VibrationOrigin.from_ranked_findings(diagnostic_findings),
        phase_timeline,
        domain_findings,
        select_top_causes(domain_findings),
    )


def build_sensor_bundle(
    samples: list[Sample],
    *,
    language: str,
    per_sample_phases: list[DrivingPhase],
) -> tuple[list[str], set[str], list[LocationIntensitySummary]]:
    """Build location-scoped sensor summaries used by analysis and reports."""
    return build_sensor_analysis(
        samples=samples,
        language=language,
        per_sample_phases=per_sample_phases,
    )


def build_run_suitability_bundle(
    metadata: JsonObject,
    samples: list[Sample],
    *,
    prepared: PreparedRunData,
    accel_stats: AccelStatistics,
) -> tuple[bool, RunSuitability | None, str | None]:
    """Build run-suitability checks and related confidence context."""
    reference_complete = compute_reference_completeness(metadata)
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
