"""Per-location intensity statistics and speed/phase breakdowns."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

from vibesensor_core.vibration_strength import percentile

from ...runlog import as_float_or_none as _as_float
from ..helpers import (
    _location_label,
    _primary_vibration_strength_db,
    _speed_bin_label,
    _speed_bin_sort_key,
    counter_delta,
)


def _phase_speed_breakdown(
    samples: list[dict[str, Any]],
    per_sample_phases: list,
) -> list[dict[str, object]]:
    """Group vibration statistics by driving phase (temporal context).

    Unlike ``_speed_breakdown`` which bins by speed magnitude, this function
    groups by the temporal driving phase (IDLE, ACCELERATION, CRUISE, etc.)
    so callers can see how vibration differs across phases at the same speed.

    Addresses issue #189: adds temporal phase context to speed breakdown.
    """
    from ..phase_segmentation import DrivingPhase

    grouped_amp: dict[str, list[float]] = defaultdict(list)
    grouped_speeds: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)

    for idx, sample in enumerate(samples):
        phase = per_sample_phases[idx] if idx < len(per_sample_phases) else "unknown"
        phase_key = phase.value if isinstance(phase, DrivingPhase) else str(phase)
        counts[phase_key] += 1
        speed = _as_float(sample.get("speed_kmh"))
        if speed is not None and speed > 0:
            grouped_speeds[phase_key].append(speed)
        amp = _primary_vibration_strength_db(sample)
        if amp is not None:
            grouped_amp[phase_key].append(amp)

    # Output in a canonical phase order
    phase_order = [p.value for p in DrivingPhase]
    rows: list[dict[str, object]] = []
    for phase_key in [*phase_order, *sorted(k for k in counts if k not in phase_order)]:
        if phase_key not in counts:
            continue
        amp_vals = grouped_amp.get(phase_key, [])
        speed_vals = grouped_speeds.get(phase_key, [])
        rows.append(
            {
                "phase": phase_key,
                "count": counts[phase_key],
                "mean_speed_kmh": mean(speed_vals) if speed_vals else None,
                "max_speed_kmh": max(speed_vals) if speed_vals else None,
                "mean_vibration_strength_db": mean(amp_vals) if amp_vals else None,
                "max_vibration_strength_db": max(amp_vals) if amp_vals else None,
            }
        )
    return rows


def _speed_breakdown(samples: list[dict[str, Any]]) -> list[dict[str, object]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    for sample in samples:
        speed = _as_float(sample.get("speed_kmh"))
        if speed is None or speed <= 0:
            continue
        label = _speed_bin_label(speed)
        counts[label] += 1
        amp = _primary_vibration_strength_db(sample)
        if amp is not None:
            grouped[label].append(amp)

    rows: list[dict[str, object]] = []
    for label in sorted(counts.keys(), key=_speed_bin_sort_key):
        values = grouped.get(label, [])
        rows.append(
            {
                "speed_range": label,
                "count": counts[label],
                "mean_vibration_strength_db": mean(values) if values else None,
                "max_vibration_strength_db": max(values) if values else None,
            }
        )
    return rows


def _sensor_intensity_by_location(
    samples: list[dict[str, Any]],
    include_locations: set[str] | None = None,
    *,
    lang: object = "en",
    connected_locations: set[str] | None = None,
    per_sample_phases: list | None = None,
) -> list[dict[str, float | str | int | bool]]:
    """Compute per-location vibration intensity statistics.

    When ``per_sample_phases`` is provided, also computes per-phase intensity
    breakdown for each location so callers can see how vibration differs across
    IDLE, ACCELERATION, CRUISE, etc. at each sensor position.
    Addresses issue #192: aggregate entire run loses phase context.
    """
    grouped_amp: dict[str, list[float]] = defaultdict(list)
    sample_counts: dict[str, int] = defaultdict(int)
    dropped_totals: dict[str, list[tuple[float | None, float]]] = defaultdict(list)
    overflow_totals: dict[str, list[tuple[float | None, float]]] = defaultdict(list)
    strength_bucket_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {f"l{idx}": 0 for idx in range(0, 6)}
    )
    strength_bucket_totals: dict[str, int] = defaultdict(int)
    # Per-phase intensity: {location: {phase_key: [amp_values]}}
    phase_amp: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    has_phases = per_sample_phases is not None and len(per_sample_phases) == len(samples)

    for i, sample in enumerate(samples):
        if not isinstance(sample, dict):
            continue
        location = _location_label(sample, lang=lang)
        if not location:
            continue
        if include_locations is not None and location not in include_locations:
            continue
        sample_counts[location] += 1
        amp = _primary_vibration_strength_db(sample)
        if amp is not None:
            grouped_amp[location].append(float(amp))
            if has_phases and per_sample_phases is not None:
                phase_key = str(
                    per_sample_phases[i].value
                    if hasattr(per_sample_phases[i], "value")
                    else per_sample_phases[i]
                )
                phase_amp[location][phase_key].append(float(amp))
        sample_t_s = _as_float(sample.get("t_s"))
        dropped_total = _as_float(sample.get("frames_dropped_total"))
        if dropped_total is not None:
            dropped_totals[location].append((sample_t_s, dropped_total))
        overflow_total = _as_float(sample.get("queue_overflow_drops"))
        if overflow_total is not None:
            overflow_totals[location].append((sample_t_s, overflow_total))
        vibration_strength_db = _as_float(sample.get("vibration_strength_db"))
        bucket = str(sample.get("strength_bucket") or "")
        if vibration_strength_db is None:
            continue
        if bucket:
            strength_bucket_counts[location][bucket] = (
                strength_bucket_counts[location].get(bucket, 0) + 1
            )
            strength_bucket_totals[location] += 1

    rows: list[dict[str, float | str | int | bool]] = []
    target_locations = set(sample_counts.keys())
    if include_locations is not None:
        target_locations |= set(include_locations)
    max_sample_count = max(
        (sample_counts.get(location, 0) for location in target_locations), default=0
    )

    def _counter_delta(counter_values: list[tuple[float | None, float]]) -> int:
        """Sort timestamped counter pairs and delegate to shared helper."""
        if len(counter_values) < 2:
            return 0
        ordered = sorted(
            counter_values,
            key=lambda pair: (pair[0] is None, pair[0] if pair[0] is not None else 0.0),
        )
        return counter_delta([float(v) for _t, v in ordered])

    for location in sorted(target_locations):
        values = grouped_amp.get(location, [])
        values_sorted = sorted(values)
        dropped_vals = dropped_totals.get(location, [])
        overflow_vals = overflow_totals.get(location, [])
        dropped_delta = _counter_delta(dropped_vals)
        overflow_delta = _counter_delta(overflow_vals)
        bucket_counts = strength_bucket_counts.get(location, {f"l{idx}": 0 for idx in range(0, 6)})
        bucket_total = max(0, strength_bucket_totals.get(location, 0))
        bucket_distribution: dict[str, float | int] = {
            "total": bucket_total,
            "counts": dict(bucket_counts),
        }
        for idx in range(0, 6):
            key = f"l{idx}"
            bucket_distribution[f"percent_time_{key}"] = (
                (bucket_counts.get(key, 0) / bucket_total * 100.0) if bucket_total > 0 else 0.0
            )
        sample_count = int(sample_counts.get(location, 0))
        sample_coverage_ratio = (sample_count / max_sample_count) if max_sample_count > 0 else 1.0
        sample_coverage_warning = max_sample_count >= 5 and sample_coverage_ratio <= 0.20
        partial_coverage = bool(
            connected_locations is not None and location not in connected_locations
        )
        # Per-phase intensity summary for this location (issue #192)
        location_phase_intensity: dict[str, object] | None = None
        if has_phases:
            loc_phases = phase_amp.get(location, {})
            location_phase_intensity = {
                phase_key: {
                    "count": len(phase_vals),
                    "mean_intensity_db": mean(phase_vals) if phase_vals else None,
                    "max_intensity_db": max(phase_vals) if phase_vals else None,
                }
                for phase_key, phase_vals in loc_phases.items()
                if phase_vals
            }
        rows.append(
            {
                "location": location,
                "partial_coverage": partial_coverage,
                "samples": sample_count,
                "sample_count": sample_count,
                "sample_coverage_ratio": sample_coverage_ratio,
                "sample_coverage_warning": sample_coverage_warning,
                "mean_intensity_db": mean(values) if values else None,
                "p50_intensity_db": percentile(values_sorted, 0.50) if values else None,
                "p95_intensity_db": percentile(values_sorted, 0.95) if values else None,
                "max_intensity_db": max(values) if values else None,
                "dropped_frames_delta": dropped_delta,
                "queue_overflow_drops_delta": overflow_delta,
                "strength_bucket_distribution": bucket_distribution,
                "phase_intensity": location_phase_intensity,
            }
        )
    rows.sort(
        key=lambda row: (
            1 if not bool(row.get("partial_coverage")) else 0,
            1 if not bool(row.get("sample_coverage_warning")) else 0,
            float(row.get("p95_intensity_db") if row.get("p95_intensity_db") is not None else 0.0),
            float(row.get("max_intensity_db") if row.get("max_intensity_db") is not None else 0.0),
        ),
        reverse=True,
    )
    return rows
