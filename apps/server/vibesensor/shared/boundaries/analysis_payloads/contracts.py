"""Protocols used by analysis-summary boundary serialization."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from typing import Protocol

from vibesensor.domain import (
    DrivingPhaseInterval,
    LocationIntensitySummary,
    RunSuitability,
    TestRun,
)
from vibesensor.domain.driving_phase_summary import DrivingPhaseSummary
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.boundaries.summary_serialization import (
    AccelStatisticsLike,
    PhaseSegmentLike,
    PhaseSpeedBreakdownRowLike,
    PlotDataResultLike,
    SpeedBreakdownRowLike,
)
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.shared.types.run_schema import RunMetadata


class PreparedRunDataLike(Protocol):
    @property
    def run_id(self) -> str: ...

    @property
    def duration_s(self) -> float: ...

    @property
    def raw_sample_rate_hz(self) -> float | None: ...

    @property
    def speed_breakdown(self) -> Sequence[SpeedBreakdownRowLike]: ...

    @property
    def phase_speed_breakdown(self) -> Sequence[PhaseSpeedBreakdownRowLike]: ...

    @property
    def phase_segments(self) -> Sequence[PhaseSegmentLike]: ...

    @property
    def run_noise_baseline_g(self) -> float | None: ...

    @property
    def speed_breakdown_skipped_reason(self) -> JsonObject | None: ...

    @property
    def speed_stats_by_phase(self) -> Mapping[str, SpeedProfileSummary]: ...

    @property
    def speed_values(self) -> list[float]: ...

    @property
    def speed_non_null_pct(self) -> float: ...


class AnalysisResultLike(Protocol):
    @property
    def file_name(self) -> str: ...

    @property
    def metadata(self) -> RunMetadata: ...

    @property
    def samples(self) -> Sequence: ...

    @property
    def language(self) -> str: ...

    @property
    def include_samples(self) -> bool: ...

    @property
    def prepared(self) -> PreparedRunDataLike: ...

    @property
    def accel_stats(self) -> AccelStatisticsLike: ...

    @property
    def reference_complete(self) -> bool: ...

    @property
    def run_suitability(self) -> RunSuitability | None: ...

    @property
    def most_likely_origin(self) -> VibrationOrigin | None: ...

    @property
    def phase_timeline(self) -> Sequence[DrivingPhaseInterval]: ...

    @property
    def sensor_locations(self) -> Sequence[str]: ...

    @property
    def connected_locations(self) -> Collection[str]: ...

    @property
    def sensor_intensity_by_location(self) -> Sequence[LocationIntensitySummary]: ...

    @property
    def summary_speed_stats(self) -> SpeedProfileSummary: ...

    @property
    def summary_phase_info(self) -> DrivingPhaseSummary: ...

    @property
    def plot_data(self) -> PlotDataResultLike: ...

    @property
    def test_run(self) -> TestRun: ...
