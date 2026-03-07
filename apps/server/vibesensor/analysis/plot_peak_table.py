"""Peak-table shaping for report-facing analysis plots."""

from __future__ import annotations

from collections import defaultdict
from math import floor
from typing import Any

from vibesensor_core.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

from ..constants import MEMS_NOISE_FLOOR_G, NUMERIC_TYPES
from ..runlog import as_float_or_none as _as_float
from .findings.persistent_findings import _classify_peak_type
from .helpers import (
    _amplitude_weighted_speed_window,
    _effective_baseline_floor,
    _estimate_strength_floor_amp_g,
    _location_label,
    _run_noise_baseline_g,
    _sample_top_peaks,
    _speed_bin_label,
)
from .plot_spectrum import safe_percentile, vibration_db_or_none


def top_peaks_table_rows(
    samples: list[dict[str, Any]],
    *,
    top_n: int = 12,
    freq_bin_hz: float = 1.0,
    run_noise_baseline_g: float | None = None,
) -> list[dict[str, Any]]:
    """Build ranked peak-table rows using persistence-weighted scoring."""
    grouped: dict[float, dict[str, Any]] = {}
    total_locations: set[str] = set()
    total_speed_bin_counts: dict[str, int] = defaultdict(int)
    if freq_bin_hz <= 0:
        freq_bin_hz = 1.0

    if run_noise_baseline_g is None:
        run_noise_baseline_g = _run_noise_baseline_g(samples)
    baseline_floor = _effective_baseline_floor(run_noise_baseline_g)

    n_samples = 0
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        n_samples += 1
        speed = _as_float(sample.get("speed_kmh"))
        sample_speed_bin = _speed_bin_label(speed) if speed is not None and speed > 0 else None
        if sample_speed_bin is not None:
            total_speed_bin_counts[sample_speed_bin] += 1
        location = _location_label(sample)
        if location:
            total_locations.add(location)
        for hz, amp in _sample_top_peaks(sample):
            if hz <= 0 or amp <= 0:
                continue
            freq_key = floor(hz / freq_bin_hz) * freq_bin_hz
            bucket = grouped.setdefault(
                freq_key,
                {
                    "frequency_hz": freq_key,
                    "amps": [],
                    "floor_amps": [],
                    "speeds": [],
                    "speed_amps": [],
                    "location_counts": {},
                    "speed_bin_counts": {},
                },
            )
            bucket["amps"].append(amp)
            floor_amp = _estimate_strength_floor_amp_g(sample)
            if floor_amp is not None:
                bucket["floor_amps"].append(floor_amp)
            if speed is not None and speed > 0:
                bucket["speeds"].append(speed)
                bucket["speed_amps"].append(amp)
            if location:
                counts = bucket["location_counts"]
                counts[location] = int(counts.get(location, 0)) + 1
            if sample_speed_bin is not None:
                speed_counts = bucket["speed_bin_counts"]
                speed_counts[sample_speed_bin] = int(speed_counts.get(sample_speed_bin, 0)) + 1

    run_noise_baseline_db: float | None = (
        canonical_vibration_db(
            peak_band_rms_amp_g=_effective_baseline_floor(run_noise_baseline_g),
            floor_amp_g=MEMS_NOISE_FLOOR_G,
        )
        if run_noise_baseline_g is not None
        else None
    )

    for bucket in grouped.values():
        amps = sorted(bucket["amps"])
        floor_amps = sorted(bucket.get("floor_amps", []))
        count = len(amps)
        presence_ratio = min(1.0, count / max(1, n_samples))
        median_amp = safe_percentile(amps, 0.50)
        p95_amp = safe_percentile(amps, 0.95)
        max_amp = amps[-1] if amps else 0.0
        floor_amp = safe_percentile(floor_amps, 0.50) if floor_amps else None
        max_intensity_db = vibration_db_or_none(max_amp, floor_amp)
        median_intensity_db = vibration_db_or_none(median_amp, floor_amp)
        p95_intensity_db = vibration_db_or_none(p95_amp, floor_amp)
        burstiness = (max_amp / median_amp) if median_amp > 1e-9 else 0.0
        spatial_uniformity: float | None = None
        if len(total_locations) >= 2:
            spatial_uniformity = len(bucket.get("location_counts", {})) / len(total_locations)
        speed_uniformity: float | None = None
        if len(total_speed_bin_counts) >= 2:
            hit_rates: list[float] = []
            per_bin_hits = bucket.get("speed_bin_counts", {})
            for speed_bin, total_count in total_speed_bin_counts.items():
                if total_count <= 0:
                    continue
                hit_rates.append(float(per_bin_hits.get(speed_bin, 0)) / float(total_count))
            if hit_rates:
                hit_rate_mean = sum(hit_rates) / len(hit_rates)
                speed_uniformity = (
                    (sum((rate - hit_rate_mean) ** 2 for rate in hit_rates) / len(hit_rates)) ** 0.5
                    if len(hit_rates) > 1
                    else 0.0
                )
        bucket["max_intensity_db"] = max_intensity_db
        bucket["median_intensity_db"] = median_intensity_db
        bucket["p95_intensity_db"] = p95_intensity_db
        bucket["run_noise_baseline_db"] = run_noise_baseline_db
        bucket["median_vs_run_noise_ratio"] = median_amp / baseline_floor
        bucket["p95_vs_run_noise_ratio"] = p95_amp / baseline_floor
        bucket["strength_floor_db"] = vibration_db_or_none(floor_amp, MEMS_NOISE_FLOOR_G)
        bucket["strength_db"] = p95_intensity_db
        bucket["presence_ratio"] = presence_ratio
        bucket["burstiness"] = burstiness
        bucket["persistence_score"] = (presence_ratio**2) * p95_amp
        bucket["spatial_uniformity"] = spatial_uniformity
        bucket["speed_uniformity"] = speed_uniformity

    ordered = sorted(
        grouped.values(),
        key=lambda item: float(item.get("persistence_score") or 0.0),
        reverse=True,
    )[:top_n]

    rows: list[dict[str, Any]] = []
    for idx, item in enumerate(ordered, start=1):
        speeds = [float(v) for v in item.get("speeds", []) if isinstance(v, NUMERIC_TYPES)]
        speed_amps = [float(v) for v in item.get("speed_amps", []) if isinstance(v, NUMERIC_TYPES)]
        low_speed, high_speed = _amplitude_weighted_speed_window(speeds, speed_amps)
        speed_band = (
            f"{low_speed:.0f}-{high_speed:.0f} km/h"
            if low_speed is not None and high_speed is not None
            else "-"
        )
        presence_ratio = float(item.get("presence_ratio", 0.0))
        burstiness = float(item.get("burstiness", 0.0))
        rows.append(
            {
                "rank": idx,
                "frequency_hz": float(item.get("frequency_hz", 0.0)),
                "order_label": "",
                "max_intensity_db": _as_float(item.get("max_intensity_db")),
                "median_intensity_db": _as_float(item.get("median_intensity_db")),
                "p95_intensity_db": _as_float(item.get("p95_intensity_db")),
                "run_noise_baseline_db": _as_float(item.get("run_noise_baseline_db")),
                "median_vs_run_noise_ratio": float(item.get("median_vs_run_noise_ratio", 0.0)),
                "p95_vs_run_noise_ratio": float(item.get("p95_vs_run_noise_ratio", 0.0)),
                "strength_floor_db": _as_float(item.get("strength_floor_db")),
                "strength_db": _as_float(item.get("strength_db")),
                "presence_ratio": presence_ratio,
                "burstiness": burstiness,
                "persistence_score": float(item.get("persistence_score", 0.0)),
                "peak_classification": _classify_peak_type(
                    presence_ratio=presence_ratio,
                    burstiness=burstiness,
                    snr=_as_float(item.get("p95_vs_run_noise_ratio")),
                    spatial_uniformity=_as_float(item.get("spatial_uniformity")),
                    speed_uniformity=_as_float(item.get("speed_uniformity")),
                ),
                "typical_speed_band": speed_band,
            }
        )
    return rows
