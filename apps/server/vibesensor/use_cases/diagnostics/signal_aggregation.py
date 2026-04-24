"""Speed and location aggregation helpers for diagnostic summaries."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from typing import TYPE_CHECKING

from vibesensor.domain import (
    LocationIntensitySummary,
    PhaseIntensitySummary,
    StrengthBucketDistribution,
    speed_band_sort_key,
    speed_bin_label,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.use_cases.diagnostics._counters import counter_delta
from vibesensor.use_cases.diagnostics._sample_metrics import _primary_vibration_strength_db
from vibesensor.use_cases.diagnostics._sensor_locations import (
    _location_label,
)
from vibesensor.use_cases.diagnostics._types import Sample
from vibesensor.use_cases.diagnostics._view_types import (
    PhaseSpeedBreakdownRowData,
    SpeedBreakdownRowData,
)
from vibesensor.use_cases.diagnostics.math_utils import _mean
from vibesensor.use_cases.diagnostics.phase_segmentation import DrivingPhase
from vibesensor.use_cases.diagnostics.speed_profile_helpers import _phase_to_str
from vibesensor.vibration_strength import percentile

if TYPE_CHECKING:
    from vibesensor.shared.types.run_schema import RunMetadata


def _counter_delta(counter_values: Sequence[tuple[float | None, float]]) -> int:
    """Sort timestamped counter pairs and delegate to shared helper."""
    min_counter_pairs = 2
    if len(counter_values) < min_counter_pairs:
        return 0
    ordered = sorted(
        counter_values,
        key=lambda pair: (
            pair[0] is None or not math.isfinite(pair[0]),
            pair[0] if (pair[0] is not None and math.isfinite(pair[0])) else 0.0,
        ),
    )
    return counter_delta([float(v) for _t, v in ordered])


_EMPTY_BUCKET_COUNTS: dict[str, int] = {f"l{idx}": 0 for idx in range(6)}


def _phase_speed_breakdown(
    samples: Sequence[Sample],
    per_sample_phases: Sequence[DrivingPhase],
) -> list[PhaseSpeedBreakdownRowData]:
    """Group vibration statistics by driving phase (temporal context)."""
    grouped_amp: dict[str, list[float]] = defaultdict(list)
    grouped_speeds: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)

    _as_float_local = _as_float
    _vib_db = _primary_vibration_strength_db
    n_phases = len(per_sample_phases)
    for idx, sample in enumerate(samples):
        phase = per_sample_phases[idx] if idx < n_phases else "unknown"
        phase_key = _phase_to_str(phase) or "unknown"
        counts[phase_key] += 1
        speed = sample.speed_kmh
        if speed is not None and speed > 0:
            grouped_speeds[phase_key].append(speed)
        amp = _vib_db(sample)
        if amp is not None:
            grouped_amp[phase_key].append(amp)

    phase_order = [p.value for p in DrivingPhase]
    phase_order_set = set(phase_order)
    rows: list[PhaseSpeedBreakdownRowData] = []
    for phase_key in [*phase_order, *sorted(k for k in counts if k not in phase_order_set)]:
        if phase_key not in counts:
            continue
        amp_vals = grouped_amp.get(phase_key, [])
        speed_vals = grouped_speeds.get(phase_key, [])
        rows.append(
            PhaseSpeedBreakdownRowData(
                phase=phase_key,
                count=counts[phase_key],
                mean_speed_kmh=_mean(speed_vals) if speed_vals else None,
                max_speed_kmh=max(speed_vals) if speed_vals else None,
                mean_vibration_strength_db=_mean(amp_vals) if amp_vals else None,
                max_vibration_strength_db=max(amp_vals) if amp_vals else None,
            ),
        )
    return rows


def _speed_breakdown(samples: Sequence[Sample]) -> list[SpeedBreakdownRowData]:
    grouped: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    _as_float_local = _as_float
    _vib_db = _primary_vibration_strength_db
    _bin_label = speed_bin_label
    for sample in samples:
        speed = sample.speed_kmh
        if speed is None or speed <= 0:
            continue
        label = _bin_label(speed)
        counts[label] += 1
        amp = _vib_db(sample)
        if amp is not None:
            grouped[label].append(amp)

    rows: list[SpeedBreakdownRowData] = []
    for label in sorted(counts, key=speed_band_sort_key):
        values = grouped.get(label, [])
        rows.append(
            SpeedBreakdownRowData(
                speed_range=label,
                count=counts[label],
                mean_vibration_strength_db=_mean(values) if values else None,
                max_vibration_strength_db=max(values) if values else None,
            ),
        )
    return rows


def _sensor_intensity_by_location(
    samples: Sequence[Sample],
    include_locations: Sequence[str] | set[str] | None = None,
    *,
    metadata: RunMetadata | None = None,
    lang: str = "en",
    connected_locations: Sequence[str] | set[str] | None = None,
    per_sample_phases: Sequence[DrivingPhase] | None = None,
) -> list[LocationIntensitySummary]:
    """Compute per-location vibration intensity statistics."""
    grouped_amp: dict[str, list[float]] = defaultdict(list)
    observed_sample_counts: dict[str, int] = defaultdict(int)
    usable_sample_counts: dict[str, int] = defaultdict(int)
    dropped_totals: dict[str, list[tuple[float | None, float]]] = defaultdict(list)
    overflow_totals: dict[str, list[tuple[float | None, float]]] = defaultdict(list)
    strength_bucket_counts: dict[str, dict[str, int]] = defaultdict(_EMPTY_BUCKET_COUNTS.copy)
    strength_bucket_totals: dict[str, int] = defaultdict(int)
    phase_amp: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    has_phases = per_sample_phases is not None and len(per_sample_phases) == len(samples)

    _as_float_local = _as_float
    _vib_db = _primary_vibration_strength_db
    _loc_label = _location_label
    for i, sample in enumerate(samples):
        location = _loc_label(sample, metadata=metadata, lang=lang)
        if not location:
            continue
        if include_locations is not None and location not in include_locations:
            continue
        observed_sample_counts[location] += 1
        amp = _vib_db(sample)
        if amp is not None:
            usable_sample_counts[location] += 1
            grouped_amp[location].append(amp)
            if has_phases and per_sample_phases is not None:
                phase_obj = per_sample_phases[i]
                phase_key = _phase_to_str(phase_obj) or "unknown"
                phase_amp[location][phase_key].append(amp)
        sample_t_s = sample.t_s
        dropped_total = sample.frames_dropped_total
        if dropped_total is not None:
            dropped_totals[location].append((sample_t_s, dropped_total))
        overflow_total = sample.queue_overflow_drops
        if overflow_total is not None:
            overflow_totals[location].append((sample_t_s, overflow_total))
        vibration_strength_db = sample.vibration_strength_db
        bucket = sample.strength_bucket
        if vibration_strength_db is None:
            continue
        if bucket:
            strength_bucket_counts[location][bucket] = (
                strength_bucket_counts[location].get(bucket, 0) + 1
            )
            strength_bucket_totals[location] += 1

    rows: list[LocationIntensitySummary] = []
    target_locations = set(observed_sample_counts.keys())
    if include_locations is not None:
        target_locations |= set(include_locations)
    max_observed_sample_count = max(
        (observed_sample_counts.get(location, 0) for location in target_locations),
        default=0,
    )
    max_usable_sample_count = max(
        (usable_sample_counts.get(location, 0) for location in target_locations),
        default=0,
    )

    for location in sorted(target_locations):
        values = grouped_amp.get(location, [])
        values_sorted = sorted(values)
        dropped_vals = dropped_totals.get(location, [])
        overflow_vals = overflow_totals.get(location, [])
        dropped_delta = _counter_delta(dropped_vals)
        overflow_delta = _counter_delta(overflow_vals)
        bucket_counts = strength_bucket_counts.get(location, _EMPTY_BUCKET_COUNTS)
        bucket_total = max(0, strength_bucket_totals.get(location, 0))
        bucket_distribution = StrengthBucketDistribution(
            total=bucket_total,
            counts=dict(bucket_counts),
            percent_time_l0=(bucket_counts.get("l0", 0) / bucket_total * 100.0)
            if bucket_total > 0
            else 0.0,
            percent_time_l1=(bucket_counts.get("l1", 0) / bucket_total * 100.0)
            if bucket_total > 0
            else 0.0,
            percent_time_l2=(bucket_counts.get("l2", 0) / bucket_total * 100.0)
            if bucket_total > 0
            else 0.0,
            percent_time_l3=(bucket_counts.get("l3", 0) / bucket_total * 100.0)
            if bucket_total > 0
            else 0.0,
            percent_time_l4=(bucket_counts.get("l4", 0) / bucket_total * 100.0)
            if bucket_total > 0
            else 0.0,
            percent_time_l5=(bucket_counts.get("l5", 0) / bucket_total * 100.0)
            if bucket_total > 0
            else 0.0,
        )
        sample_count = int(observed_sample_counts.get(location, 0))
        sample_coverage_ratio = (
            sample_count / max_observed_sample_count if max_observed_sample_count > 0 else 1.0
        )
        sample_coverage_warning = max_observed_sample_count >= 5 and sample_coverage_ratio <= 0.20
        usable_sample_count = int(usable_sample_counts.get(location, 0))
        usable_sample_coverage_ratio = (
            usable_sample_count / max_usable_sample_count if max_usable_sample_count > 0 else 0.0
        )
        usable_sample_coverage_warning = (
            max_usable_sample_count >= 5 and usable_sample_coverage_ratio <= 0.20
        )
        partial_coverage = bool(
            connected_locations is not None and location not in connected_locations,
        )
        location_phase_intensity: dict[str, PhaseIntensitySummary] | None = None
        if has_phases:
            loc_phases = phase_amp.get(location, {})
            location_phase_intensity = {
                phase_key: PhaseIntensitySummary(
                    count=len(phase_vals),
                    mean_intensity_db=_mean(phase_vals) if phase_vals else None,
                    max_intensity_db=max(phase_vals) if phase_vals else None,
                )
                for phase_key, phase_vals in loc_phases.items()
                if phase_vals
            }
        rows.append(
            LocationIntensitySummary(
                location=location,
                partial_coverage=partial_coverage,
                sample_count=sample_count,
                sample_coverage_ratio=sample_coverage_ratio,
                sample_coverage_warning=sample_coverage_warning,
                usable_sample_count=usable_sample_count,
                usable_sample_coverage_ratio=usable_sample_coverage_ratio,
                usable_sample_coverage_warning=usable_sample_coverage_warning,
                mean_intensity_db=_mean(values) if values else None,
                p50_intensity_db=percentile(values_sorted, 0.50) if values else None,
                p95_intensity_db=percentile(values_sorted, 0.95) if values else None,
                max_intensity_db=max(values) if values else None,
                dropped_frames_delta=dropped_delta,
                queue_overflow_drops_delta=overflow_delta,
                strength_bucket_distribution=bucket_distribution,
                phase_intensity=location_phase_intensity,
            ),
        )
    rows.sort(
        key=lambda row: (
            0 if row.partial_coverage else 1,
            0 if row.diagnostic_sample_coverage_warning else 1,
            row.p95_intensity_db if isinstance(row.p95_intensity_db, (int, float)) else 0.0,
            row.max_intensity_db if isinstance(row.max_intensity_db, (int, float)) else 0.0,
        ),
        reverse=True,
    )
    return rows
