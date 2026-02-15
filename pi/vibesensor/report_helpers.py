from __future__ import annotations

from collections import defaultdict
from math import ceil, floor, sqrt
from statistics import mean
from typing import Any

from .analysis_settings import tire_circumference_m_from_spec

SPEED_BIN_WIDTH_KMH = 10


def as_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def percent_missing(samples: list[dict[str, Any]], key: str) -> float:
    if not samples:
        return 100.0
    missing = sum(1 for sample in samples if sample.get(key) in (None, ""))
    return (missing / len(samples)) * 100.0


def mean_variance(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    m = mean(values)
    var = sum((v - m) ** 2 for v in values) / len(values)
    return m, var


def percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = max(0.0, min(1.0, q)) * (len(sorted_values) - 1)
    lo = floor(pos)
    hi = ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] + ((sorted_values[hi] - sorted_values[lo]) * frac)


def outlier_summary(values: list[float]) -> dict[str, object]:
    if not values:
        return {
            "count": 0,
            "outlier_count": 0,
            "outlier_pct": 0.0,
            "lower_bound": None,
            "upper_bound": None,
        }
    sorted_vals = sorted(values)
    q1 = percentile(sorted_vals, 0.25)
    q3 = percentile(sorted_vals, 0.75)
    iqr = max(0.0, q3 - q1)
    low = q1 - (1.5 * iqr)
    high = q3 + (1.5 * iqr)
    outliers = [v for v in sorted_vals if v < low or v > high]
    return {
        "count": len(sorted_vals),
        "outlier_count": len(outliers),
        "outlier_pct": (len(outliers) / len(sorted_vals)) * 100.0,
        "lower_bound": low,
        "upper_bound": high,
    }


def speed_bin_label(kmh: float) -> str:
    low = int(kmh // SPEED_BIN_WIDTH_KMH) * SPEED_BIN_WIDTH_KMH
    high = low + SPEED_BIN_WIDTH_KMH
    return f"{low}-{high} km/h"


def speed_bin_sort_key(label: str) -> int:
    head = label.split(" ", 1)[0]
    low_text = head.split("-", 1)[0]
    try:
        return int(low_text)
    except ValueError:
        return 0


def sensor_limit_g(sensor_model: object) -> float | None:
    if not isinstance(sensor_model, str):
        return None
    model = sensor_model.lower()
    if "adxl345" in model:
        return 16.0
    return None


def tire_reference_from_metadata(metadata: dict[str, Any]) -> tuple[float | None, str | None]:
    direct = as_float(metadata.get("tire_circumference_m"))
    if direct is not None and direct > 0:
        return direct, "metadata.tire_circumference_m"

    derived = tire_circumference_m_from_spec(
        as_float(metadata.get("tire_width_mm")),
        as_float(metadata.get("tire_aspect_pct")),
        as_float(metadata.get("rim_in")),
    )
    if derived is not None and derived > 0:
        return derived, "derived_from_tire_dimensions"
    return None, None


def effective_engine_rpm(
    sample: dict[str, Any],
    metadata: dict[str, Any],
    tire_circumference_m: float | None,
) -> tuple[float | None, str]:
    measured = as_float(sample.get("engine_rpm"))
    if measured is not None and measured > 0:
        return measured, str(sample.get("engine_rpm_source") or "measured")

    estimated_in_sample = as_float(sample.get("engine_rpm_estimated"))
    if estimated_in_sample is not None and estimated_in_sample > 0:
        return estimated_in_sample, "estimated_from_speed_and_ratios"

    speed_kmh = as_float(sample.get("speed_kmh"))
    final_drive_ratio = as_float(sample.get("final_drive_ratio")) or as_float(
        metadata.get("final_drive_ratio")
    )
    gear_ratio = as_float(sample.get("gear")) or as_float(metadata.get("current_gear_ratio"))
    if (
        speed_kmh is None
        or speed_kmh <= 0
        or tire_circumference_m is None
        or tire_circumference_m <= 0
        or final_drive_ratio is None
        or final_drive_ratio <= 0
        or gear_ratio is None
        or gear_ratio <= 0
    ):
        return None, "missing"

    wheel_hz = (speed_kmh / 3.6) / tire_circumference_m
    return wheel_hz * final_drive_ratio * gear_ratio * 60.0, "estimated_from_speed_and_ratios"


def speed_breakdown(samples: list[dict[str, Any]]) -> list[dict[str, object]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    for sample in samples:
        speed = as_float(sample.get("speed_kmh"))
        if speed is None or speed <= 0:
            continue
        label = speed_bin_label(speed)
        counts[label] += 1
        amp = as_float(sample.get("accel_magnitude_rms_g"))
        if amp is None:
            amp = as_float(sample.get("dominant_peak_amp_g"))
        if amp is not None:
            grouped[label].append(amp)

    rows: list[dict[str, object]] = []
    for label in sorted(counts.keys(), key=speed_bin_sort_key):
        values = grouped.get(label, [])
        rows.append(
            {
                "speed_range": label,
                "count": counts[label],
                "mean_amplitude_g": mean(values) if values else None,
                "max_amplitude_g": max(values) if values else None,
            }
        )
    return rows


def corr_abs(x_vals: list[float], y_vals: list[float]) -> float | None:
    if len(x_vals) != len(y_vals) or len(x_vals) < 3:
        return None
    mx = mean(x_vals)
    my = mean(y_vals)
    cov = sum((x - mx) * (y - my) for x, y in zip(x_vals, y_vals, strict=False))
    sx = sqrt(sum((x - mx) ** 2 for x in x_vals))
    sy = sqrt(sum((y - my) ** 2 for y in y_vals))
    if sx <= 1e-9 or sy <= 1e-9:
        return None
    return abs(cov / (sx * sy))
