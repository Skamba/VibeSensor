"""Explicit intermediate models for the run-summary diagnosis pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ._types import (
    AccelStatistics,
    Finding,
    I18nRef,
    IntensityRow,
    OriginSummary,
    PhaseSpeedBreakdownRow,
    PhaseSpeedStats,
    PhaseSummary,
    PhaseTimelineEntry,
    RunSuitabilityCheck,
    SpeedBreakdownRow,
    SpeedStats,
    TestStep,
    TopCause,
)
from .phase_segmentation import DrivingPhase, PhaseSegment


@dataclass(frozen=True)
class PreparedRunData:
    """Shared timing, speed, and phase context for summary generation."""

    run_id: str
    start_ts: datetime | None
    end_ts: datetime | None
    duration_s: float
    raw_sample_rate_hz: float | None
    speed_values: list[float]
    speed_stats: SpeedStats
    speed_non_null_pct: float
    speed_sufficient: bool
    per_sample_phases: list[DrivingPhase]
    phase_segments: list[PhaseSegment]
    run_noise_baseline_g: float | None
    phase_info: PhaseSummary
    speed_stats_by_phase: dict[str, PhaseSpeedStats]
    speed_breakdown: list[SpeedBreakdownRow]
    speed_breakdown_skipped_reason: I18nRef | None
    phase_speed_breakdown: list[PhaseSpeedBreakdownRow]


@dataclass(frozen=True)
class FindingsBundle:
    """Diagnosis outputs assembled after building findings."""

    findings: list[Finding]
    most_likely_origin: OriginSummary
    test_plan: list[TestStep]
    phase_timeline: list[PhaseTimelineEntry]
    top_causes: list[TopCause]


@dataclass(frozen=True)
class SensorAnalysisBundle:
    """Location-scoped sensor analysis ready for summary/report use."""

    sensor_locations: list[str]
    connected_locations: set[str]
    sensor_intensity_by_location: list[IntensityRow]


@dataclass(frozen=True)
class RunSuitabilityBundle:
    """Run-suitability evaluation and confidence context."""

    reference_complete: bool
    run_suitability: list[RunSuitabilityCheck]
    overall_strength_band_key: str | None


@dataclass(frozen=True)
class SummaryComputation:
    """Aggregated intermediate state used to build the final summary payload."""

    prepared: PreparedRunData
    accel_stats: AccelStatistics
    findings: FindingsBundle
    sensors: SensorAnalysisBundle
    suitability: RunSuitabilityBundle
