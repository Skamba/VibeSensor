"""Typed strength-metrics extraction for live sample construction."""

from __future__ import annotations

import math

from vibesensor.domain.strength_metrics import StrengthMetrics
from vibesensor.dsp.constants import PEAK_SEPARATION_HZ
from vibesensor.dsp.fft_analysis import AXES, axis_peaks_from_spectrum
from vibesensor.live.payload_types import AxisPeak, ClientMetrics
from vibesensor.recording.strength_metrics_codec import strength_metrics_from_mapping

__all__ = ["dominant_axis_from_metrics", "dominant_hz_from_strength", "extract_strength_data"]

_AXIS_DOMINANCE_REL_TOL = 0.05


def extract_strength_data(metrics: ClientMetrics) -> StrengthMetrics:
    """Extract strength metrics and top peaks from client metrics."""

    combined_metrics = metrics.get("combined")
    raw_strength_metrics = (
        combined_metrics.get("strength_metrics") if combined_metrics is not None else None
    )
    return strength_metrics_from_mapping(raw_strength_metrics)


def dominant_hz_from_strength(strength_metrics: StrengthMetrics) -> float | None:
    """Return the frequency of the strongest peak, or ``None``."""

    return strength_metrics.dominant_hz


def dominant_axis_from_metrics(
    metrics: ClientMetrics,
    *,
    dominant_hz: float | None,
) -> str:
    """Return the real dominant axis, or non-directional/unavailable semantics.

    ``""`` means the input carries no usable per-axis evidence.
    ``"combined"`` means the dominant combined peak is real, but no single axis
    clearly dominates it.
    """

    if dominant_hz is None or not math.isfinite(dominant_hz):
        return ""
    matches: list[tuple[float, float, str]] = []
    for axis in AXES:
        spectrum = metrics.get(axis)
        if spectrum is None:
            continue
        peaks = axis_peaks_from_spectrum(freq_slice=spectrum["freq"], amp_slice=spectrum["amp"])
        best_match = _best_axis_peak_match(peaks, dominant_hz)
        if best_match is None:
            continue
        matches.append((best_match[0], best_match[1], axis))
    if not matches:
        return ""

    matches.sort(key=lambda item: (-item[0], item[1], item[2]))
    if len(matches) == 1:
        return matches[0][2]

    best_amp, _best_delta, best_axis = matches[0]
    second_amp = matches[1][0]
    if math.isclose(best_amp, second_amp, rel_tol=_AXIS_DOMINANCE_REL_TOL, abs_tol=1e-9):
        return "combined"
    return best_axis


def _best_axis_peak_match(peaks: list[AxisPeak], dominant_hz: float) -> tuple[float, float] | None:
    best: tuple[float, float] | None = None
    for peak in peaks:
        amp = peak["amp"]
        if not math.isfinite(amp):
            continue
        delta_hz = abs(peak["hz"] - dominant_hz)
        if delta_hz > PEAK_SEPARATION_HZ:
            continue
        candidate = (amp, delta_hz)
        if (
            best is None
            or candidate[0] > best[0]
            or (
                math.isclose(candidate[0], best[0], rel_tol=1e-9, abs_tol=1e-12)
                and candidate[1] < best[1]
            )
        ):
            best = candidate
    return best
