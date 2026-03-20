"""Pure computation helpers for run statistics.

Side-effect-free, independently testable functions extracted from
``summary_builder.py``: acceleration statistics, data quality metrics,
run timing, speed/phase preparation, and noise baseline conversion.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta

from vibesensor.domain.snapshots import SpeedProfileSummary
from vibesensor.shared.constants import (
    MEMS_NOISE_FLOOR_G,
    SPEED_COVERAGE_MIN_PCT,
    SPEED_MIN_POINTS,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.run_context import order_reference_context_complete
from vibesensor.shared.time_utils import parse_iso8601
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.strength_bands import bucket_for_strength
from vibesensor.use_cases.diagnostics._types import AccelStatistics, Sample
from vibesensor.use_cases.diagnostics.helpers import (
    _primary_vibration_strength_db,
    _sensor_limit_g,
    counter_delta,
)
from vibesensor.use_cases.diagnostics.math_utils import (
    _mean_variance,
    _outlier_summary,
    _percent_missing,
)
from vibesensor.use_cases.diagnostics.phase_segmentation import (
    DrivingPhase,
    PhaseSegment,
    segment_run_phases,
)
from vibesensor.use_cases.diagnostics.speed_profile_helpers import _speed_stats
from vibesensor.vibration_strength import compute_db

# ── Constants ────────────────────────────────────────────────────────────

# Fraction of sensor ADC limit above which a sample is considered clipping.
# 2% headroom accounts for quantization effects near the ADC rail.
_SATURATION_FRACTION = 0.98

_STRENGTH_LABEL_KEY_BY_BUCKET: dict[str, str] = {
    "l0": "negligible",
    "l1": "light",
    "l2": "moderate",
    "l3": "strong",
    "l4": "very_strong",
    "l5": "very_strong",
}


# ── Strength helpers ─────────────────────────────────────────────────────


def _strength_band_key(db_value: float | None) -> str | None:
    if db_value is None or not math.isfinite(db_value):
        return None
    return _STRENGTH_LABEL_KEY_BY_BUCKET.get(bucket_for_strength(db_value), "very_strong")


def _json_outlier_summary(values: list[float]) -> JsonObject:
    """Convert the local outlier summary helper output into the shared JSON shape."""
    summary = _outlier_summary(values)
    return {
        "count": summary["count"],
        "outlier_count": summary["outlier_count"],
        "outlier_pct": summary["outlier_pct"],
        "lower_bound": summary["lower_bound"],
        "upper_bound": summary["upper_bound"],
    }


# ── Acceleration statistics ──────────────────────────────────────────────


def compute_accel_statistics(
    samples: list[Sample],
    sensor_model: object,
) -> AccelStatistics:
    """Compute per-axis values, aggregate amplitude metrics, and saturation counts."""
    sensor_limit = _sensor_limit_g(sensor_model)
    sat_threshold = sensor_limit * _SATURATION_FRACTION if sensor_limit is not None else None

    accel_x_vals: list[float] = []
    accel_y_vals: list[float] = []
    accel_z_vals: list[float] = []
    accel_mag_vals: list[float] = []
    amp_metric_values: list[float] = []
    sat_count = 0

    for sample in samples:
        x = _as_float(sample.get("accel_x_g"))
        y = _as_float(sample.get("accel_y_g"))
        z = _as_float(sample.get("accel_z_g"))
        if x is not None:
            accel_x_vals.append(x)
        if y is not None:
            accel_y_vals.append(y)
        if z is not None:
            accel_z_vals.append(z)
        if x is not None and y is not None and z is not None:
            accel_mag_vals.append(math.sqrt(x * x + y * y + z * z))
        if sat_threshold is not None and any(
            axis_val is not None and abs(axis_val) >= sat_threshold for axis_val in (x, y, z)
        ):
            sat_count += 1
        amp = _primary_vibration_strength_db(sample)
        if amp is not None:
            amp_metric_values.append(amp)

    x_mean, x_var = _mean_variance(accel_x_vals)
    y_mean, y_var = _mean_variance(accel_y_vals)
    z_mean, z_var = _mean_variance(accel_z_vals)
    return {
        "accel_x_vals": accel_x_vals,
        "accel_y_vals": accel_y_vals,
        "accel_z_vals": accel_z_vals,
        "accel_mag_vals": accel_mag_vals,
        "amp_metric_values": amp_metric_values,
        "sat_count": sat_count,
        "sensor_limit": sensor_limit,
        "x_mean": x_mean,
        "x_var": x_var,
        "y_mean": y_mean,
        "y_var": y_var,
        "z_mean": z_mean,
        "z_var": z_var,
    }


# ── Frame integrity ──────────────────────────────────────────────────────


def compute_frame_integrity_counts(samples: list[Sample]) -> tuple[int, int]:
    """Compute ``(total_dropped, total_overflow)`` across all client sensors."""
    per_client_dropped: dict[str, list[float]] = defaultdict(list)
    per_client_overflow: dict[str, list[float]] = defaultdict(list)
    for sample in samples:
        client_id = str(sample.get("client_id") or "")
        if not client_id:
            continue
        dropped = _as_float(sample.get("frames_dropped_total"))
        if dropped is not None:
            per_client_dropped[client_id].append(dropped)
        overflow = _as_float(sample.get("queue_overflow_drops"))
        if overflow is not None:
            per_client_overflow[client_id].append(overflow)
    total_dropped = sum(counter_delta(values) for values in per_client_dropped.values())
    total_overflow = sum(counter_delta(values) for values in per_client_overflow.values())
    return total_dropped, total_overflow


# ── Reference completeness ───────────────────────────────────────────────


def compute_reference_completeness(metadata: JsonObject) -> bool:
    """Return True when enough reference metadata is present for order analysis."""
    return bool(order_reference_context_complete(metadata))


# ── Data quality ─────────────────────────────────────────────────────────


def build_data_quality_dict(
    samples: list[Sample],
    speed_values: list[float],
    speed_stats: SpeedProfileSummary,
    speed_non_null_pct: float,
    accel_stats: AccelStatistics,
    amp_metric_values: list[float],
) -> JsonObject:
    """Build the ``data_quality`` sub-dict for the run summary."""
    return {
        "required_missing_pct": {
            "t_s": _percent_missing(samples, "t_s"),
            "speed_kmh": _percent_missing(samples, "speed_kmh"),
            "accel_x": _percent_missing(samples, "accel_x_g"),
            "accel_y": _percent_missing(samples, "accel_y_g"),
            "accel_z": _percent_missing(samples, "accel_z_g"),
        },
        "speed_coverage": {
            "non_null_pct": speed_non_null_pct,
            "min_kmh": min(speed_values) if speed_values else None,
            "max_kmh": max(speed_values) if speed_values else None,
            "mean_kmh": speed_stats.mean_kmh,
            "stddev_kmh": speed_stats.stddev_kmh,
            "count_non_null": len(speed_values),
        },
        "accel_sanity": {
            "x_mean": accel_stats["x_mean"],
            "x_variance": accel_stats["x_var"],
            "y_mean": accel_stats["y_mean"],
            "y_variance": accel_stats["y_var"],
            "z_mean": accel_stats["z_mean"],
            "z_variance": accel_stats["z_var"],
            "sensor_limit": accel_stats["sensor_limit"],
            "saturation_count": accel_stats["sat_count"],
        },
        "outliers": {
            "accel_magnitude": _json_outlier_summary(accel_stats["accel_mag_vals"]),
            "amplitude_metric": _json_outlier_summary(amp_metric_values),
        },
    }


# ── Noise baseline ───────────────────────────────────────────────────────


def noise_baseline_db(run_noise_baseline_g: float | None) -> float | None:
    """Convert a run noise baseline amplitude in g to dB, or return None."""
    if run_noise_baseline_g is None:
        return None
    result: float = compute_db(
        max(MEMS_NOISE_FLOOR_G, run_noise_baseline_g),
        MEMS_NOISE_FLOOR_G,
    )
    return result


# ── Speed and phase preparation ──────────────────────────────────────────


def prepare_speed_and_phases(
    samples: list[Sample],
) -> tuple[list[float], SpeedProfileSummary, float, bool, list[DrivingPhase], list[PhaseSegment]]:
    """Compute speed stats and phase segmentation shared by multiple entry points."""
    speed_values = [
        speed
        for speed in (_as_float(sample.get("speed_kmh")) for sample in samples)
        if speed is not None and speed > 0
    ]
    speed_stats = _speed_stats(speed_values)
    speed_non_null_pct = (len(speed_values) / len(samples) * 100.0) if samples else 0.0
    speed_sufficient = (
        speed_non_null_pct >= SPEED_COVERAGE_MIN_PCT and len(speed_values) >= SPEED_MIN_POINTS
    )
    per_sample_phases, phase_segments = segment_run_phases(samples)
    return (
        speed_values,
        speed_stats,
        speed_non_null_pct,
        speed_sufficient,
        per_sample_phases,
        phase_segments,
    )


# ── Run timing ───────────────────────────────────────────────────────────


def compute_run_timing(
    metadata: JsonObject,
    samples: list[Sample],
    file_name: str,
) -> tuple[str, datetime | None, datetime | None, float]:
    """Extract run_id, start/end timestamps and duration from metadata+samples."""
    run_id = str(metadata.get("run_id") or f"run-{file_name}")
    start_ts = parse_iso8601(metadata.get("start_time_utc"))
    end_ts = parse_iso8601(metadata.get("end_time_utc"))

    if end_ts is None and samples:
        sample_max_t = max((_as_float(sample.get("t_s")) or 0.0) for sample in samples)
        if start_ts is not None:
            end_ts = start_ts + timedelta(seconds=sample_max_t)
    duration_s = 0.0
    if start_ts is not None and end_ts is not None:
        duration_s = max(0.0, (end_ts - start_ts).total_seconds())
    elif samples:
        duration_s = max((_as_float(sample.get("t_s")) or 0.0) for sample in samples)

    return run_id, start_ts, end_ts, duration_s
