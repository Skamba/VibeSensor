"""Canonical app-level diagnostics analysis result."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain import (
    DiagnosticCase,
    DrivingPhaseInterval,
    LocationIntensitySummary,
    RunSuitability,
    TestRun,
)
from vibesensor.domain.driving_phase_summary import DrivingPhaseSummary
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.types.run_schema import RunMetadata

from ._types import AccelStatistics, Sample
from ._view_types import PlotDataResultData
from .run_data_preparation import PreparedRunData

__all__ = ["AnalysisResult"]


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """App-level analysis result for a completed run."""

    file_name: str
    metadata: RunMetadata
    samples: tuple[Sample, ...]
    language: str
    include_samples: bool
    prepared: PreparedRunData
    accel_stats: AccelStatistics
    reference_complete: bool
    run_suitability: RunSuitability | None
    most_likely_origin: VibrationOrigin | None
    phase_timeline: tuple[DrivingPhaseInterval, ...]
    sensor_locations: tuple[str, ...]
    connected_locations: frozenset[str]
    sensor_intensity_by_location: tuple[LocationIntensitySummary, ...]
    summary_speed_stats: SpeedProfileSummary
    summary_phase_info: DrivingPhaseSummary
    plot_data: PlotDataResultData

    test_run: TestRun
    diagnostic_case: DiagnosticCase
