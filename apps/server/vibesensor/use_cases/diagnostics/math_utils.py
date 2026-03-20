"""Generic math and statistical helpers for diagnostics."""

from __future__ import annotations

from math import isfinite, sqrt
from typing import TypedDict

from vibesensor.use_cases.diagnostics._types import Sample
from vibesensor.vibration_strength import percentile


def _mean(values: list[float]) -> float:
    """Arithmetic mean returning 0.0 for empty inputs."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _percent_missing(samples: list[Sample], key: str) -> float:
    if not samples:
        return 100.0
    missing = sum(1 for sample in samples if sample.get(key) in (None, ""))
    return (missing / len(samples)) * 100.0


def _mean_variance(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    n = len(values)
    m = sum(values) / n
    if n < 2:
        return m, 0.0
    var = sum((v - m) ** 2 for v in values) / (n - 1)
    return m, var


class _OutlierSummary(TypedDict):
    """Return type of :func:`_outlier_summary`."""

    count: int
    outlier_count: int
    outlier_pct: float
    lower_bound: float | None
    upper_bound: float | None


def _outlier_summary(values: list[float]) -> _OutlierSummary:
    if not values:
        return {
            "count": 0,
            "outlier_count": 0,
            "outlier_pct": 0.0,
            "lower_bound": None,
            "upper_bound": None,
        }
    sorted_vals = sorted(values)
    q1 = float(percentile(sorted_vals, 0.25))
    q3 = float(percentile(sorted_vals, 0.75))
    iqr = max(0.0, q3 - q1)
    low = q1 - (1.5 * iqr)
    high = q3 + (1.5 * iqr)
    outlier_count = sum(1 for v in sorted_vals if v < low or v > high)
    return {
        "count": len(sorted_vals),
        "outlier_count": outlier_count,
        "outlier_pct": (outlier_count / len(sorted_vals)) * 100.0,
        "lower_bound": low,
        "upper_bound": high,
    }


def _corr_abs(x_vals: list[float], y_vals: list[float]) -> float | None:
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


def _corr_abs_clamped(x: list[float], y: list[float]) -> float | None:
    """Absolute Pearson correlation, clamped to [0, 1]."""
    raw = _corr_abs(x, y)
    if raw is None:
        return None
    return max(0.0, min(1.0, raw))


def _weighted_percentile(
    pairs: list[tuple[float, float]],
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
