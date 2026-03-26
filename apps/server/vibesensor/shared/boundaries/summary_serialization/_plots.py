"""Plot, spectrogram, and table serialization helpers."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol

from vibesensor.domain import DrivingPhase
from vibesensor.shared.types.analysis_views import (
    AmpVsPhaseRow,
    FreqVsSpeedByFindingSeries,
    MatchedAmpVsSpeedSeries,
    PeakTableRow,
    PhaseBoundary,
    PhaseSegmentOut,
    PhaseSpeedBreakdownRow,
    PlotDataResult,
    SpectrogramResult,
    SpeedBreakdownRow,
)
from vibesensor.shared.types.history_analysis_contracts import (
    PhaseSegmentSummaryResponse as PhaseSegmentSummaryPayload,
)


class SpeedBreakdownRowLike(Protocol):
    @property
    def speed_range(self) -> str: ...
    @property
    def count(self) -> int: ...
    @property
    def mean_vibration_strength_db(self) -> float | None: ...
    @property
    def max_vibration_strength_db(self) -> float | None: ...


class PhaseSpeedBreakdownRowLike(Protocol):
    @property
    def phase(self) -> str: ...
    @property
    def count(self) -> int: ...
    @property
    def mean_speed_kmh(self) -> float | None: ...
    @property
    def max_speed_kmh(self) -> float | None: ...
    @property
    def mean_vibration_strength_db(self) -> float | None: ...
    @property
    def max_vibration_strength_db(self) -> float | None: ...


class PeakTableRowLike(Protocol):
    @property
    def rank(self) -> int: ...
    @property
    def frequency_hz(self) -> float: ...
    @property
    def order_label(self) -> str: ...
    @property
    def suspected_source(self) -> str: ...
    @property
    def max_intensity_db(self) -> float | None: ...
    @property
    def median_intensity_db(self) -> float | None: ...
    @property
    def p95_intensity_db(self) -> float | None: ...
    @property
    def run_noise_baseline_db(self) -> float | None: ...
    @property
    def median_vs_run_noise_ratio(self) -> float: ...
    @property
    def p95_vs_run_noise_ratio(self) -> float: ...
    @property
    def strength_floor_db(self) -> float | None: ...
    @property
    def strength_db(self) -> float | None: ...
    @property
    def presence_ratio(self) -> float: ...
    @property
    def burstiness(self) -> float: ...
    @property
    def persistence_score(self) -> float: ...
    @property
    def peak_classification(self) -> str: ...
    @property
    def typical_speed_band(self) -> str: ...


class SpectrogramResultLike(Protocol):
    @property
    def x_axis(self) -> str: ...
    @property
    def x_label_key(self) -> str: ...
    @property
    def x_bins(self) -> Sequence[float]: ...
    @property
    def y_bins(self) -> Sequence[float]: ...
    @property
    def cells(self) -> Sequence[Sequence[float]]: ...
    @property
    def max_amp(self) -> float: ...
    @property
    def x_bin_width(self) -> float | None: ...
    @property
    def y_bin_width(self) -> float | None: ...


class AmpVsPhaseRowLike(Protocol):
    @property
    def phase(self) -> str: ...
    @property
    def count(self) -> int: ...
    @property
    def mean_vib_db(self) -> float: ...
    @property
    def max_vib_db(self) -> float | None: ...
    @property
    def mean_speed_kmh(self) -> float | None: ...


class MatchedAmpVsSpeedSeriesLike(Protocol):
    @property
    def label(self) -> str: ...
    @property
    def points(self) -> Sequence[tuple[float, float]]: ...


class FreqVsSpeedByFindingSeriesLike(Protocol):
    @property
    def label(self) -> str: ...
    @property
    def matched(self) -> Sequence[tuple[float, float]]: ...
    @property
    def predicted(self) -> Sequence[tuple[float, float]]: ...


class PhaseSegmentPlotLike(Protocol):
    @property
    def phase(self) -> str: ...
    @property
    def start_t_s(self) -> float | None: ...
    @property
    def end_t_s(self) -> float | None: ...


class PhaseBoundaryLike(Protocol):
    @property
    def phase(self) -> str: ...
    @property
    def t_s(self) -> float | None: ...
    @property
    def end_t_s(self) -> float | None: ...


class PlotDataResultLike(Protocol):
    @property
    def vib_magnitude(self) -> Sequence[tuple[float, float, str]]: ...
    @property
    def dominant_freq(self) -> Sequence[tuple[float, float]]: ...
    @property
    def amp_vs_speed(self) -> Sequence[tuple[float, float]]: ...
    @property
    def amp_vs_phase(self) -> Sequence[AmpVsPhaseRowLike]: ...
    @property
    def matched_amp_vs_speed(self) -> Sequence[MatchedAmpVsSpeedSeriesLike]: ...
    @property
    def freq_vs_speed_by_finding(self) -> Sequence[FreqVsSpeedByFindingSeriesLike]: ...
    @property
    def steady_speed_distribution(self) -> dict[str, float] | None: ...
    @property
    def fft_spectrum(self) -> Sequence[tuple[float, float]]: ...
    @property
    def fft_spectrum_raw(self) -> Sequence[tuple[float, float]]: ...
    @property
    def peaks_spectrogram(self) -> SpectrogramResultLike: ...
    @property
    def peaks_spectrogram_raw(self) -> SpectrogramResultLike: ...
    @property
    def peaks_table(self) -> Sequence[PeakTableRowLike]: ...
    @property
    def phase_segments(self) -> Sequence[PhaseSegmentPlotLike]: ...
    @property
    def phase_boundaries(self) -> Sequence[PhaseBoundaryLike]: ...


class PhaseSegmentLike(Protocol):
    @property
    def phase(self) -> DrivingPhase: ...
    @property
    def start_idx(self) -> int: ...
    @property
    def end_idx(self) -> int: ...
    @property
    def start_t_s(self) -> float: ...
    @property
    def end_t_s(self) -> float: ...
    @property
    def speed_min_kmh(self) -> float | None: ...
    @property
    def speed_max_kmh(self) -> float | None: ...
    @property
    def sample_count(self) -> int: ...


def serialize_phase_segments(
    phase_segments: Sequence[PhaseSegmentLike],
) -> list[PhaseSegmentSummaryPayload]:
    """Serialize phase segments to JSON-safe dicts."""
    return [
        {
            "phase": seg.phase.value,
            "start_idx": seg.start_idx,
            "end_idx": seg.end_idx,
            "start_t_s": (
                None
                if isinstance(seg.start_t_s, float) and math.isnan(seg.start_t_s)
                else seg.start_t_s
            ),
            "end_t_s": (
                None if isinstance(seg.end_t_s, float) and math.isnan(seg.end_t_s) else seg.end_t_s
            ),
            "speed_min_kmh": seg.speed_min_kmh,
            "speed_max_kmh": seg.speed_max_kmh,
            "sample_count": seg.sample_count,
        }
        for seg in phase_segments
    ]


def serialize_speed_breakdown(
    rows: Sequence[SpeedBreakdownRowLike],
) -> list[SpeedBreakdownRow]:
    """Project speed-breakdown rows into their persisted summary payload shape."""
    payload_rows: list[SpeedBreakdownRow] = []
    for row in rows:
        payload: SpeedBreakdownRow = {
            "speed_range": row.speed_range,
            "count": row.count,
            "mean_vibration_strength_db": row.mean_vibration_strength_db,
            "max_vibration_strength_db": row.max_vibration_strength_db,
        }
        payload_rows.append(payload)
    return payload_rows


def serialize_phase_speed_breakdown(
    rows: Sequence[PhaseSpeedBreakdownRowLike],
) -> list[PhaseSpeedBreakdownRow]:
    """Project per-phase speed breakdown rows into persisted summary payloads."""
    payload_rows: list[PhaseSpeedBreakdownRow] = []
    for row in rows:
        payload: PhaseSpeedBreakdownRow = {
            "phase": row.phase,
            "count": row.count,
            "mean_speed_kmh": row.mean_speed_kmh,
            "max_speed_kmh": row.max_speed_kmh,
            "mean_vibration_strength_db": row.mean_vibration_strength_db,
            "max_vibration_strength_db": row.max_vibration_strength_db,
        }
        payload_rows.append(payload)
    return payload_rows


def serialize_peak_table(
    rows: Sequence[PeakTableRowLike],
) -> list[PeakTableRow]:
    """Project peak-table rows into persisted summary payload dictionaries."""
    payload_rows: list[PeakTableRow] = []
    for row in rows:
        payload: PeakTableRow = {
            "rank": row.rank,
            "frequency_hz": row.frequency_hz,
            "order_label": row.order_label,
            "max_intensity_db": row.max_intensity_db,
            "median_intensity_db": row.median_intensity_db,
            "p95_intensity_db": row.p95_intensity_db,
            "run_noise_baseline_db": row.run_noise_baseline_db,
            "median_vs_run_noise_ratio": row.median_vs_run_noise_ratio,
            "p95_vs_run_noise_ratio": row.p95_vs_run_noise_ratio,
            "strength_floor_db": row.strength_floor_db,
            "strength_db": row.strength_db,
            "presence_ratio": row.presence_ratio,
            "burstiness": row.burstiness,
            "persistence_score": row.persistence_score,
            "suspected_source": row.suspected_source,
            "peak_classification": row.peak_classification,
            "typical_speed_band": row.typical_speed_band,
        }
        payload_rows.append(payload)
    return payload_rows


def serialize_spectrogram(result: SpectrogramResultLike) -> SpectrogramResult:
    """Project a spectrogram result into a JSON-safe persisted payload."""
    payload: SpectrogramResult = {
        "x_axis": result.x_axis,
        "x_label_key": result.x_label_key,
        "x_bins": list(result.x_bins),
        "y_bins": list(result.y_bins),
        "cells": [list(row) for row in result.cells],
        "max_amp": result.max_amp,
    }
    if result.x_bin_width is not None:
        payload["x_bin_width"] = result.x_bin_width
    if result.y_bin_width is not None:
        payload["y_bin_width"] = result.y_bin_width
    return payload


def serialize_plot_data(plot_data: PlotDataResultLike) -> PlotDataResult:
    """Project composite plot data into the persisted summary payload shape."""
    amp_vs_phase: list[AmpVsPhaseRow] = []
    for phase_row in plot_data.amp_vs_phase:
        phase_payload: AmpVsPhaseRow = {
            "phase": phase_row.phase,
            "count": phase_row.count,
            "mean_vib_db": phase_row.mean_vib_db,
            "max_vib_db": phase_row.max_vib_db,
            "mean_speed_kmh": phase_row.mean_speed_kmh,
        }
        amp_vs_phase.append(phase_payload)

    matched_amp_vs_speed: list[MatchedAmpVsSpeedSeries] = []
    for matched_row in plot_data.matched_amp_vs_speed:
        matched_payload: MatchedAmpVsSpeedSeries = {
            "label": matched_row.label,
            "points": list(matched_row.points),
        }
        matched_amp_vs_speed.append(matched_payload)

    freq_vs_speed_by_finding: list[FreqVsSpeedByFindingSeries] = []
    for freq_row in plot_data.freq_vs_speed_by_finding:
        freq_payload: FreqVsSpeedByFindingSeries = {
            "label": freq_row.label,
            "matched": list(freq_row.matched),
            "predicted": list(freq_row.predicted),
        }
        freq_vs_speed_by_finding.append(freq_payload)

    phase_segments: list[PhaseSegmentOut] = []
    for segment_row in plot_data.phase_segments:
        segment_payload: PhaseSegmentOut = {
            "phase": segment_row.phase,
            "start_t_s": segment_row.start_t_s,
            "end_t_s": segment_row.end_t_s,
        }
        phase_segments.append(segment_payload)

    phase_boundaries: list[PhaseBoundary] = []
    for boundary_row in plot_data.phase_boundaries:
        boundary_payload: PhaseBoundary = {
            "phase": boundary_row.phase,
            "t_s": boundary_row.t_s,
            "end_t_s": boundary_row.end_t_s,
        }
        phase_boundaries.append(boundary_payload)

    return {
        "vib_magnitude": list(plot_data.vib_magnitude),
        "dominant_freq": list(plot_data.dominant_freq),
        "amp_vs_speed": list(plot_data.amp_vs_speed),
        "amp_vs_phase": amp_vs_phase,
        "matched_amp_vs_speed": matched_amp_vs_speed,
        "freq_vs_speed_by_finding": freq_vs_speed_by_finding,
        "steady_speed_distribution": plot_data.steady_speed_distribution,
        "fft_spectrum": list(plot_data.fft_spectrum),
        "fft_spectrum_raw": list(plot_data.fft_spectrum_raw),
        "peaks_spectrogram": serialize_spectrogram(plot_data.peaks_spectrogram),
        "peaks_spectrogram_raw": serialize_spectrogram(plot_data.peaks_spectrogram_raw),
        "peaks_table": serialize_peak_table(plot_data.peaks_table),
        "phase_segments": phase_segments,
        "phase_boundaries": phase_boundaries,
    }
