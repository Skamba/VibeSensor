"""Plot-data builders: series and orchestration.

Spectral computation (FFT spectrum, spectrogram) has been extracted to
``spectrogram.py``. Peak-table ranking now lives in ``peak_table.py``.
This module keeps time-series extraction and the top-level ``_plot_data``
orchestrator.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from vibesensor.shared.boundaries.analysis_payload import (
    AmpVsPhaseRow,
    FreqVsSpeedByFindingSeries,
    MatchedAmpVsSpeedSeries,
    PhaseBoundary,
    PhaseSegmentOut,
    PlotDataResult,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.use_cases.diagnostics._types import Sample
from vibesensor.use_cases.diagnostics.helpers import (
    _primary_vibration_strength_db,
    _run_noise_baseline_g,
)
from vibesensor.use_cases.diagnostics.peak_table import top_peaks_table_rows
from vibesensor.use_cases.diagnostics.phase_segmentation import DrivingPhase, PhaseSegment
from vibesensor.use_cases.diagnostics.phase_segmentation import (
    segment_run_phases as _segment_run_phases,
)
from vibesensor.use_cases.diagnostics.spectrogram import (
    aggregate_fft_spectrum,
    aggregate_fft_spectrum_raw,
    scan_peak_samples,
    spectrogram_from_peaks,
    spectrogram_from_peaks_raw,
)
from vibesensor.vibration_strength import percentile

# ---------------------------------------------------------------------------
# Series types & builders (formerly plot_series.py)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlotSeriesBundle:
    """Intermediate series grouped by plot concern."""

    vib_magnitude: list[tuple[float, float, str]]
    dominant_freq: list[tuple[float, float]]
    amp_vs_speed: list[tuple[float, float]]
    matched_amp_vs_speed: list[MatchedAmpVsSpeedSeries]
    freq_vs_speed_by_finding: list[FreqVsSpeedByFindingSeries]
    steady_speed_distribution: dict[str, float] | None
    amp_vs_phase: list[AmpVsPhaseRow]
    phase_segments_out: list[PhaseSegmentOut]
    phase_boundaries: list[PhaseBoundary]


def build_plot_series(
    summary: Mapping[str, Any],
    *,
    per_sample_phases: list[DrivingPhase],
    phase_segments: list[PhaseSegment],
    raw_sample_rate_hz: float | None,
) -> PlotSeriesBundle:
    """Build reusable time/speed/finding series for the plot payload."""
    samples: list[Sample] = summary.get("samples", [])
    vib_mag_points: list[tuple[float, float, str]] = []
    dominant_freq_points: list[tuple[float, float]] = []
    speed_amp_points: list[tuple[float, float]] = []
    matched_by_finding: list[MatchedAmpVsSpeedSeries] = []
    freq_vs_speed_by_finding: list[FreqVsSpeedByFindingSeries] = []

    for i, sample in enumerate(samples):
        t_s = _as_float(sample.get("t_s"))
        if t_s is None:
            continue
        phase_label = per_sample_phases[i].value if i < len(per_sample_phases) else "unknown"
        vib = _primary_vibration_strength_db(sample)
        if vib is not None:
            vib_mag_points.append((t_s, vib, phase_label))
        if raw_sample_rate_hz and raw_sample_rate_hz > 0:
            dominant_hz = _as_float(sample.get("dominant_freq_hz"))
            if dominant_hz is not None and dominant_hz > 0:
                dominant_freq_points.append((t_s, dominant_hz))

    for row in summary.get("speed_breakdown", []):
        speed_range = str(row.get("speed_range", ""))
        if "-" not in speed_range:
            continue
        prefix = speed_range.split(" ", 1)[0]
        low_text, _, high_text = prefix.partition("-")
        try:
            low = float(low_text)
            high = float(high_text)
        except ValueError:
            continue
        amp = _as_float(row.get("mean_vibration_strength_db"))
        if amp is None:
            continue
        speed_amp_points.append(((low + high) / 2.0, amp))

    for finding in summary.get("findings", []):
        points_raw = finding.get("matched_points")
        if not isinstance(points_raw, list):
            continue
        finding_label = str(finding.get("frequency_hz_or_order") or finding.get("finding_id"))
        matched_points: list[tuple[float, float]] = []
        freq_points: list[tuple[float, float]] = []
        predicted_points: list[tuple[float, float]] = []
        for pt in points_raw:
            if not isinstance(pt, dict):
                continue
            speed = _as_float(pt.get("speed_kmh"))
            amp = _as_float(pt.get("amp"))
            matched_hz = _as_float(pt.get("matched_hz"))
            predicted_hz = _as_float(pt.get("predicted_hz"))
            if speed is None or speed <= 0:
                continue
            if amp is not None:
                matched_points.append((speed, amp))
            if matched_hz is not None and matched_hz > 0:
                freq_points.append((speed, matched_hz))
            if predicted_hz is not None and predicted_hz > 0:
                predicted_points.append((speed, predicted_hz))
        if matched_points:
            matched_by_finding.append(
                MatchedAmpVsSpeedSeries(label=finding_label, points=matched_points),
            )
        if freq_points:
            freq_vs_speed_by_finding.append(
                FreqVsSpeedByFindingSeries(
                    label=finding_label,
                    matched=freq_points,
                    predicted=predicted_points,
                ),
            )

    steady_speed_distribution = build_steady_speed_distribution(
        summary,
        vib_mag_points=vib_mag_points,
    )
    amp_vs_phase = build_amp_vs_phase(summary)
    phase_segments_out, phase_boundaries = serialize_phase_context(phase_segments)
    return PlotSeriesBundle(
        vib_magnitude=vib_mag_points,
        dominant_freq=dominant_freq_points,
        amp_vs_speed=speed_amp_points,
        matched_amp_vs_speed=matched_by_finding,
        freq_vs_speed_by_finding=freq_vs_speed_by_finding,
        steady_speed_distribution=steady_speed_distribution,
        amp_vs_phase=amp_vs_phase,
        phase_segments_out=phase_segments_out,
        phase_boundaries=phase_boundaries,
    )


def build_steady_speed_distribution(
    summary: Mapping[str, Any],
    *,
    vib_mag_points: list[tuple[float, float, str]],
) -> dict[str, float] | None:
    """Build steady-speed percentile distribution when appropriate."""
    speed_stats = summary.get("speed_stats")
    if not (speed_stats and bool(speed_stats.get("steady_speed")) and vib_mag_points):
        return None
    vals = sorted(v for _t, v, _phase in vib_mag_points if v >= 0)
    if not vals:
        return None
    return {
        "p10": percentile(vals, 0.10),
        "p50": percentile(vals, 0.50),
        "p90": percentile(vals, 0.90),
        "p95": percentile(vals, 0.95),
    }


def build_amp_vs_phase(summary: Mapping[str, Any]) -> list[AmpVsPhaseRow]:
    """Shape the phase-grouped vibration rows for plotting."""
    amp_vs_phase: list[AmpVsPhaseRow] = []
    for row in summary.get("phase_speed_breakdown", []):
        phase = str(row.get("phase", ""))
        mean_vib = _as_float(row.get("mean_vibration_strength_db"))
        if not phase or mean_vib is None:
            continue
        amp_vs_phase.append(
            AmpVsPhaseRow(
                phase=phase,
                count=int(row.get("count") or 0),
                mean_vib_db=mean_vib,
                max_vib_db=_as_float(row.get("max_vibration_strength_db")),
                mean_speed_kmh=_as_float(row.get("mean_speed_kmh")),
            ),
        )
    return amp_vs_phase


def serialize_phase_context(
    phase_segments: list[PhaseSegment],
) -> tuple[list[PhaseSegmentOut], list[PhaseBoundary]]:
    """Serialize phase segments for plot consumers."""
    phase_segments_out: list[PhaseSegmentOut] = []
    phase_boundaries: list[PhaseBoundary] = []
    for segment in phase_segments:
        phase_value = segment.phase.value
        phase_segments_out.append(
            PhaseSegmentOut(
                phase=phase_value,
                start_t_s=segment.start_t_s,
                end_t_s=segment.end_t_s,
            ),
        )
        phase_boundaries.append(
            PhaseBoundary(
                phase=phase_value,
                t_s=segment.start_t_s,
                end_t_s=segment.end_t_s,
            ),
        )
    return phase_segments_out, phase_boundaries


# ---------------------------------------------------------------------------
# Plot-data orchestration (formerly plot_data.py)
# ---------------------------------------------------------------------------


def _plot_data(
    summary: Mapping[str, Any],
    *,
    run_noise_baseline_g: float | None = None,
    per_sample_phases: list[DrivingPhase] | None = None,
    phase_segments: list[PhaseSegment] | None = None,
) -> PlotDataResult:
    samples: list[Sample] = summary.get("samples", [])
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
        fft_spectrum=aggregate_fft_spectrum(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=peak_scan,
        ),
        fft_spectrum_raw=aggregate_fft_spectrum_raw(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=peak_scan,
        ),
        peaks_spectrogram=spectrogram_from_peaks(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=peak_scan,
        ),
        peaks_spectrogram_raw=spectrogram_from_peaks_raw(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=peak_scan,
        ),
        peaks_table=top_peaks_table_rows(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=peak_scan,
        ),
        phase_segments=series.phase_segments_out,
        phase_boundaries=series.phase_boundaries,
    )
