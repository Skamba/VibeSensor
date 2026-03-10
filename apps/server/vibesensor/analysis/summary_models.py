"""Explicit intermediate models for the run-summary diagnosis pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ._types import (
    I18nRef,
    PhaseSpeedBreakdownRow,
    PhaseSpeedStats,
    PhaseSummary,
    SpeedBreakdownRow,
    SpeedStats,
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
