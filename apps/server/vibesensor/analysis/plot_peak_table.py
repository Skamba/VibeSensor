"""Peak-table shaping for report-facing analysis plots."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import floor
from typing import TypedDict

from vibesensor_core.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

from ..constants import MEMS_NOISE_FLOOR_G
from ._types import Sample
from .findings.persistent_findings import _classify_peak_type
from .helpers import (
    _amplitude_weighted_speed_window,
    _effective_baseline_floor,
    _run_noise_baseline_g,
)
from .plot_spectrum import (
    PeakSampleScan,
    safe_percentile,
    scan_peak_samples,
    vibration_db_or_none,
)


class PeakTableRow(TypedDict):
    """Shape of a single row in the ranked peak table."""

    rank: int
    frequency_hz: float
    order_label: str
    max_intensity_db: float | None
    median_intensity_db: float | None
    p95_intensity_db: float | None
    run_noise_baseline_db: float | None
    median_vs_run_noise_ratio: float
    p95_vs_run_noise_ratio: float
    strength_floor_db: float | None
    strength_db: float | None
    presence_ratio: float
    burstiness: float
    persistence_score: float
    peak_classification: str
    typical_speed_band: str


@dataclass
class _PeakBucket:
    """Internal accumulator for per-frequency-bin peak statistics."""

    frequency_hz: float
    amps: list[float] = field(default_factory=list)
    floor_amps: list[float] = field(default_factory=list)
    speeds: list[float] = field(default_factory=list)
    speed_amps: list[float] = field(default_factory=list)
    location_counts: dict[str, int] = field(default_factory=dict)
    speed_bin_counts: dict[str, int] = field(default_factory=dict)
    # Computed during the statistics pass:
    max_intensity_db: float | None = None
    median_intensity_db: float | None = None
    p95_intensity_db: float | None = None
    run_noise_baseline_db: float | None = None
    median_vs_run_noise_ratio: float = 0.0
    p95_vs_run_noise_ratio: float = 0.0
    strength_floor_db: float | None = None
    strength_db: float | None = None
    presence_ratio: float = 0.0
    burstiness: float = 0.0
    persistence_score: float = 0.0
    spatial_uniformity: float | None = None
    speed_uniformity: float | None = None


def top_peaks_table_rows(
    samples: list[Sample],
    *,
    top_n: int = 12,
    freq_bin_hz: float = 1.0,
    run_noise_baseline_g: float | None = None,
    peak_scan: PeakSampleScan | None = None,
) -> list[PeakTableRow]:
    """Build ranked peak-table rows using persistence-weighted scoring."""
    resolved_scan = peak_scan or scan_peak_samples(samples)
    grouped: dict[float, _PeakBucket] = {}
    total_locations = resolved_scan.total_locations
    total_speed_bin_counts = resolved_scan.total_speed_bin_counts
    if freq_bin_hz <= 0:
        freq_bin_hz = 1.0

    if run_noise_baseline_g is None:
        run_noise_baseline_g = _run_noise_baseline_g(samples)
    baseline_floor = _effective_baseline_floor(run_noise_baseline_g)

    n_samples = resolved_scan.sample_count
    for row in resolved_scan.rows:
        speed = row.speed_kmh
        sample_speed_bin = row.speed_bin
        location = row.location
        for hz, amp in row.peaks:
            freq_key = floor(hz / freq_bin_hz) * freq_bin_hz
            if freq_key not in grouped:
                grouped[freq_key] = _PeakBucket(frequency_hz=freq_key)
            bucket = grouped[freq_key]
            bucket.amps.append(amp)
            floor_amp = row.floor_amp_g
            if floor_amp is not None:
                bucket.floor_amps.append(floor_amp)
            if speed is not None and speed > 0:
                bucket.speeds.append(speed)
                bucket.speed_amps.append(amp)
            if location:
                bucket.location_counts[location] = bucket.location_counts.get(location, 0) + 1
            if sample_speed_bin is not None:
                bucket.speed_bin_counts[sample_speed_bin] = (
                    bucket.speed_bin_counts.get(sample_speed_bin, 0) + 1
                )

    run_noise_baseline_db: float | None = (
        canonical_vibration_db(
            peak_band_rms_amp_g=_effective_baseline_floor(run_noise_baseline_g),
            floor_amp_g=MEMS_NOISE_FLOOR_G,
        )
        if run_noise_baseline_g is not None
        else None
    )

    for bucket in grouped.values():
        amps = sorted(bucket.amps)
        floor_amps = sorted(bucket.floor_amps)
        count = len(amps)
        presence_ratio = min(1.0, count / max(1, n_samples))
        median_amp = safe_percentile(amps, 0.50)
        p95_amp = safe_percentile(amps, 0.95)
        max_amp = amps[-1] if amps else 0.0
        floor_amp_val = safe_percentile(floor_amps, 0.50) if floor_amps else None
        max_intensity_db = vibration_db_or_none(max_amp, floor_amp_val)
        median_intensity_db = vibration_db_or_none(median_amp, floor_amp_val)
        p95_intensity_db = vibration_db_or_none(p95_amp, floor_amp_val)
        burstiness = (max_amp / median_amp) if median_amp > 1e-9 else 0.0
        spatial_uniformity: float | None = None
        if len(total_locations) >= 2:
            spatial_uniformity = len(bucket.location_counts) / len(total_locations)
        speed_uniformity: float | None = None
        if len(total_speed_bin_counts) >= 2:
            hit_rates: list[float] = []
            for speed_bin, total_count in total_speed_bin_counts.items():
                if total_count <= 0:
                    continue
                hit_rates.append(
                    float(bucket.speed_bin_counts.get(speed_bin, 0)) / float(total_count),
                )
            if hit_rates:
                hit_rate_mean = sum(hit_rates) / len(hit_rates)
                speed_uniformity = (
                    (sum((rate - hit_rate_mean) ** 2 for rate in hit_rates) / len(hit_rates)) ** 0.5
                    if len(hit_rates) > 1
                    else 0.0
                )
        bucket.max_intensity_db = max_intensity_db
        bucket.median_intensity_db = median_intensity_db
        bucket.p95_intensity_db = p95_intensity_db
        bucket.run_noise_baseline_db = run_noise_baseline_db
        bucket.median_vs_run_noise_ratio = median_amp / baseline_floor
        bucket.p95_vs_run_noise_ratio = p95_amp / baseline_floor
        bucket.strength_floor_db = vibration_db_or_none(floor_amp_val, MEMS_NOISE_FLOOR_G)
        bucket.strength_db = p95_intensity_db
        bucket.presence_ratio = presence_ratio
        bucket.burstiness = burstiness
        bucket.persistence_score = (presence_ratio**2) * p95_amp
        bucket.spatial_uniformity = spatial_uniformity
        bucket.speed_uniformity = speed_uniformity

    ordered = sorted(
        grouped.values(),
        key=lambda b: b.persistence_score,
        reverse=True,
    )[:top_n]

    rows: list[PeakTableRow] = []
    for idx, item in enumerate(ordered, start=1):
        low_speed, high_speed = _amplitude_weighted_speed_window(item.speeds, item.speed_amps)
        speed_band = (
            f"{low_speed:.0f}-{high_speed:.0f} km/h"
            if low_speed is not None and high_speed is not None
            else "-"
        )
        rows.append(
            PeakTableRow(
                rank=idx,
                frequency_hz=item.frequency_hz,
                order_label="",
                max_intensity_db=item.max_intensity_db,
                median_intensity_db=item.median_intensity_db,
                p95_intensity_db=item.p95_intensity_db,
                run_noise_baseline_db=item.run_noise_baseline_db,
                median_vs_run_noise_ratio=item.median_vs_run_noise_ratio,
                p95_vs_run_noise_ratio=item.p95_vs_run_noise_ratio,
                strength_floor_db=item.strength_floor_db,
                strength_db=item.strength_db,
                presence_ratio=item.presence_ratio,
                burstiness=item.burstiness,
                persistence_score=item.persistence_score,
                peak_classification=_classify_peak_type(
                    presence_ratio=item.presence_ratio,
                    burstiness=item.burstiness,
                    snr=item.p95_vs_run_noise_ratio,
                    spatial_uniformity=item.spatial_uniformity,
                    speed_uniformity=item.speed_uniformity,
                ),
                typical_speed_band=speed_band,
            ),
        )
    return rows
