"""Typed models for canonical diagnostics analysis orchestration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from vibesensor.analysis._types import AccelStatistics, PhaseLabels, Sample
from vibesensor.analysis.run_data_preparation import PreparedRunData
from vibesensor.domain.driving_segment import DrivingPhaseInterval
from vibesensor.domain.finding import Finding as DomainFinding
from vibesensor.domain.location_hotspot import LocationIntensitySummary
from vibesensor.domain.run_suitability import RunSuitability
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.recording.run_schema import RunMetadata


@dataclass(frozen=True, slots=True)
class FindingsBuildRequest:
    """Normalized inputs required to build diagnostics findings."""

    context: RunMetadata
    samples: Sequence[Sample]
    speed_sufficient: bool
    steady_speed: bool
    speed_steadiness: float
    speed_constancy: float
    speed_non_null_pct: float
    raw_sample_rate_hz: float | None
    lang: str
    per_sample_phases: PhaseLabels | None
    run_noise_baseline_g: float | None


@dataclass(frozen=True, slots=True)
class FindingsBundle:
    """Derived findings outputs carried together through summary assembly."""

    most_likely_origin: VibrationOrigin | None
    phase_timeline: tuple[DrivingPhaseInterval, ...]
    domain_findings: tuple[DomainFinding, ...]
    domain_top_causes: tuple[DomainFinding, ...]


@dataclass(frozen=True, slots=True)
class PreparedAnalysisContext:
    """Canonical typed context shared across diagnostics result assembly."""

    file_name: str
    context: RunMetadata
    samples: tuple[Sample, ...]
    language: str
    include_samples: bool
    prepared: PreparedRunData
    accel_stats: AccelStatistics
    reference_complete: bool
    run_suitability: RunSuitability | None
    sensor_locations: tuple[str, ...]
    connected_locations: frozenset[str]
    sensor_intensity_by_location: tuple[LocationIntensitySummary, ...]

    def findings_request(self) -> FindingsBuildRequest:
        """Project the canonical analysis context into findings-specific inputs."""

        return FindingsBuildRequest(
            context=self.context,
            samples=self.samples,
            speed_sufficient=self.prepared.speed_sufficient,
            steady_speed=self.prepared.is_steady_speed,
            speed_steadiness=self.prepared.speed_steadiness,
            speed_constancy=self.prepared.speed_constancy,
            speed_non_null_pct=self.prepared.speed_non_null_pct,
            raw_sample_rate_hz=self.prepared.raw_sample_rate_hz,
            lang=self.language,
            per_sample_phases=self.prepared.per_sample_phases,
            run_noise_baseline_g=self.prepared.run_noise_baseline_g,
        )
