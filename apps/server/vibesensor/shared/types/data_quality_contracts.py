"""Data-quality diagnostic contracts shared by boundary and HTTP layers.

Extracted from ``history_analysis_contracts`` so data-quality diagnostics can
evolve independently of finding, summary, and warning wrappers.
"""

from __future__ import annotations

from typing import TypedDict

__all__ = [
    "DataQualityAccelSanityResponse",
    "DataQualityOutliersResponse",
    "DataQualityRequiredMissingPctResponse",
    "DataQualityResponse",
    "DataQualitySpeedCoverageResponse",
    "OutlierSummaryResponse",
]


class OutlierSummaryResponse(TypedDict):
    """Response body for an outlier-summary bucket."""

    count: int
    outlier_count: int
    outlier_pct: float
    lower_bound: float | None
    upper_bound: float | None


class DataQualityRequiredMissingPctResponse(TypedDict):
    """Response body for required-field missing percentages."""

    t_s: float
    speed_kmh: float
    accel_x: float
    accel_y: float
    accel_z: float


class DataQualitySpeedCoverageResponse(TypedDict):
    """Response body for summarized speed-coverage statistics."""

    non_null_pct: float
    min_kmh: float | None
    max_kmh: float | None
    mean_kmh: float | None
    stddev_kmh: float | None
    count_non_null: int


class DataQualityAccelSanityResponse(TypedDict):
    """Response body for acceleration sanity diagnostics."""

    x_mean: float | None
    x_variance: float | None
    y_mean: float | None
    y_variance: float | None
    z_mean: float | None
    z_variance: float | None
    sensor_limit: float | None
    saturation_count: int | None


class DataQualityOutliersResponse(TypedDict):
    """Response body for grouped outlier summaries."""

    accel_magnitude: OutlierSummaryResponse
    amplitude_metric: OutlierSummaryResponse


class DataQualityResponse(TypedDict):
    """Response body for run-level data-quality diagnostics."""

    required_missing_pct: DataQualityRequiredMissingPctResponse
    speed_coverage: DataQualitySpeedCoverageResponse
    accel_sanity: DataQualityAccelSanityResponse
    outliers: DataQualityOutliersResponse
