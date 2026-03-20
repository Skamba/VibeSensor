"""Analysis-internal type aliases and value objects.

Boundary serialization TypedDicts (``FindingPayload``, ``AnalysisSummary``,
etc.) live in ``vibesensor.shared.boundaries.analysis_payload``.
This module is the diagnostics package's internal source of truth for
analysis-local value objects that should not depend on boundary payload
TypedDicts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeAlias, TypedDict

from vibesensor.shared.types.json_types import JsonObject
from vibesensor.use_cases.diagnostics.phase_segmentation import DrivingPhase

Sample: TypeAlias = JsonObject
"""A single recorded sample row.  Alias for ``JsonObject``; used for
semantic clarity across analysis modules, not additional type safety."""


class AccelStatistics(TypedDict):
    accel_x_vals: list[float]
    accel_y_vals: list[float]
    accel_z_vals: list[float]
    accel_mag_vals: list[float]
    amp_metric_values: list[float]
    sat_count: int
    sensor_limit: float | None
    x_mean: float | None
    x_var: float | None
    y_mean: float | None
    y_var: float | None
    z_mean: float | None
    z_var: float | None


PhaseLabel: TypeAlias = DrivingPhase | str
PhaseLabels: TypeAlias = Sequence[PhaseLabel]


@dataclass(frozen=True, slots=True)
class SpeedBreakdownRowData:
    speed_range: str
    count: int
    mean_vibration_strength_db: float | None
    max_vibration_strength_db: float | None


@dataclass(frozen=True, slots=True)
class PhaseSpeedBreakdownRowData:
    phase: str
    count: int
    mean_speed_kmh: float | None
    max_speed_kmh: float | None
    mean_vibration_strength_db: float | None
    max_vibration_strength_db: float | None


@dataclass(frozen=True, slots=True)
class MatchedAmpVsSpeedSeriesData:
    label: str
    points: list[tuple[float, float]]


@dataclass(frozen=True, slots=True)
class FreqVsSpeedByFindingSeriesData:
    label: str
    matched: list[tuple[float, float]]
    predicted: list[tuple[float, float]]


@dataclass(frozen=True, slots=True)
class AmpVsPhaseRowData:
    phase: str
    count: int
    mean_vib_db: float
    max_vib_db: float | None
    mean_speed_kmh: float | None


@dataclass(frozen=True, slots=True)
class PhaseSegmentPlotData:
    phase: str
    start_t_s: float | None
    end_t_s: float | None


@dataclass(frozen=True, slots=True)
class PhaseBoundaryData:
    phase: str
    t_s: float | None
    end_t_s: float | None


@dataclass(frozen=True, slots=True)
class PlotSeriesBundle:
    """Intermediate series grouped by plot concern."""

    vib_magnitude: list[tuple[float, float, str]]
    dominant_freq: list[tuple[float, float]]
    amp_vs_speed: list[tuple[float, float]]
    matched_amp_vs_speed: list[MatchedAmpVsSpeedSeriesData]
    freq_vs_speed_by_finding: list[FreqVsSpeedByFindingSeriesData]
    steady_speed_distribution: dict[str, float] | None
    amp_vs_phase: list[AmpVsPhaseRowData]
    phase_segments_out: list[PhaseSegmentPlotData]
    phase_boundaries: list[PhaseBoundaryData]


@dataclass(frozen=True, slots=True)
class PeakTableRowData:
    rank: int
    frequency_hz: float
    order_label: str
    suspected_source: str
    max_intensity_db: float | None
    median_intensity_db: float | None
    p95_intensity_db: float | None
    run_noise_baseline_db: float | None
    median_vs_run_noise_ratio: float
    p95_vs_run_noise_ratio: float
    strength_floor_db: float | None
    strength_db: float | None
    presence_ratio: float
    burstiness: float
    persistence_score: float
    peak_classification: str
    typical_speed_band: str


@dataclass(frozen=True, slots=True)
class SpectrogramResultData:
    x_axis: str
    x_label_key: str
    x_bins: list[float]
    y_bins: list[float]
    cells: list[list[float]]
    max_amp: float
    x_bin_width: float | None = None
    y_bin_width: float | None = None


@dataclass(frozen=True, slots=True)
class PlotDataResultData:
    vib_magnitude: list[tuple[float, float, str]]
    dominant_freq: list[tuple[float, float]]
    amp_vs_speed: list[tuple[float, float]]
    amp_vs_phase: list[AmpVsPhaseRowData]
    matched_amp_vs_speed: list[MatchedAmpVsSpeedSeriesData]
    freq_vs_speed_by_finding: list[FreqVsSpeedByFindingSeriesData]
    steady_speed_distribution: dict[str, float] | None
    fft_spectrum: list[tuple[float, float]]
    fft_spectrum_raw: list[tuple[float, float]]
    peaks_spectrogram: SpectrogramResultData
    peaks_spectrogram_raw: SpectrogramResultData
    peaks_table: list[PeakTableRowData]
    phase_segments: list[PhaseSegmentPlotData]
    phase_boundaries: list[PhaseBoundaryData]
