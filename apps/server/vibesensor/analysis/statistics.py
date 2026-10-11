"""Pure computation helpers for run statistics.

Side-effect-free, independently testable functions extracted from
``run_analysis.py``: acceleration statistics, run timing, frame
integrity, and speed/phase preparation.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from vibesensor.analysis._counters import counter_delta
from vibesensor.analysis._sample_metrics import _sensor_limit_g
from vibesensor.analysis._types import AccelStatistics
from vibesensor.analysis.constants import SPEED_COVERAGE_MIN_PCT, SPEED_MIN_POINTS
from vibesensor.analysis.phase_segmentation import (
    DrivingPhase,
    PhaseSegment,
    segment_run_phases,
)
from vibesensor.analysis.speed_profile_helpers import _speed_stats
from vibesensor.common.time_utils import parse_iso8601
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.dsp.statistics_utils import _mean_variance
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.sample_columns import SampleColumns, rows_of_groups

# ── Constants ────────────────────────────────────────────────────────────

# Fraction of sensor ADC limit above which a sample is considered clipping.
# 2% headroom accounts for quantization effects near the ADC rail.
_SATURATION_FRACTION = 0.98

# ── Acceleration statistics ──────────────────────────────────────────────


def compute_accel_statistics(
    samples: SampleColumns,
    sensor_model: object,
) -> AccelStatistics:
    """Compute per-axis values, aggregate amplitude metrics, and saturation counts."""
    sensor_limit = _sensor_limit_g(sensor_model)
    sat_threshold = sensor_limit * _SATURATION_FRACTION if sensor_limit is not None else None

    x, y, z = samples.accel_x_g, samples.accel_y_g, samples.accel_z_g
    accel_x_vals: list[float] = x[~np.isnan(x)].tolist()
    accel_y_vals: list[float] = y[~np.isnan(y)].tolist()
    accel_z_vals: list[float] = z[~np.isnan(z)].tolist()
    # NaN where an axis is missing, as each step is in Python.
    magnitudes = np.sqrt(x * x + y * y + z * z)
    accel_mag_vals: list[float] = magnitudes[~np.isnan(magnitudes)].tolist()
    sat_count = (
        int(
            np.count_nonzero(
                (np.abs(x) >= sat_threshold)
                | (np.abs(y) >= sat_threshold)
                | (np.abs(z) >= sat_threshold)
            )
        )
        if sat_threshold is not None
        else 0
    )
    strength_db = samples.vibration_strength_db
    amp_metric_values: list[float] = strength_db[~np.isnan(strength_db)].tolist()

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


def compute_frame_integrity_counts(samples: SampleColumns) -> tuple[int, int]:
    """Compute ``(total_dropped, total_overflow)`` across all client sensors."""
    client_of, clients = samples.clients()
    dropped = samples.frames_dropped_total
    overflow = samples.queue_overflow_drops
    total_dropped = 0
    total_overflow = 0
    for client_id, rows in zip(clients, rows_of_groups(client_of, len(clients)), strict=True):
        if client_id:
            total_dropped += counter_delta(dropped[rows].tolist())
            total_overflow += counter_delta(overflow[rows].tolist())
    return total_dropped, total_overflow


# ── Speed and phase preparation ──────────────────────────────────────────


def prepare_speed_and_phases(
    samples: SampleColumns,
) -> tuple[list[float], SpeedProfileSummary, float, bool, list[DrivingPhase], list[PhaseSegment]]:
    """Compute speed stats and phase segmentation shared by multiple entry points."""
    speed_values: list[float] = samples.speed_kmh[samples.speed_kmh > 0].tolist()
    speed_stats = _speed_stats(speed_values)
    speed_non_null_pct = (len(speed_values) / len(samples) * 100.0) if len(samples) else 0.0
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
    context: RunMetadata,
    samples: SampleColumns,
) -> tuple[str, datetime | None, datetime | None, float]:
    """Extract run_id, start/end timestamps and duration from context+samples."""
    run_id = context.run_id
    start_ts = parse_iso8601(context.start_time_utc)
    end_ts = parse_iso8601(context.end_time_utc)
    # The latest sample time, a sample without one (or at -0.0) at 0.0.
    sample_max_t = (
        float(np.max(np.where(np.isnan(samples.t_s) | (samples.t_s == 0.0), 0.0, samples.t_s)))
        if len(samples)
        else 0.0
    )

    if end_ts is None and len(samples) and start_ts is not None:
        end_ts = start_ts + timedelta(seconds=sample_max_t)
    duration_s = 0.0
    if start_ts is not None and end_ts is not None:
        duration_s = max(0.0, (end_ts - start_ts).total_seconds())
    elif len(samples):
        duration_s = sample_max_t

    return run_id, start_ts, end_ts, duration_s
