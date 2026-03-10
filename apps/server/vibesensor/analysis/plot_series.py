"""Series builders used by the plot-data orchestration layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from vibesensor.core.vibration_strength import percentile

from ..domain_models import as_float_or_none as _as_float
from ._types import Sample, SummaryData
from .helpers import _primary_vibration_strength_db
from .phase_segmentation import DrivingPhase, PhaseSegment


class MatchedAmpVsSpeedSeries(TypedDict):
    """Per-finding matched-point series for amp-vs-speed."""

    label: str
    points: list[tuple[float, float]]


class FreqVsSpeedByFindingSeries(TypedDict):
    """Per-finding frequency-vs-speed series with predicted overlay."""

    label: str
    matched: list[tuple[float, float]]
    predicted: list[tuple[float, float]]


class AmpVsPhaseRow(TypedDict):
    """A single phase-grouped vibration row."""

    phase: str
    count: int
    mean_vib_db: float
    max_vib_db: float | None
    mean_speed_kmh: float | None


class PhaseSegmentOut(TypedDict):
    """Serialised driving-phase segment for plot consumers."""

    phase: str
    start_t_s: float | None
    end_t_s: float | None


class PhaseBoundary(TypedDict):
    """Phase boundary marker for plot overlay."""

    phase: str
    t_s: float | None
    end_t_s: float | None


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
    summary: SummaryData,
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
    summary: SummaryData,
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


def build_amp_vs_phase(summary: SummaryData) -> list[AmpVsPhaseRow]:
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
