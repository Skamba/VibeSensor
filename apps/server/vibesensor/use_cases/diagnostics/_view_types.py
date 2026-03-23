"""Diagnostics output/view dataclasses used by plots, tables, and reports."""

from __future__ import annotations

from dataclasses import dataclass


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

    @property
    def peaks(self) -> PeakClassificationRowView:
        """Return the peak-classification view expected by serializers and reports."""
        return PeakClassificationRowView(classification=self.peak_classification)


@dataclass(frozen=True, slots=True)
class PeakClassificationRowView:
    """Minimal nested view of peak classification for report payload builders."""

    classification: str


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
