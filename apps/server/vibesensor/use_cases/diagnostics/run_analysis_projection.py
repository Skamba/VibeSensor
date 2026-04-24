"""Projection helpers derived from prepared diagnostics run data."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING

from vibesensor.domain import DrivingPhaseInterval, LocationIntensitySummary
from vibesensor.domain import DrivingSegment as DomainDrivingSegment
from vibesensor.domain import Finding as DomainFinding
from vibesensor.use_cases.diagnostics._sensor_locations import (
    _location_label,
    _locations_connected_throughout_run,
)
from vibesensor.use_cases.diagnostics._types import Sample
from vibesensor.use_cases.diagnostics.phase_segmentation import DrivingPhase, PhaseSegment
from vibesensor.use_cases.diagnostics.signal_aggregation import _sensor_intensity_by_location

if TYPE_CHECKING:
    from vibesensor.shared.types.run_schema import RunMetadata


def build_phase_timeline(
    phase_segments: Sequence[PhaseSegment],
    findings: Sequence[DomainFinding],
    *,
    min_confidence: float,
) -> list[DrivingPhaseInterval]:
    """Build a simple phase timeline annotated with finding evidence."""
    if not phase_segments:
        return []

    evidence_phases = {
        str(phase).strip().lower()
        for finding in findings
        if finding.is_diagnostic and finding.effective_confidence >= min_confidence
        for phase in finding.phases_detected
        if str(phase).strip()
    }
    return [
        DrivingPhaseInterval(
            phase=segment.phase,
            start_t_s=None if math.isnan(segment.start_t_s) else segment.start_t_s,
            end_t_s=None if math.isnan(segment.end_t_s) else segment.end_t_s,
            speed_min_kmh=segment.speed_min_kmh,
            speed_max_kmh=segment.speed_max_kmh,
            has_fault_evidence=str(segment.phase).strip().lower() in evidence_phases,
        )
        for segment in phase_segments
    ]


def build_domain_driving_segments(
    phase_segments: Sequence[PhaseSegment],
) -> tuple[DomainDrivingSegment, ...]:
    """Project diagnostics phase segments into the domain driving-segment shape."""
    return tuple(
        DomainDrivingSegment(
            phase=segment.phase,
            start_idx=segment.start_idx,
            end_idx=segment.end_idx,
            start_t_s=(
                None
                if isinstance(segment.start_t_s, float) and math.isnan(segment.start_t_s)
                else segment.start_t_s
            ),
            end_t_s=(
                None
                if isinstance(segment.end_t_s, float) and math.isnan(segment.end_t_s)
                else segment.end_t_s
            ),
            speed_min_kmh=segment.speed_min_kmh,
            speed_max_kmh=segment.speed_max_kmh,
            sample_count=segment.sample_count,
        )
        for segment in phase_segments
    )


def build_sensor_analysis(
    *,
    samples: Sequence[Sample],
    language: str,
    per_sample_phases: Sequence[DrivingPhase],
    metadata: RunMetadata | None = None,
) -> tuple[list[str], set[str], list[LocationIntensitySummary]]:
    """Build sensor location lists and intensity rows from analysed samples."""
    sensor_locations = sorted(
        {
            label
            for sample in samples
            if (label := _location_label(sample, metadata=metadata, lang=language))
        },
    )
    connected_locations = _locations_connected_throughout_run(
        samples,
        metadata=metadata,
        lang=language,
    )
    sensor_intensity_by_location = _sensor_intensity_by_location(
        samples,
        include_locations=set(sensor_locations),
        metadata=metadata,
        lang=language,
        connected_locations=connected_locations,
        per_sample_phases=per_sample_phases,
    )
    return sensor_locations, connected_locations, sensor_intensity_by_location
