"""Typed models for canonical diagnostics analysis orchestration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from vibesensor.domain import DrivingPhaseInterval, LocationIntensitySummary, RunSuitability
from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.types.run_schema import RunMetadata

from ._types import AccelStatistics, PhaseLabels, Sample
from .run_data_preparation import PreparedRunData


@dataclass(frozen=True, slots=True)
class FindingsBuildRequest:
    """Normalized inputs required to build diagnostics findings."""

    context: RunMetadata
    samples: Sequence[Sample]
    speed_sufficient: bool
    steady_speed: bool
    speed_stddev_kmh: float | None
    speed_non_null_pct: float
    raw_sample_rate_hz: float | None
    lang: str
    per_sample_phases: PhaseLabels | None
    run_noise_baseline_g: float | None


FindingsBuilder = Callable[[FindingsBuildRequest], tuple[DomainFinding, ...]]


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
    overall_strength_band_key: str | None
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
            speed_stddev_kmh=self.prepared.speed_stddev_kmh,
            speed_non_null_pct=self.prepared.speed_non_null_pct,
            raw_sample_rate_hz=self.prepared.raw_sample_rate_hz,
            lang=self.language,
            per_sample_phases=self.prepared.per_sample_phases,
            run_noise_baseline_g=self.prepared.run_noise_baseline_g,
        )
