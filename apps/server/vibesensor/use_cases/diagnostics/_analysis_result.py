"""Canonical app-level diagnostics analysis result."""

from __future__ import annotations

from dataclasses import dataclass

from vibesensor.domain.diagnostic_case import DiagnosticCase
from vibesensor.domain.driving_phase_summary import DrivingPhaseSummary
from vibesensor.domain.driving_segment import DrivingPhaseInterval
from vibesensor.domain.location_hotspot import LocationIntensitySummary
from vibesensor.domain.run_suitability import RunSuitability
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.domain.test_run import TestRun
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.use_cases.diagnostics._types import AccelStatistics, Sample
from vibesensor.use_cases.diagnostics._view_types import PeakTableRowData
from vibesensor.use_cases.diagnostics.run_data_preparation import PreparedRunData

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
    peaks_table: list[PeakTableRowData]

    test_run: TestRun
    diagnostic_case: DiagnosticCase
