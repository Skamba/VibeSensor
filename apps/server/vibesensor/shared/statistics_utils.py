"""Shared statistical helpers reused by diagnostics and boundary serializers."""

from __future__ import annotations

from typing import TypedDict, cast

from vibesensor.shared.types.json_types import JsonObject
from vibesensor.vibration_strength import percentile


def _percent_missing(samples: list[JsonObject], key: str) -> float:
    """Return the percentage of samples whose *key* is missing or blank."""
    if not samples:
        return 100.0
    missing = sum(1 for sample in samples if sample.get(key) in (None, ""))
    return (missing / len(samples)) * 100.0


def _mean_variance(values: list[float]) -> tuple[float | None, float | None]:
    """Return the mean and sample variance for *values*."""
    if not values:
        return None, None
    count = len(values)
    mean = sum(values) / count
    if count < 2:
        return mean, 0.0
    variance = sum((value - mean) ** 2 for value in values) / (count - 1)
    return mean, variance


class _OutlierSummary(TypedDict):
    """Return type of :func:`_outlier_summary`."""

    count: int
    outlier_count: int
    outlier_pct: float
    lower_bound: float | None
    upper_bound: float | None


def _outlier_summary(values: list[float]) -> _OutlierSummary:
    """Summarize Tukey-IQR outlier bounds and counts for *values*."""
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
    outlier_count = sum(1 for value in sorted_vals if value < low or value > high)
    return {
        "count": len(sorted_vals),
        "outlier_count": outlier_count,
        "outlier_pct": (outlier_count / len(sorted_vals)) * 100.0,
        "lower_bound": low,
        "upper_bound": high,
    }


def _json_outlier_summary(values: list[float]) -> JsonObject:
    """Convert the local outlier summary helper output into the shared JSON shape."""
    return cast(JsonObject, _outlier_summary(values))
