"""Focused helpers for building ``data_quality`` summary payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from vibesensor.common.json_utils import as_float_or_none as _as_float
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.dsp.statistics_utils import _outlier_summary
from vibesensor.recording.sensor_frame import SensorFrame
from vibesensor.summary.data_quality_contracts import (
    DataQualityResponse as DataQualityPayload,
)
from vibesensor.summary.data_quality_contracts import (
    OutlierSummaryResponse as OutlierSummaryPayload,
)

AccelStatisticsLike = Mapping[str, object]


def _float_list(stats: AccelStatisticsLike, key: str) -> list[float]:
    value = stats.get(key)
    if not isinstance(value, list):
        return []
    return [float(item) for item in value if isinstance(item, (int, float))]


def _int_value(stats: AccelStatisticsLike, key: str) -> int | None:
    value = stats.get(key)
    return int(value) if isinstance(value, (int, float)) else None


def _percent_missing(samples: Sequence[SensorFrame], field: str) -> float:
    """Return the percentage of samples without a value for *field*."""
    if not samples:
        return 100.0
    missing = sum(1 for sample in samples if getattr(sample, field) is None)
    return (missing / len(samples)) * 100.0


def _outlier_summary_payload(values: list[float]) -> OutlierSummaryPayload:
    summary = _outlier_summary(values)
    return {
        "count": summary["count"],
        "outlier_count": summary["outlier_count"],
        "outlier_pct": summary["outlier_pct"],
        "lower_bound": summary["lower_bound"],
        "upper_bound": summary["upper_bound"],
    }


def build_data_quality_dict(
    samples: Sequence[SensorFrame],
    speed_values: list[float],
    speed_stats: SpeedProfileSummary,
    speed_non_null_pct: float,
    accel_stats: AccelStatisticsLike,
    amp_metric_values: list[float],
) -> DataQualityPayload:
    """Build the ``data_quality`` sub-dict for the persisted run summary."""

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
            "x_mean": _as_float(accel_stats.get("x_mean")),
            "x_variance": _as_float(accel_stats.get("x_var")),
            "y_mean": _as_float(accel_stats.get("y_mean")),
            "y_variance": _as_float(accel_stats.get("y_var")),
            "z_mean": _as_float(accel_stats.get("z_mean")),
            "z_variance": _as_float(accel_stats.get("z_var")),
            "sensor_limit": _as_float(accel_stats.get("sensor_limit")),
            "saturation_count": _int_value(accel_stats, "sat_count"),
        },
        "outliers": {
            "accel_magnitude": _outlier_summary_payload(_float_list(accel_stats, "accel_mag_vals")),
            "amplitude_metric": _outlier_summary_payload(amp_metric_values),
        },
    }
