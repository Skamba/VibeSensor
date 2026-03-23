"""Pure computation helpers for run statistics.

Side-effect-free, independently testable functions extracted from
``summary_builder.py``: acceleration statistics, run timing, frame
integrity, reference completeness, and speed/phase preparation.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta

from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.shared.constants.analysis import SPEED_COVERAGE_MIN_PCT, SPEED_MIN_POINTS
from vibesensor.shared.statistics_utils import _mean_variance
from vibesensor.shared.time_utils import parse_iso8601
from vibesensor.strength_bands import bucket_for_strength
from vibesensor.use_cases.diagnostics._context import DiagnosticsContext
from vibesensor.use_cases.diagnostics._counters import counter_delta
from vibesensor.use_cases.diagnostics._sample_metrics import (
    _primary_vibration_strength_db,
    _sensor_limit_g,
)
from vibesensor.use_cases.diagnostics._types import (
    AccelStatistics,
    AnalysisSampleInput,
    ensure_analysis_samples,
)
from vibesensor.use_cases.diagnostics.phase_segmentation import (
    DrivingPhase,
    PhaseSegment,
    segment_run_phases,
)
from vibesensor.use_cases.diagnostics.speed_profile_helpers import _speed_stats

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


# ── Acceleration statistics ──────────────────────────────────────────────


def compute_accel_statistics(
    samples: Sequence[AnalysisSampleInput],
    sensor_model: object,
) -> AccelStatistics:
    """Compute per-axis values, aggregate amplitude metrics, and saturation counts."""
    typed_samples = ensure_analysis_samples(samples)
    sensor_limit = _sensor_limit_g(sensor_model)
    sat_threshold = sensor_limit * _SATURATION_FRACTION if sensor_limit is not None else None

    accel_x_vals: list[float] = []
    accel_y_vals: list[float] = []
    accel_z_vals: list[float] = []
    accel_mag_vals: list[float] = []
    amp_metric_values: list[float] = []
    sat_count = 0

    for sample in typed_samples:
        x = sample.accel_x_g
        y = sample.accel_y_g
        z = sample.accel_z_g
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


def compute_frame_integrity_counts(samples: Sequence[AnalysisSampleInput]) -> tuple[int, int]:
    """Compute ``(total_dropped, total_overflow)`` across all client sensors."""
    typed_samples = ensure_analysis_samples(samples)
    per_client_dropped: dict[str, list[float]] = defaultdict(list)
    per_client_overflow: dict[str, list[float]] = defaultdict(list)
    for sample in typed_samples:
        client_id = sample.client_id
        if not client_id:
            continue
        dropped = sample.frames_dropped_total
        if dropped is not None:
            per_client_dropped[client_id].append(dropped)
        overflow = sample.queue_overflow_drops
        if overflow is not None:
            per_client_overflow[client_id].append(overflow)
    total_dropped = sum(counter_delta(values) for values in per_client_dropped.values())
    total_overflow = sum(counter_delta(values) for values in per_client_overflow.values())
    return total_dropped, total_overflow


# ── Reference completeness ───────────────────────────────────────────────


def compute_reference_completeness(context: DiagnosticsContext) -> bool:
    """Return True when enough reference metadata is present for order analysis."""
    return context.reference_complete


# ── Speed and phase preparation ──────────────────────────────────────────


def prepare_speed_and_phases(
    samples: Sequence[AnalysisSampleInput],
) -> tuple[list[float], SpeedProfileSummary, float, bool, list[DrivingPhase], list[PhaseSegment]]:
    """Compute speed stats and phase segmentation shared by multiple entry points."""
    typed_samples = ensure_analysis_samples(samples)
    speed_values = [
        speed
        for speed in (sample.speed_kmh for sample in typed_samples)
        if speed is not None and speed > 0
    ]
    speed_stats = _speed_stats(speed_values)
    speed_non_null_pct = (len(speed_values) / len(typed_samples) * 100.0) if typed_samples else 0.0
    speed_sufficient = (
        speed_non_null_pct >= SPEED_COVERAGE_MIN_PCT and len(speed_values) >= SPEED_MIN_POINTS
    )
    per_sample_phases, phase_segments = segment_run_phases(typed_samples)
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
    context: DiagnosticsContext,
    samples: Sequence[AnalysisSampleInput],
) -> tuple[str, datetime | None, datetime | None, float]:
    """Extract run_id, start/end timestamps and duration from context+samples."""
    typed_samples = ensure_analysis_samples(samples)
    run_id = context.run_id
    start_ts = parse_iso8601(context.start_time_utc)
    end_ts = parse_iso8601(context.end_time_utc)

    if end_ts is None and typed_samples:
        sample_max_t = max((sample.t_s or 0.0) for sample in typed_samples)
        if start_ts is not None:
            end_ts = start_ts + timedelta(seconds=sample_max_t)
    duration_s = 0.0
    if start_ts is not None and end_ts is not None:
        duration_s = max(0.0, (end_ts - start_ts).total_seconds())
    elif typed_samples:
        duration_s = max((sample.t_s or 0.0) for sample in typed_samples)

    return run_id, start_ts, end_ts, duration_s
