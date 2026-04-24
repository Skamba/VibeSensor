"""Typed strength-metrics extraction for live sample construction."""

from __future__ import annotations

import math
from collections.abc import Mapping

from vibesensor.domain.strength_metrics import StrengthMetrics
from vibesensor.shared.boundaries.codecs import strength_metrics_from_mapping
from vibesensor.shared.constants.dsp import PEAK_SEPARATION_HZ
from vibesensor.shared.types.payload_types import ClientMetrics

__all__ = ["dominant_axis_from_metrics", "dominant_hz_from_strength", "extract_strength_data"]

_AXES: tuple[str, str, str] = ("x", "y", "z")
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
    for axis in _AXES:
        axis_metrics = metrics.get(axis)
        if not isinstance(axis_metrics, Mapping):
            continue
        best_match = _best_axis_peak_match(axis_metrics.get("peaks"), dominant_hz)
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


def _best_axis_peak_match(peaks: object, dominant_hz: float) -> tuple[float, float] | None:
    if not isinstance(peaks, list):
        return None
    best: tuple[float, float] | None = None
    for peak in peaks:
        if not isinstance(peak, Mapping):
            continue
        raw_hz = peak.get("hz")
        raw_amp = peak.get("amp")
        if not isinstance(raw_hz, int | float) or not isinstance(raw_amp, int | float):
            continue
        hz = float(raw_hz)
        amp = float(raw_amp)
        if not math.isfinite(hz) or not math.isfinite(amp) or amp <= 0.0:
            continue
        delta_hz = abs(hz - dominant_hz)
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
