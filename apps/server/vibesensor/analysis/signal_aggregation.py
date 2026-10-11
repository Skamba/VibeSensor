"""Speed and location aggregation helpers for diagnostic summaries."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

from vibesensor.analysis._counters import counter_delta
from vibesensor.analysis._sensor_locations import location_labels
from vibesensor.analysis._view_types import (
    PhaseSpeedBreakdownRowData,
    SpeedBreakdownRowData,
)
from vibesensor.analysis.math_utils import _mean
from vibesensor.analysis.phase_segmentation import DrivingPhase
from vibesensor.analysis.speed_profile_helpers import _phase_to_str
from vibesensor.domain.finding import speed_band_sort_key
from vibesensor.domain.location_hotspot import (
    LocationIntensitySummary,
    PhaseIntensitySummary,
    StrengthBucketDistribution,
)
from vibesensor.dsp.vibration_strength import percentile
from vibesensor.recording.sample_columns import SampleColumns, optional_floats, rows_of_groups

if TYPE_CHECKING:
    from vibesensor.analysis.drive_table import DriveTable
    from vibesensor.recording.run_schema import RunMetadata


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
    samples: SampleColumns,
    per_sample_phases: Sequence[DrivingPhase],
) -> list[PhaseSpeedBreakdownRowData]:
    """Group vibration statistics by driving phase (temporal context)."""
    grouped_amp: dict[str, list[float]] = defaultdict(list)
    grouped_speeds: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)

    n_phases = len(per_sample_phases)
    for idx, (speed, amp) in enumerate(
        zip(samples.speed_kmh.tolist(), optional_floats(samples.vibration_strength_db), strict=True)
    ):
        phase = per_sample_phases[idx] if idx < n_phases else "unknown"
        phase_key = _phase_to_str(phase) or "unknown"
        counts[phase_key] += 1
        # A speed of NaN (none) is not over 0.
        if speed > 0:
            grouped_speeds[phase_key].append(speed)
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


def _speed_breakdown(samples: SampleColumns, table: DriveTable) -> list[SpeedBreakdownRowData]:
    """Vibration statistics by speed bin (*table* is *samples* as a drive table)."""
    strength_db = samples.vibration_strength_db
    bins = sorted(
        zip(table.speed_bins, rows_of_groups(table.speed_bin_of, len(table.speed_bins)), strict=True),
        key=lambda found: speed_band_sort_key(found[0]),
    )
    rows: list[SpeedBreakdownRowData] = []
    for label, bin_rows in bins:
        amps = strength_db[bin_rows]
        values: list[float] = amps[~np.isnan(amps)].tolist()
        rows.append(
            SpeedBreakdownRowData(
                speed_range=label,
                count=int(bin_rows.size),
                mean_vibration_strength_db=_mean(values) if values else None,
                max_vibration_strength_db=max(values) if values else None,
            ),
        )
    return rows


def _sensor_intensity_by_location(
    samples: SampleColumns,
    include_locations: Sequence[str] | set[str] | None = None,
    *,
    metadata: RunMetadata | None = None,
    connected_locations: Sequence[str] | set[str] | None = None,
    per_sample_phases: Sequence[DrivingPhase] | None = None,
) -> list[LocationIntensitySummary]:
    """Compute per-location vibration intensity statistics."""
    grouped_amp: dict[str, list[float]] = {}
    observed_sample_counts: dict[str, int] = {}
    usable_sample_counts: dict[str, int] = {}
    dropped_totals: dict[str, list[tuple[float | None, float]]] = {}
    overflow_totals: dict[str, list[tuple[float | None, float]]] = {}
    strength_bucket_counts: dict[str, dict[str, int]] = {}
    strength_bucket_totals: dict[str, int] = {}
    phase_amp: dict[str, dict[str, list[float]]] = {}
    has_phases = per_sample_phases is not None and len(per_sample_phases) == len(samples)
    phase_keys = (
        [_phase_to_str(phase) or "unknown" for phase in per_sample_phases]
        if has_phases and per_sample_phases is not None
        else []
    )

    label_of, labels = location_labels(samples, metadata)
    strength_db = samples.vibration_strength_db
    usable = ~np.isnan(strength_db)
    times = optional_floats(samples.t_s)
    for location, rows in zip(labels, rows_of_groups(label_of, len(labels)), strict=True):
        if not location:
            continue
        if include_locations is not None and location not in include_locations:
            continue
        observed_sample_counts[location] = int(rows.size)
        used = rows[usable[rows]]
        if used.size:
            amps = strength_db[used].tolist()
            usable_sample_counts[location] = int(used.size)
            grouped_amp[location] = amps
            if has_phases:
                by_phase: dict[str, list[float]] = defaultdict(list)
                for row, amp in zip(used.tolist(), amps, strict=True):
                    by_phase[phase_keys[row]].append(amp)
                phase_amp[location] = by_phase
        row_list = rows.tolist()
        dropped_totals[location] = [
            (times[row], dropped)
            for row, dropped in zip(
                row_list, samples.frames_dropped_total[rows].tolist(), strict=True
            )
        ]
        overflow_totals[location] = [
            (times[row], overflow)
            for row, overflow in zip(
                row_list, samples.queue_overflow_drops[rows].tolist(), strict=True
            )
        ]
        bucketed = samples.strength_bucket_of[used]
        bucketed = bucketed[bucketed >= 0]
        if bucketed.size:
            bucket_counts = _EMPTY_BUCKET_COUNTS.copy()
            for code in bucketed.tolist():
                bucket = samples.strength_buckets[code]
                bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
            strength_bucket_counts[location] = bucket_counts
            strength_bucket_totals[location] = int(bucketed.size)

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
