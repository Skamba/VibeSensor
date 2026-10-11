"""Peak-table row building for diagnostics reports."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from math import floor

import numpy as np
import numpy.typing as npt

from vibesensor.analysis._sample_metrics import _effective_baseline_floor, _run_noise_baseline_g
from vibesensor.analysis._view_types import PeakTableRowData
from vibesensor.analysis.constants import MEMS_NOISE_FLOOR_G, SPEED_BIN_WIDTH_KMH
from vibesensor.analysis.drive_table import DriveTable, counts_by_group, groups_in_order
from vibesensor.analysis.peaks.classification import classify_peak_type
from vibesensor.analysis.peaks.statistics import (
    compute_peak_distribution_stats,
    compute_peak_persistence_score,
    compute_peak_spatial_uniformity,
    compute_peak_speed_uniformity,
)
from vibesensor.domain.finding import Finding as DomainFinding
from vibesensor.domain.finding import speed_band_sort_key
from vibesensor.dsp.vibration_strength import compute_db, compute_db_or_none


@dataclass(slots=True)
class _PeakBucket:
    """One frequency bin's peak statistics."""

    frequency_hz: float
    # The bin's place among the bins (``groups_in_order``).
    number: int
    max_intensity_db: float | None
    median_intensity_db: float | None
    p95_intensity_db: float | None
    median_vs_run_noise_ratio: float
    p95_vs_run_noise_ratio: float
    strength_floor_db: float | None
    presence_ratio: float
    burstiness: float
    persistence_score: float
    spatial_uniformity: float | None
    speed_uniformity: float | None


def top_peaks_table_rows(
    table: DriveTable,
    *,
    top_n: int = 12,
    freq_bin_hz: float = 1.0,
    run_noise_baseline_g: float | None = None,
) -> list[PeakTableRowData]:
    """Build ranked peak-table rows using persistence-weighted scoring.

    The drive's analysed peaks fall in bins of *freq_bin_hz* named by their low
    edge, the bins in the order the peaks first fall in them; the *top_n* with
    the highest persistence score (the first of equal ones) become the rows.
    """
    if freq_bin_hz <= 0:
        freq_bin_hz = 1.0
    if run_noise_baseline_g is None:
        run_noise_baseline_g = _run_noise_baseline_g(table)
    baseline_floor = _effective_baseline_floor(run_noise_baseline_g)
    run_noise_baseline_db: float | None = (
        compute_db(baseline_floor, MEMS_NOISE_FLOOR_G) if run_noise_baseline_g is not None else None
    )
    n_samples = table.size
    located = table.located
    total_locations = int(np.count_nonzero(located))
    total_speed_bin_counts = table.speed_bin_counts()

    frequencies, bin_of = groups_in_order(np.floor(table.peak_hz / freq_bin_hz) * freq_bin_hz)
    # The peaks bin by bin, each bin's in the drive's order.
    order = np.argsort(bin_of, kind="stable")
    ordered_bin = bin_of[order]
    bounds = np.searchsorted(ordered_bin, np.arange(len(frequencies) + 1)).tolist()
    row = table.peak_row[order]
    amps = table.peak_amp[order]
    amp_values = amps.tolist()
    with_floor = table.has_floor[row]
    floors = table.floor_amp_g[row][with_floor].tolist()
    floor_bounds = np.concatenate(([0], np.cumsum(with_floor)))[bounds].tolist()
    location_of = table.location_of[row]
    locations_by_bin = counts_by_group(
        ordered_bin, location_of, located[location_of], table.locations
    )
    speed_bin_of = table.speed_bin_of[row]
    speed_bins_by_bin = counts_by_group(
        ordered_bin, speed_bin_of, speed_bin_of >= 0, table.speed_bins
    )

    buckets: list[_PeakBucket] = []
    for number, frequency_hz in enumerate(frequencies):
        stats = compute_peak_distribution_stats(
            amp_values[bounds[number] : bounds[number + 1]],
            floors[floor_bounds[number] : floor_bounds[number + 1]],
        )
        presence_ratio = min(1.0, stats.sample_count / max(1, n_samples))
        floor_amp_val = stats.median_floor_amp
        buckets.append(
            _PeakBucket(
                frequency_hz=frequency_hz,
                number=number,
                max_intensity_db=compute_db_or_none(stats.max_amp, floor_amp_val),
                median_intensity_db=compute_db_or_none(stats.median_amp, floor_amp_val),
                p95_intensity_db=compute_db_or_none(stats.p95_amp, floor_amp_val),
                median_vs_run_noise_ratio=stats.median_amp / baseline_floor,
                p95_vs_run_noise_ratio=stats.p95_amp / baseline_floor,
                strength_floor_db=compute_db_or_none(floor_amp_val, MEMS_NOISE_FLOOR_G),
                presence_ratio=presence_ratio,
                burstiness=stats.burstiness,
                persistence_score=compute_peak_persistence_score(
                    presence_ratio=presence_ratio,
                    p95_amp=stats.p95_amp,
                ),
                spatial_uniformity=compute_peak_spatial_uniformity(
                    matching_locations=len(locations_by_bin.get(number, {})),
                    total_locations=total_locations,
                ),
                speed_uniformity=compute_peak_speed_uniformity(
                    speed_bin_counts_for_bin=speed_bins_by_bin.get(number, {}),
                    total_speed_bin_counts=total_speed_bin_counts,
                ),
            )
        )

    ordered = sorted(buckets, key=lambda bucket: bucket.persistence_score, reverse=True)[:top_n]

    # The peaks that weigh in a bin's speed window: a moving sample's, both values finite.
    weighed = (speed_bin_of >= 0) & np.isfinite(table.speed_kmh[row]) & np.isfinite(amps)
    band_lows = [speed_band_sort_key(label) for label in table.speed_bins]
    rows: list[PeakTableRowData] = []
    for idx, item in enumerate(ordered, start=1):
        start, end = bounds[item.number], bounds[item.number + 1]
        in_window = weighed[start:end]
        low_speed, high_speed = _amplitude_weighted_speed_window(
            speed_bin_of[start:end][in_window], amps[start:end][in_window], band_lows
        )
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
                run_noise_baseline_db=run_noise_baseline_db,
                median_vs_run_noise_ratio=item.median_vs_run_noise_ratio,
                p95_vs_run_noise_ratio=item.p95_vs_run_noise_ratio,
                strength_floor_db=item.strength_floor_db,
                strength_db=item.p95_intensity_db,
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


