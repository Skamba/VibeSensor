"""Plot-data builders: series and orchestration.

Spectral computation (FFT spectrum, spectrogram) has been extracted to
``spectrogram.py``. Peak-table ranking now lives in ``peak_table.py``.
This module keeps time-series extraction and the top-level ``_plot_data``
orchestrator.
"""

from __future__ import annotations

from collections.abc import Sequence

from vibesensor.domain import Finding as DomainFinding
from vibesensor.use_cases.diagnostics._sample_metrics import (
    _primary_vibration_strength_db,
    _run_noise_baseline_g,
)
from vibesensor.use_cases.diagnostics._types import Sample
from vibesensor.use_cases.diagnostics._view_types import (
    AmpVsPhaseRowData,
    FreqVsSpeedByFindingSeriesData,
    MatchedAmpVsSpeedSeriesData,
    PhaseBoundaryData,
    PhaseSegmentPlotData,
    PhaseSpeedBreakdownRowData,
    PlotDataResultData,
    PlotSeriesBundle,
    SpeedBreakdownRowData,
)
from vibesensor.use_cases.diagnostics.peaks.table import (
    annotate_peak_rows_with_order_labels,
    top_peaks_table_rows,
)
from vibesensor.use_cases.diagnostics.phase_segmentation import (
    DrivingPhase,
    PhaseSegment,
    segment_run_phases,
)
from vibesensor.use_cases.diagnostics.spectrogram import (
    PeakSampleScan,
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


def build_plot_series(
    *,
    samples: Sequence[Sample],
    speed_breakdown: Sequence[SpeedBreakdownRowData],
    phase_speed_breakdown: Sequence[PhaseSpeedBreakdownRowData],
    findings: Sequence[DomainFinding],
    steady_speed: bool,
    per_sample_phases: Sequence[DrivingPhase],
    phase_segments: Sequence[PhaseSegment],
    raw_sample_rate_hz: float | None,
) -> PlotSeriesBundle:
    """Build reusable time/speed/finding series for the plot payload."""
    vib_mag_points: list[tuple[float, float, str]] = []
    dominant_freq_points: list[tuple[float, float]] = []
    speed_amp_points: list[tuple[float, float]] = []
    matched_by_finding: list[MatchedAmpVsSpeedSeriesData] = []
    freq_vs_speed_by_finding: list[FreqVsSpeedByFindingSeriesData] = []

    for i, sample in enumerate(samples):
        t_s = sample.t_s
        if t_s is None:
            continue
        phase_label = per_sample_phases[i].value if i < len(per_sample_phases) else "unknown"
        vib = _primary_vibration_strength_db(sample)
        if vib is not None:
            vib_mag_points.append((t_s, vib, phase_label))
        if raw_sample_rate_hz and raw_sample_rate_hz > 0:
            dominant_hz = sample.dominant_freq_hz
            if dominant_hz is not None and dominant_hz > 0:
                dominant_freq_points.append((t_s, dominant_hz))

    for row in speed_breakdown:
        speed_range = row.speed_range
        if "-" not in speed_range:
            continue
        prefix = speed_range.split(" ", 1)[0]
        low_text, _, high_text = prefix.partition("-")
        try:
            low = float(low_text)
            high = float(high_text)
        except ValueError:
            continue
        amp = row.mean_vibration_strength_db
        if amp is None:
            continue
        speed_amp_points.append(((low + high) / 2.0, amp))

    for finding in findings:
        if not finding.matched_points:
            continue
        finding_label = _finding_series_label(finding)
        matched_points: list[tuple[float, float]] = []
        freq_points: list[tuple[float, float]] = []
        predicted_points: list[tuple[float, float]] = []
        for point in finding.matched_points:
            speed = point.speed_kmh
            if speed is None or speed <= 0:
                continue
            matched_points.append((speed, point.amp))
            if point.matched_hz > 0:
                freq_points.append((speed, point.matched_hz))
            if point.predicted_hz > 0:
                predicted_points.append((speed, point.predicted_hz))
        if matched_points:
            matched_by_finding.append(
                MatchedAmpVsSpeedSeriesData(label=finding_label, points=matched_points),
            )
        if freq_points:
            freq_vs_speed_by_finding.append(
                FreqVsSpeedByFindingSeriesData(
                    label=finding_label,
                    matched=freq_points,
                    predicted=predicted_points,
                ),
            )

    steady_speed_distribution = build_steady_speed_distribution(
        steady_speed=steady_speed,
        vib_mag_points=vib_mag_points,
    )
    amp_vs_phase = build_amp_vs_phase(phase_speed_breakdown)
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


def _finding_series_label(finding: DomainFinding) -> str:
    raw_label: object = (
        finding.frequency_hz
        if finding.frequency_hz is not None
        else (finding.order or finding.finding_id)
    )
    return str(raw_label)


def build_steady_speed_distribution(
    *,
    steady_speed: bool,
    vib_mag_points: Sequence[tuple[float, float, str]],
) -> dict[str, float] | None:
    """Build steady-speed percentile distribution when appropriate."""
    if not (steady_speed and vib_mag_points):
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


def build_amp_vs_phase(
    phase_speed_breakdown: Sequence[PhaseSpeedBreakdownRowData],
) -> list[AmpVsPhaseRowData]:
    """Shape the phase-grouped vibration rows for plotting."""
    amp_vs_phase: list[AmpVsPhaseRowData] = []
    for row in phase_speed_breakdown:
        if not row.phase or row.mean_vibration_strength_db is None:
            continue
        amp_vs_phase.append(
            AmpVsPhaseRowData(
                phase=row.phase,
                count=row.count,
                mean_vib_db=row.mean_vibration_strength_db,
                max_vib_db=row.max_vibration_strength_db,
                mean_speed_kmh=row.mean_speed_kmh,
            ),
        )
    return amp_vs_phase


def serialize_phase_context(
    phase_segments: Sequence[PhaseSegment],
) -> tuple[list[PhaseSegmentPlotData], list[PhaseBoundaryData]]:
    """Serialize phase segments for plot consumers."""
    phase_segments_out: list[PhaseSegmentPlotData] = []
    phase_boundaries: list[PhaseBoundaryData] = []
    for segment in phase_segments:
        phase_value = segment.phase.value
        phase_segments_out.append(
            PhaseSegmentPlotData(
                phase=phase_value,
                start_t_s=segment.start_t_s,
                end_t_s=segment.end_t_s,
            ),
        )
        phase_boundaries.append(
            PhaseBoundaryData(
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
    *,
    samples: Sequence[Sample],
    speed_breakdown: Sequence[SpeedBreakdownRowData],
    phase_speed_breakdown: Sequence[PhaseSpeedBreakdownRowData],
    findings: Sequence[DomainFinding],
    raw_sample_rate_hz: float | None,
    steady_speed: bool,
    run_noise_baseline_g: float | None = None,
    per_sample_phases: Sequence[DrivingPhase] | None = None,
    phase_segments: Sequence[PhaseSegment] | None = None,
    peak_scan: PeakSampleScan | None = None,
) -> PlotDataResultData:
    if run_noise_baseline_g is None:
        run_noise_baseline_g = _run_noise_baseline_g(samples)

    if per_sample_phases is not None and phase_segments is not None:
        resolved_phases = per_sample_phases
        resolved_phase_segments = phase_segments
    else:
        resolved_phases, resolved_phase_segments = segment_run_phases(samples)

    resolved_peak_scan = peak_scan or scan_peak_samples(samples)
    series = build_plot_series(
        samples=samples,
        speed_breakdown=speed_breakdown,
        phase_speed_breakdown=phase_speed_breakdown,
        findings=findings,
        steady_speed=steady_speed,
        per_sample_phases=resolved_phases,
        phase_segments=resolved_phase_segments,
        raw_sample_rate_hz=raw_sample_rate_hz,
    )
    peaks_table = annotate_peak_rows_with_order_labels(
        top_peaks_table_rows(
            samples=list(samples),
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=resolved_peak_scan,
        ),
        findings,
    )
    return PlotDataResultData(
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
            peak_scan=resolved_peak_scan,
        ),
        fft_spectrum_raw=aggregate_fft_spectrum_raw(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=resolved_peak_scan,
        ),
        peaks_spectrogram=spectrogram_from_peaks(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=resolved_peak_scan,
        ),
        peaks_spectrogram_raw=spectrogram_from_peaks_raw(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=resolved_peak_scan,
        ),
        peaks_table=peaks_table,
        phase_segments=series.phase_segments_out,
        phase_boundaries=series.phase_boundaries,
    )
