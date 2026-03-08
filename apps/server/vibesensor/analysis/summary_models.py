"""Explicit intermediate models for the run-summary diagnosis pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

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
    speed_stats: dict[str, Any]
    speed_non_null_pct: float
    speed_sufficient: bool
    per_sample_phases: list[DrivingPhase]
    phase_segments: list[PhaseSegment]
    run_noise_baseline_g: float | None
    phase_info: dict[str, Any]
    speed_stats_by_phase: dict[str, Any]
    speed_breakdown: list[dict[str, Any]]
    speed_breakdown_skipped_reason: object
    phase_speed_breakdown: list[dict[str, Any]]


@dataclass(frozen=True)
class FindingsBundle:
    """Diagnosis outputs assembled after building findings."""

    findings: list[dict[str, Any]]
    most_likely_origin: dict[str, Any]
    test_plan: list[dict[str, Any]]
    phase_timeline: list[dict[str, Any]]
    top_causes: list[dict[str, Any]]


@dataclass(frozen=True)
class SensorAnalysisBundle:
    """Location-scoped sensor analysis ready for summary/report use."""

    sensor_locations: list[str]
    connected_locations: set[str]
    sensor_intensity_by_location: list[dict[str, Any]]


@dataclass(frozen=True)
class RunSuitabilityBundle:
    """Run-suitability evaluation and confidence context."""

    reference_complete: bool
    run_suitability: list[dict[str, Any]]
    overall_strength_band_key: str | None


@dataclass(frozen=True)
class SummaryComputation:
    """Aggregated intermediate state used to build the final summary payload."""

    prepared: PreparedRunData
    accel_stats: dict[str, Any]
    findings: FindingsBundle
    sensors: SensorAnalysisBundle
    suitability: RunSuitabilityBundle
