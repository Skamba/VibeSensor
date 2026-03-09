"""Plot-data orchestration for analysis summaries."""

from __future__ import annotations

from typing import TypedDict

from ..runlog import as_float_or_none as _as_float
from ._types import Sample, SummaryData
from .helpers import _run_noise_baseline_g
from .phase_segmentation import DrivingPhase, PhaseSegment
from .phase_segmentation import segment_run_phases as _segment_run_phases
from .plot_peak_table import PeakTableRow, top_peaks_table_rows
from .plot_series import (
    AmpVsPhaseRow,
    FreqVsSpeedByFindingSeries,
    MatchedAmpVsSpeedSeries,
    PhaseBoundary,
    PhaseSegmentOut,
    build_plot_series,
)
from .plot_spectrum import (
    PeakSampleScan,
    SpectrogramResult,
    aggregate_fft_spectrum,
    aggregate_fft_spectrum_raw,
    scan_peak_samples,
    spectrogram_from_peaks,
    spectrogram_from_peaks_raw,
)


class PlotDataResult(TypedDict):
    """Shape returned by the plot-data orchestration layer."""

    vib_magnitude: list[tuple[float, float, str]]
    dominant_freq: list[tuple[float, float]]
    amp_vs_speed: list[tuple[float, float]]
    amp_vs_phase: list[AmpVsPhaseRow]
    matched_amp_vs_speed: list[MatchedAmpVsSpeedSeries]
    freq_vs_speed_by_finding: list[FreqVsSpeedByFindingSeries]
    steady_speed_distribution: dict[str, float] | None
    fft_spectrum: list[tuple[float, float]]
    fft_spectrum_raw: list[tuple[float, float]]
    peaks_spectrogram: SpectrogramResult
    peaks_spectrogram_raw: SpectrogramResult
    peaks_table: list[PeakTableRow]
    phase_segments: list[PhaseSegmentOut]
    phase_boundaries: list[PhaseBoundary]


def _aggregate_fft_spectrum(
    samples: list[Sample],
    *,
    freq_bin_hz: float = 2.0,
    aggregation: str = "persistence",
    run_noise_baseline_g: float | None = None,
    peak_scan: PeakSampleScan | None = None,
) -> list[tuple[float, float]]:
    return aggregate_fft_spectrum(
        samples,
        freq_bin_hz=freq_bin_hz,
        aggregation=aggregation,
        run_noise_baseline_g=run_noise_baseline_g,
        peak_scan=peak_scan,
    )


def _aggregate_fft_spectrum_raw(
    samples: list[Sample],
    *,
    freq_bin_hz: float = 2.0,
    run_noise_baseline_g: float | None = None,
    peak_scan: PeakSampleScan | None = None,
) -> list[tuple[float, float]]:
    return aggregate_fft_spectrum_raw(
        samples,
        freq_bin_hz=freq_bin_hz,
        run_noise_baseline_g=run_noise_baseline_g,
        peak_scan=peak_scan,
    )


def _spectrogram_from_peaks(
    samples: list[Sample],
    *,
    run_noise_baseline_g: float | None = None,
    peak_scan: PeakSampleScan | None = None,
) -> SpectrogramResult:
    return spectrogram_from_peaks(
        samples,
        run_noise_baseline_g=run_noise_baseline_g,
        peak_scan=peak_scan,
    )


def _spectrogram_from_peaks_raw(
    samples: list[Sample],
    *,
    run_noise_baseline_g: float | None = None,
    peak_scan: PeakSampleScan | None = None,
) -> SpectrogramResult:
    return spectrogram_from_peaks_raw(
        samples,
        run_noise_baseline_g=run_noise_baseline_g,
        peak_scan=peak_scan,
    )


def _top_peaks_table_rows(
    samples: list[Sample],
    *,
    top_n: int = 12,
    freq_bin_hz: float = 1.0,
    run_noise_baseline_g: float | None = None,
    peak_scan: PeakSampleScan | None = None,
) -> list[PeakTableRow]:
    return top_peaks_table_rows(
        samples,
        top_n=top_n,
        freq_bin_hz=freq_bin_hz,
        run_noise_baseline_g=run_noise_baseline_g,
        peak_scan=peak_scan,
    )


def _plot_data(
    summary: SummaryData,
    *,
    run_noise_baseline_g: float | None = None,
    per_sample_phases: list[DrivingPhase] | None = None,
    phase_segments: list[PhaseSegment] | None = None,
) -> PlotDataResult:
    samples: list[Sample] = summary.get("samples", [])  # type: ignore[assignment]
    raw_sample_rate_hz = _as_float(summary.get("raw_sample_rate_hz"))
    if run_noise_baseline_g is None:
        run_noise_baseline_g = _run_noise_baseline_g(samples)

    if per_sample_phases is not None and phase_segments is not None:
        resolved_phases = per_sample_phases
        resolved_phase_segments = phase_segments
    else:
        resolved_phases, resolved_phase_segments = _segment_run_phases(samples)

    peak_scan = scan_peak_samples(samples)

    series = build_plot_series(
        summary,
        per_sample_phases=resolved_phases,
        phase_segments=resolved_phase_segments,
        raw_sample_rate_hz=raw_sample_rate_hz,
    )
    return PlotDataResult(
        vib_magnitude=series.vib_magnitude,
        dominant_freq=series.dominant_freq,
        amp_vs_speed=series.amp_vs_speed,
        amp_vs_phase=series.amp_vs_phase,
        matched_amp_vs_speed=series.matched_amp_vs_speed,
        freq_vs_speed_by_finding=series.freq_vs_speed_by_finding,
        steady_speed_distribution=series.steady_speed_distribution,
        fft_spectrum=_aggregate_fft_spectrum(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=peak_scan,
        ),
        fft_spectrum_raw=_aggregate_fft_spectrum_raw(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=peak_scan,
        ),
        peaks_spectrogram=_spectrogram_from_peaks(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=peak_scan,
        ),
        peaks_spectrogram_raw=_spectrogram_from_peaks_raw(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=peak_scan,
        ),
        peaks_table=_top_peaks_table_rows(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=peak_scan,
        ),
        phase_segments=series.phase_segments_out,
        phase_boundaries=series.phase_boundaries,
    )
