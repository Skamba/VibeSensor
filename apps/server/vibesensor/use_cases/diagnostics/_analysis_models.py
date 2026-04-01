"""Typed request and bundle models for diagnostics summary orchestration."""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass

from vibesensor.domain import DrivingPhaseInterval, LocationIntensitySummary, RunSuitability
from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain.vibration_origin import VibrationOrigin

from ._context import DiagnosticsContext
from ._types import AccelStatistics, PhaseLabels, Sample
from .run_data_preparation import PreparedRunData


@dataclass(frozen=True, slots=True)
class FindingsBuildRequest:
    """Normalized inputs required to build diagnostics findings."""

    context: DiagnosticsContext
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
class FindingsBundleRequest:
    """Inputs needed to build findings plus derived narrative artifacts."""

    findings_request: FindingsBuildRequest
    prepared: PreparedRunData
    overall_strength_band_key: str | None
    has_reference_gaps: bool
    sensor_count: int


@dataclass(frozen=True, slots=True)
class FindingsBundle:
    """Derived findings outputs carried together through summary assembly."""

    most_likely_origin: VibrationOrigin | None
    phase_timeline: tuple[DrivingPhaseInterval, ...]
    domain_findings: tuple[DomainFinding, ...]
    domain_top_causes: tuple[DomainFinding, ...]


@dataclass(frozen=True, slots=True)
class AnalysisResultBuildRequest:
    """Inputs required to assemble the final diagnostics analysis result."""

    file_name: str
    context: DiagnosticsContext
    samples: Sequence[Sample]
    language: str
    include_samples: bool
    prepared: PreparedRunData
    accel_stats: AccelStatistics
    sensor_locations: Sequence[str]
    connected_locations: Collection[str]
    sensor_intensity_by_location: Sequence[LocationIntensitySummary]
    reference_complete: bool
    run_suitability: RunSuitability | None
    findings_bundle: FindingsBundle
