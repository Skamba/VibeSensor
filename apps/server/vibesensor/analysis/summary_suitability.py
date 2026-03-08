"""Run-suitability and acceleration-statistics helpers for run summaries."""

from __future__ import annotations

import math
from collections import defaultdict

from ..analysis_settings import tire_circumference_m_from_spec
from ..runlog import as_float_or_none as _as_float
from ._types import (
    AccelStatistics,
    JsonObject,
    MetadataDict,
    RunSuitabilityCheck,
    Sample,
    SpeedStats,
)
from .helpers import (
    _mean_variance,
    _outlier_summary,
    _percent_missing,
    _primary_vibration_strength_db,
    _sensor_limit_g,
    counter_delta,
)
from .order_analysis import _i18n_ref

# Fraction of sensor ADC limit above which a sample is considered clipping.
# 2% headroom accounts for quantization effects near the ADC rail.
_SATURATION_FRACTION = 0.98


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


def build_run_suitability_checks(
    *,
    steady_speed: bool,
    speed_sufficient: bool,
    sensor_ids: set[str],
    reference_complete: bool,
    sat_count: int,
    samples: list[Sample],
) -> list[RunSuitabilityCheck]:
    """Construct the language-neutral run-suitability checklist."""
    sensor_count_sufficient = len(sensor_ids) >= 3
    speed_variation_ok = speed_sufficient and not steady_speed
    run_suitability: list[RunSuitabilityCheck] = [
        {
            "check": "SUITABILITY_CHECK_SPEED_VARIATION",
            "check_key": "SUITABILITY_CHECK_SPEED_VARIATION",
            "state": "pass" if speed_variation_ok else "warn",
            "explanation": (
                _i18n_ref("SUITABILITY_SPEED_VARIATION_PASS")
                if speed_variation_ok
                else _i18n_ref("SUITABILITY_SPEED_VARIATION_WARN")
            ),
        },
        {
            "check": "SUITABILITY_CHECK_SENSOR_COVERAGE",
            "check_key": "SUITABILITY_CHECK_SENSOR_COVERAGE",
            "state": "pass" if sensor_count_sufficient else "warn",
            "explanation": (
                _i18n_ref("SUITABILITY_SENSOR_COVERAGE_PASS")
                if sensor_count_sufficient
                else _i18n_ref("SUITABILITY_SENSOR_COVERAGE_WARN")
            ),
        },
        {
            "check": "SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
            "check_key": "SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
            "state": "pass" if reference_complete else "warn",
            "explanation": (
                _i18n_ref("SUITABILITY_REFERENCE_COMPLETENESS_PASS")
                if reference_complete
                else _i18n_ref("SUITABILITY_REFERENCE_COMPLETENESS_WARN")
            ),
        },
        {
            "check": "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
            "check_key": "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
            "state": "pass" if sat_count == 0 else "warn",
            "explanation": (
                _i18n_ref("SUITABILITY_SATURATION_PASS")
                if sat_count == 0
                else _i18n_ref("SUITABILITY_SATURATION_WARN", sat_count=sat_count)
            ),
        },
    ]
    total_dropped, total_overflow = compute_frame_integrity_counts(samples)
    frame_issues = total_dropped + total_overflow
    run_suitability.append(
        {
            "check": "SUITABILITY_CHECK_FRAME_INTEGRITY",
            "check_key": "SUITABILITY_CHECK_FRAME_INTEGRITY",
            "state": "pass" if frame_issues == 0 else "warn",
            "explanation": (
                _i18n_ref("SUITABILITY_FRAME_INTEGRITY_PASS")
                if frame_issues == 0
                else _i18n_ref(
                    "SUITABILITY_FRAME_INTEGRITY_WARN",
                    total_dropped=total_dropped,
                    total_overflow=total_overflow,
                )
            ),
        }
    )
    return run_suitability


def compute_reference_completeness(metadata: MetadataDict) -> bool:
    """Return True when enough reference metadata is present for order analysis."""
    return bool(
        _as_float(metadata.get("raw_sample_rate_hz"))
        and (
            _as_float(metadata.get("tire_circumference_m"))
            or tire_circumference_m_from_spec(
                _as_float(metadata.get("tire_width_mm")),
                _as_float(metadata.get("tire_aspect_pct")),
                _as_float(metadata.get("rim_in")),
            )
        )
        and (
            _as_float(metadata.get("engine_rpm"))
            or (
                _as_float(metadata.get("final_drive_ratio"))
                and _as_float(metadata.get("current_gear_ratio"))
            )
        )
    )


def build_data_quality_dict(
    samples: list[Sample],
    speed_values: list[float],
    speed_stats: SpeedStats,
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
            "mean_kmh": speed_stats.get("mean_kmh"),
            "stddev_kmh": speed_stats.get("stddev_kmh"),
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
