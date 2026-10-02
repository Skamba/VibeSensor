"""Generic math and statistical helpers for diagnostics."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import isfinite, sqrt


def _mean(values: Sequence[float]) -> float:
    """Arithmetic mean returning 0.0 for empty inputs."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _mean_or_none(values: Iterable[float]) -> float | None:
    items = tuple(values)
    if not items:
        return None
    return sum(float(value) for value in items) / len(items)


def _max_or_none(values: Iterable[float]) -> float | None:
    items = tuple(values)
    if not items:
        return None
    return max(float(value) for value in items)


def _min_or_none(values: Iterable[float]) -> float | None:
    items = tuple(values)
    if not items:
        return None
    return min(float(value) for value in items)


def _stddev_or_none(values: Iterable[float]) -> float | None:
    items = tuple(values)
    if not items:
        return None
    mean_value = _mean_or_none(items)
    if mean_value is None:
        return None
    variance = sum((float(value) - mean_value) ** 2 for value in items) / len(items)
    return sqrt(max(0.0, variance))


def _ratio_or_zero(numerator: int | float, denominator: int | float) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _corr_abs(x_vals: Sequence[float], y_vals: Sequence[float]) -> float | None:
    """Absolute Pearson correlation for equal-length numeric sequences."""
    if len(x_vals) != len(y_vals) or len(x_vals) < 3:
        return None
    n = len(x_vals)
    mx = sum(x_vals) / n
    my = sum(y_vals) / n
    cov = 0.0
    sx_sq = 0.0
    sy_sq = 0.0
    for x, y in zip(x_vals, y_vals, strict=False):
        dx = x - mx
        dy = y - my
        cov += dx * dy
        sx_sq += dx * dx
        sy_sq += dy * dy
    sx = sqrt(sx_sq)
    sy = sqrt(sy_sq)
    if sx <= 1e-9 or sy <= 1e-9:
        return None
    result = abs(cov / (sx * sy))
    return result if isfinite(result) else None


def _corr_abs_clamped(x: Sequence[float], y: Sequence[float]) -> float | None:
    """Absolute Pearson correlation, clamped to [0, 1]."""
    raw = _corr_abs(x, y)
    if raw is None:
        return None
    return max(0.0, min(1.0, raw))


def _weighted_percentile(
    pairs: Sequence[tuple[float, float]],
    q: float,
) -> float | None:
    """Return the *q*-th weighted percentile from *(value, weight)* pairs."""
    if not pairs:
        return None
    q_clamped = max(0.0, min(1.0, q))
    filtered = [(value, weight) for value, weight in pairs if weight > 0]
    if not filtered:
        return None
    ordered = sorted(filtered)
    total_weight = sum(weight for _, weight in ordered)
    if total_weight <= 0:
        return None
    threshold = q_clamped * total_weight
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return ordered[-1][0]