def _amplitude_weighted_speed_window(
    speed_bin_of: npt.NDArray[np.intp],
    amps: npt.NDArray[np.float64],
    band_lows: Sequence[int],
) -> tuple[float | None, float | None]:
    """The speed bin with the most amplitude summed in it (the faster of equal ones), as a window.

    *speed_bin_of* indexes the speed bins whose low ends are *band_lows*.
    """
    if not speed_bin_of.size:
        return (None, None)
    # Each bin's amplitudes summed one by one in the peaks' order.
    weights = np.bincount(speed_bin_of, weights=amps, minlength=len(band_lows)).tolist()
    present = np.flatnonzero(np.bincount(speed_bin_of, minlength=len(band_lows))).tolist()
    strongest = max(present, key=lambda code: (weights[code], band_lows[code]))
    low_kmh = float(band_lows[strongest])
    return (low_kmh, low_kmh + float(SPEED_BIN_WIDTH_KMH))


_MIN_ORDER_POINTS_PER_ROW = 3
_MIN_ORDER_POINT_SHARE_PER_ROW = 0.05


def annotate_peak_rows_with_order_labels(
    rows: list[PeakTableRowData],
    findings: Sequence[DomainFinding],
    *,
    freq_bin_hz: float = 1.0,
) -> list[PeakTableRowData]:
    """Label peak rows an order finding tracks with its order code and mark them patterned.

    An order that follows speed spreads over several 1 Hz rows (and its pooled
    amplitude looks bursty), so every row that holds a meaningful share of the
    finding's matched points belongs to that order, not to a transient.
    """
    if not rows or not findings or freq_bin_hz <= 0:
        return rows
    row_index = {row.frequency_hz: idx for idx, row in enumerate(rows)}
    claims: dict[int, tuple[int, DomainFinding]] = {}
    for finding in findings:
        if finding.order_code is None or not finding.matched_points:
            continue
        counts: dict[int, int] = defaultdict(int)
        for point in finding.matched_points:
            idx = row_index.get(floor(point.matched_hz / freq_bin_hz) * freq_bin_hz)
            if idx is not None:
                counts[idx] += 1
        min_points = max(
            _MIN_ORDER_POINTS_PER_ROW,
            int(len(finding.matched_points) * _MIN_ORDER_POINT_SHARE_PER_ROW),
        )
        for idx, count in counts.items():
            if count >= min_points and count > claims.get(idx, (0, finding))[0]:
                claims[idx] = (count, finding)
    annotated = list(rows)
    for idx, (_count, finding) in claims.items():
        annotated[idx] = replace(
            annotated[idx],
            order_label=finding.order_code or "",
            suspected_source=str(finding.suspected_source),
            peak_classification="patterned",
        )
    return annotated
