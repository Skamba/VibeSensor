"""Peak-table row building for diagnostics reports."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from math import floor
from statistics import median as _median

from vibesensor.domain import Finding as DomainFinding
from vibesensor.shared.constants import MEMS_NOISE_FLOOR_G
from vibesensor.use_cases.diagnostics._sample_metrics import (
    _effective_baseline_floor,
    _run_noise_baseline_g,
)
from vibesensor.use_cases.diagnostics._types import PeakTableRowData, Sample
from vibesensor.use_cases.diagnostics.peaks.classification import classify_peak_type
from vibesensor.use_cases.diagnostics.peaks.statistics import (
    compute_peak_distribution_stats,
    compute_peak_persistence_score,
    compute_peak_spatial_uniformity,
    compute_peak_speed_uniformity,
)
from vibesensor.use_cases.diagnostics.spectrogram import (
    PeakSampleScan,
    scan_peak_samples,
)
from vibesensor.use_cases.diagnostics.speed_profile_helpers import (
    _amplitude_weighted_speed_window,
)
from vibesensor.vibration_strength import compute_db, compute_db_or_none


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
) -> list[PeakTableRowData]:
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
        compute_db(
            _effective_baseline_floor(run_noise_baseline_g),
            MEMS_NOISE_FLOOR_G,
        )
        if run_noise_baseline_g is not None
        else None
    )

    for bucket in grouped.values():
        stats = compute_peak_distribution_stats(bucket.amps, bucket.floor_amps)
        count = stats.sample_count
        presence_ratio = min(1.0, count / max(1, n_samples))
        floor_amp_val = stats.median_floor_amp
        max_intensity_db = compute_db_or_none(stats.max_amp, floor_amp_val)
        median_intensity_db = compute_db_or_none(stats.median_amp, floor_amp_val)
        p95_intensity_db = compute_db_or_none(stats.p95_amp, floor_amp_val)
        spatial_uniformity = compute_peak_spatial_uniformity(
            matching_locations=len(bucket.location_counts),
            total_locations=len(total_locations),
        )
        speed_uniformity = compute_peak_speed_uniformity(
            speed_bin_counts_for_bin=bucket.speed_bin_counts,
            total_speed_bin_counts=total_speed_bin_counts,
        )
        bucket.max_intensity_db = max_intensity_db
        bucket.median_intensity_db = median_intensity_db
        bucket.p95_intensity_db = p95_intensity_db
        bucket.run_noise_baseline_db = run_noise_baseline_db
        bucket.median_vs_run_noise_ratio = stats.median_amp / baseline_floor
        bucket.p95_vs_run_noise_ratio = stats.p95_amp / baseline_floor
        bucket.strength_floor_db = compute_db_or_none(floor_amp_val, MEMS_NOISE_FLOOR_G)
        bucket.strength_db = p95_intensity_db
        bucket.presence_ratio = presence_ratio
        bucket.burstiness = stats.burstiness
        bucket.persistence_score = compute_peak_persistence_score(
            presence_ratio=presence_ratio,
            p95_amp=stats.p95_amp,
        )
        bucket.spatial_uniformity = spatial_uniformity
        bucket.speed_uniformity = speed_uniformity

    ordered = sorted(
        grouped.values(),
        key=lambda bucket: bucket.persistence_score,
        reverse=True,
    )[:top_n]

    rows: list[PeakTableRowData] = []
    for idx, item in enumerate(ordered, start=1):
        low_speed, high_speed = _amplitude_weighted_speed_window(item.speeds, item.speed_amps)
        speed_band = (
            f"{low_speed:.0f}-{high_speed:.0f} km/h"
            if low_speed is not None and high_speed is not None
            else "-"
        )
        rows.append(
            PeakTableRowData(
                rank=idx,
                frequency_hz=item.frequency_hz,
                order_label="",
                suspected_source="",
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
                peak_classification=classify_peak_type(
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


def annotate_peak_rows_with_order_labels(
    rows: list[PeakTableRowData],
    findings: Sequence[DomainFinding],
) -> list[PeakTableRowData]:
    """Back-fill peak-table order labels using domain findings before serialization."""
    if not rows or not findings:
        return rows

    order_annotations: list[tuple[float, str, str]] = []
    for finding in findings:
        if finding.finding_id != "F_ORDER" or not finding.matched_points:
            continue
        label = finding.order.strip() or (
            str(finding.frequency_hz) if finding.frequency_hz is not None else ""
        )
        if not label:
            continue
        matched_freqs = [
            point.matched_hz for point in finding.matched_points if point.matched_hz > 0
        ]
        if matched_freqs:
            order_annotations.append(
                (_median(matched_freqs), label, str(finding.suspected_source).strip()),
            )

    if not order_annotations:
        return rows

    tolerance_hz = 2.0
    annotated = list(rows)
    used_rows: set[int] = set()
    for median_hz, label, suspected_source in order_annotations:
        best_idx: int | None = None
        best_dist = tolerance_hz + 1.0
        for idx, row in enumerate(annotated):
            if idx in used_rows:
                continue
            dist = abs(row.frequency_hz - median_hz)
            if dist < best_dist:
                best_idx = idx
                best_dist = dist
        if best_idx is not None and best_dist <= tolerance_hz:
            annotated[best_idx] = replace(
                annotated[best_idx],
                order_label=label,
                suspected_source=suspected_source,
            )
            used_rows.add(best_idx)
    return annotated
