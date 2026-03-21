"""Plot, spectrogram, and table serialization helpers."""

from __future__ import annotations

import math
from collections.abc import Sequence

from vibesensor.shared.boundaries.analysis_payload import (
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
from vibesensor.shared.types.json_types import JsonObject

from ._contracts import (
    PeakTableRowLike,
    PhaseSegmentLike,
    PhaseSpeedBreakdownRowLike,
    PlotDataResultLike,
    SpectrogramResultLike,
    SpeedBreakdownRowLike,
)


def serialize_phase_segments(phase_segments: Sequence[PhaseSegmentLike]) -> list[JsonObject]:
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
