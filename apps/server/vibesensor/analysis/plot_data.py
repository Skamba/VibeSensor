# ruff: noqa: E501
"""Plot data builders – FFT spectrum, spectrogram, peak tables, and composite plot payload."""

from __future__ import annotations

from collections import defaultdict
from math import floor
from statistics import mean
from typing import Any, Literal

from vibesensor_core.vibration_strength import percentile, vibration_strength_db_scalar

from ..runlog import as_float_or_none as _as_float
from .findings import _classify_peak_type, _speed_bin_label
from .helpers import (
    MEMS_NOISE_FLOOR_G,
    _amplitude_weighted_speed_window,
    _effective_baseline_floor,
    _estimate_strength_floor_amp_g,
    _location_label,
    _primary_vibration_strength_db,
    _run_noise_baseline_g,
    _sample_top_peaks,
)
from .phase_segmentation import segment_run_phases as _segment_run_phases


def _aggregate_fft_spectrum(
    samples: list[dict[str, Any]],
    *,
    freq_bin_hz: float = 2.0,
    aggregation: str = "persistence",
    run_noise_baseline_g: float | None = None,
) -> list[tuple[float, float]]:
    """Return aggregated FFT spectrum.

    aggregation='persistence': presence_ratio² × p95_amp per bin (diagnostic view).
    aggregation='max': max amplitude per bin (raw/debug view).
    """
    if freq_bin_hz <= 0:
        freq_bin_hz = 2.0
    bin_amps: dict[float, list[float]] = {}
    n_samples = 0
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        n_samples += 1
        for hz, amp in _sample_top_peaks(sample):
            if hz <= 0 or amp <= 0:
                continue
            bin_low = floor(hz / freq_bin_hz) * freq_bin_hz
            bin_center = bin_low + (freq_bin_hz / 2.0)
            bin_amps.setdefault(bin_center, []).append(amp)
    if not bin_amps:
        return []
    if run_noise_baseline_g is None:
        run_noise_baseline_g = _run_noise_baseline_g(samples)
    baseline_floor = _effective_baseline_floor(run_noise_baseline_g)
    result: dict[float, float] = {}
    for bin_center, amps in bin_amps.items():
        if aggregation == "max":
            result[bin_center] = max(amps)
        else:
            presence_ratio = len(amps) / max(1, n_samples)
            sorted_amps = sorted(amps)
            p95 = percentile(sorted_amps, 0.95) if len(sorted_amps) >= 2 else sorted_amps[-1]
            result[bin_center] = (presence_ratio**2) * (p95 / baseline_floor)
    return sorted(result.items(), key=lambda item: item[0])


def _aggregate_fft_spectrum_raw(
    samples: list[dict[str, Any]],
    *,
    freq_bin_hz: float = 2.0,
    run_noise_baseline_g: float | None = None,
) -> list[tuple[float, float]]:
    """Return max-amplitude FFT spectrum (raw/debug view)."""
    return _aggregate_fft_spectrum(
        samples,
        freq_bin_hz=freq_bin_hz,
        aggregation="max",
        run_noise_baseline_g=run_noise_baseline_g,
    )


def _spectrogram_from_peaks(
    samples: list[dict[str, Any]],
    *,
    aggregation: Literal["persistence", "max"] = "persistence",
    run_noise_baseline_g: float | None = None,
) -> dict[str, Any]:
    """Build a 2-D spectrogram grid from per-sample peak lists.

    *aggregation* controls cell values:
    - ``"persistence"`` – ``(presence_ratio²) × p95_amp`` where each observation
      is SNR-gated/weighted against its sample noise floor (default, diagnostic view).
    - ``"max"``         – simple ``max(amplitude)`` per cell (raw/debug view).
    """
    peak_rows: list[tuple[float, float, float, float | None]] = []
    time_values: list[float] = []
    speed_values: list[float] = []

    for sample in samples:
        if not isinstance(sample, dict):
            continue
        t_s = _as_float(sample.get("t_s"))
        speed = _as_float(sample.get("speed_kmh"))
        peaks = _sample_top_peaks(sample)
        if t_s is not None and t_s >= 0:
            time_values.append(t_s)
        if speed is not None and speed > 0:
            speed_values.append(speed)
        if not peaks:
            continue
        floor_amp = _estimate_strength_floor_amp_g(sample)
        for hz, amp in peaks:
            if hz <= 0 or amp <= 0:
                continue
            if t_s is not None and t_s >= 0:
                peak_rows.append((t_s, hz, amp, floor_amp))
            elif speed is not None and speed > 0:
                peak_rows.append((speed, hz, amp, floor_amp))

    use_time = bool(time_values)
    empty_result: dict[str, Any] = {
        "x_axis": "none",
        "x_label_key": "TIME_S",
        "x_bins": [],
        "y_bins": [],
        "cells": [],
        "max_amp": 0.0,
    }
    if not use_time and not speed_values:
        return empty_result

    x_axis = "time_s" if use_time else "speed_kmh"
    x_values = time_values if use_time else speed_values
    x_min = min(x_values)
    x_max = max(x_values)
    x_span = max(0.0, x_max - x_min)
    if x_axis == "time_s":
        x_bin_width = max(2.0, (x_span / 40.0) if x_span > 0 else 2.0)
        x_label_key = "TIME_S"
    else:
        x_bin_width = max(5.0, (x_span / 30.0) if x_span > 0 else 5.0)
        x_label_key = "SPEED_KM_H"

    peak_freqs = [hz for _x, hz, _amp, _floor in peak_rows]
    if not peak_freqs:
        empty_result.update(x_axis=x_axis, x_label_key=x_label_key)
        return empty_result

    observed_max_hz = max(peak_freqs)
    freq_cap_hz = min(200.0, max(40.0, observed_max_hz))
    freq_bin_hz = max(2.0, freq_cap_hz / 45.0)

    # Collect amplitudes per (x_bin, y_bin) cell.
    cell_by_bin: dict[tuple[float, float], list[tuple[float, float | None]]] = {}
    x_sample_counts: dict[float, int] = {}
    if aggregation == "persistence":
        for x_val in x_values:
            x_bin_low = floor((x_val - x_min) / x_bin_width) * x_bin_width + x_min
            x_sample_counts[x_bin_low] = x_sample_counts.get(x_bin_low, 0) + 1

    for x_val, hz, amp, floor_amp in peak_rows:
        if hz > freq_cap_hz:
            continue
        x_bin_low = floor((x_val - x_min) / x_bin_width) * x_bin_width + x_min
        y_bin_low = floor(hz / freq_bin_hz) * freq_bin_hz
        key = (x_bin_low, y_bin_low)
        cell_by_bin.setdefault(key, []).append((amp, floor_amp))

    x_bins = sorted({x for x, _y in cell_by_bin})
    y_bins = sorted({y for _x, y in cell_by_bin})
    if not x_bins or not y_bins:
        empty_result.update(x_axis=x_axis, x_label_key=x_label_key)
        return empty_result

    x_index = {value: idx for idx, value in enumerate(x_bins)}
    y_index = {value: idx for idx, value in enumerate(y_bins)}
    cells = [[0.0 for _ in x_bins] for _ in y_bins]
    max_amp = 0.0

    if run_noise_baseline_g is None:
        run_noise_baseline_g = _run_noise_baseline_g(samples)
    baseline_floor = _effective_baseline_floor(run_noise_baseline_g)
    min_presence_snr = 2.0

    for (x_key, y_key), amp_floor_pairs in cell_by_bin.items():
        yi = y_index[y_key]
        xi = x_index[x_key]
        if aggregation == "persistence":
            if not amp_floor_pairs:
                continue
            effective_amps: list[float] = []
            for amp, floor_amp in amp_floor_pairs:
                local_floor = max(
                    MEMS_NOISE_FLOOR_G,
                    floor_amp if floor_amp is not None and floor_amp > 0 else baseline_floor,
                )
                snr = amp / local_floor
                if snr < min_presence_snr:
                    continue
                snr_weight = min(1.0, snr / 5.0)
                effective_amps.append(amp * snr_weight)
            if not effective_amps:
                continue
            p95_amp = (
                percentile(sorted(effective_amps), 0.95)
                if len(effective_amps) >= 2
                else effective_amps[-1]
            )
            presence_ratio = len(effective_amps) / max(1, x_sample_counts.get(x_key, 1))
            val = (presence_ratio**2) * p95_amp
        else:
            val = max(amp for amp, _floor in amp_floor_pairs)
        cells[yi][xi] = val
        if val > max_amp:
            max_amp = val

    return {
        "x_axis": x_axis,
        "x_label_key": x_label_key,
        "x_bin_width": x_bin_width,
        "y_bin_width": freq_bin_hz,
        "x_bins": [x + (x_bin_width / 2.0) for x in x_bins],
        "y_bins": [y + (freq_bin_hz / 2.0) for y in y_bins],
        "cells": cells,
        "max_amp": max_amp,
    }


def _spectrogram_from_peaks_raw(
    samples: list[dict[str, Any]],
    *,
    run_noise_baseline_g: float | None = None,
) -> dict[str, Any]:
    """Max-amplitude spectrogram (raw/debug view)."""
    return _spectrogram_from_peaks(
        samples,
        aggregation="max",
        run_noise_baseline_g=run_noise_baseline_g,
    )


def _top_peaks_table_rows(
    samples: list[dict[str, Any]],
    *,
    top_n: int = 12,
    freq_bin_hz: float = 1.0,
    run_noise_baseline_g: float | None = None,
) -> list[dict[str, Any]]:
    """Build ranked peak table using persistence-weighted scoring.

    Each frequency bin collects all amplitude observations across samples.
    Ranking uses ``presence_ratio² × p95_amp`` so that persistent peaks
    rank above one-off transient spikes.
    """
    grouped: dict[float, dict[str, Any]] = {}
    total_locations: set[str] = set()
    total_speed_bin_counts: dict[str, int] = defaultdict(int)
    if freq_bin_hz <= 0:
        freq_bin_hz = 1.0

    n_samples = 0
    if run_noise_baseline_g is None:
        run_noise_baseline_g = _run_noise_baseline_g(samples)
    baseline_floor = _effective_baseline_floor(run_noise_baseline_g)
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

    for bucket in grouped.values():
        amps = sorted(bucket["amps"])
        floor_amps = sorted(float(v) for v in bucket.get("floor_amps", []))
        count = len(amps)
        presence_ratio = count / max(1, n_samples)
        median_amp = percentile(amps, 0.50) if count >= 2 else (amps[0] if amps else 0.0)
        p95_amp = percentile(amps, 0.95) if count >= 2 else (amps[-1] if amps else 0.0)
        max_amp = amps[-1] if amps else 0.0
        floor_amp = (
            percentile(floor_amps, 0.50)
            if len(floor_amps) >= 2
            else (floor_amps[0] if floor_amps else None)
        )
        strength_db = (
            vibration_strength_db_scalar(
                peak_band_rms_amp_g=p95_amp,
                floor_amp_g=floor_amp,
            )
            if floor_amp is not None
            else None
        )
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
                hit_rate_mean = mean(hit_rates)
                speed_uniformity = (
                    mean([(rate - hit_rate_mean) ** 2 for rate in hit_rates]) ** 0.5
                    if len(hit_rates) > 1
                    else 0.0
                )
        bucket["max_amp_g"] = max_amp
        bucket["median_amp_g"] = median_amp
        bucket["p95_amp_g"] = p95_amp
        bucket["run_noise_baseline_g"] = run_noise_baseline_g
        bucket["median_vs_run_noise_ratio"] = median_amp / baseline_floor
        bucket["p95_vs_run_noise_ratio"] = p95_amp / baseline_floor
        bucket["strength_floor_amp_g"] = floor_amp
        bucket["strength_db"] = strength_db
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
        speeds = [float(v) for v in item.get("speeds", []) if isinstance(v, (int, float))]
        speed_amps = [float(v) for v in item.get("speed_amps", []) if isinstance(v, (int, float))]
        low_speed, high_speed = _amplitude_weighted_speed_window(speeds, speed_amps)
        speed_band = (
            f"{low_speed:.0f}-{high_speed:.0f} km/h"
            if low_speed is not None and high_speed is not None
            else "-"
        )
        rows.append(
            {
                "rank": idx,
                "frequency_hz": float(item.get("frequency_hz") or 0.0),
                "order_label": "",
                "max_amp_g": float(item.get("max_amp_g") or 0.0),
                "median_amp_g": float(item.get("median_amp_g") or 0.0),
                "p95_amp_g": float(item.get("p95_amp_g") or 0.0),
                "run_noise_baseline_g": _as_float(item.get("run_noise_baseline_g")),
                "median_vs_run_noise_ratio": float(
                    item.get("median_vs_run_noise_ratio")
                    if item.get("median_vs_run_noise_ratio") is not None
                    else 0.0
                ),
                "p95_vs_run_noise_ratio": float(
                    item.get("p95_vs_run_noise_ratio")
                    if item.get("p95_vs_run_noise_ratio") is not None
                    else 0.0
                ),
                "strength_floor_amp_g": _as_float(item.get("strength_floor_amp_g")),
                "strength_db": _as_float(item.get("strength_db")),
                "presence_ratio": float(
                    item.get("presence_ratio") if item.get("presence_ratio") is not None else 0.0
                ),
                "burstiness": float(
                    item.get("burstiness") if item.get("burstiness") is not None else 0.0
                ),
                "persistence_score": float(
                    item.get("persistence_score")
                    if item.get("persistence_score") is not None
                    else 0.0
                ),
                "peak_classification": _classify_peak_type(
                    presence_ratio=float(
                        item.get("presence_ratio")
                        if item.get("presence_ratio") is not None
                        else 0.0
                    ),
                    burstiness=float(
                        item.get("burstiness") if item.get("burstiness") is not None else 0.0
                    ),
                    snr=_as_float(item.get("p95_vs_run_noise_ratio")),
                    spatial_uniformity=_as_float(item.get("spatial_uniformity")),
                    speed_uniformity=_as_float(item.get("speed_uniformity")),
                ),
                "typical_speed_band": speed_band,
            }
        )
    return rows


def _plot_data(
    summary: dict[str, Any],
    *,
    run_noise_baseline_g: float | None = None,
    per_sample_phases: list | None = None,
    phase_segments: list | None = None,
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = summary.get("samples", [])
    raw_sample_rate_hz = _as_float(summary.get("raw_sample_rate_hz"))
    vib_mag_points: list[tuple[float, float, str]] = []  # (t_s, vib_db, phase_label)
    dominant_freq_points: list[tuple[float, float]] = []
    speed_amp_points: list[tuple[float, float]] = []
    matched_by_finding: list[dict[str, object]] = []
    freq_vs_speed_by_finding: list[dict[str, object]] = []
    steady_speed_distribution: dict[str, float] | None = None

    if per_sample_phases is not None and phase_segments is not None:
        phase_segs = phase_segments
    else:
        per_sample_phases, phase_segs = _segment_run_phases(samples)

    if run_noise_baseline_g is None:
        run_noise_baseline_g = _run_noise_baseline_g(samples)

    for i, sample in enumerate(samples):
        t_s = _as_float(sample.get("t_s"))
        if t_s is None:
            continue
        phase_label: str = per_sample_phases[i].value if i < len(per_sample_phases) else "unknown"
        vib = _primary_vibration_strength_db(sample)
        if vib is not None:
            vib_mag_points.append((t_s, vib, phase_label))
        if raw_sample_rate_hz and raw_sample_rate_hz > 0:
            dominant_hz = _as_float(sample.get("dominant_freq_hz"))
            if dominant_hz is not None and dominant_hz > 0:
                dominant_freq_points.append((t_s, dominant_hz))

    for row in summary.get("speed_breakdown", []):
        if not isinstance(row, dict):
            continue
        speed_range = str(row.get("speed_range", ""))
        if "-" not in speed_range:
            continue
        prefix = speed_range.split(" ", 1)[0]
        low_text, _, high_text = prefix.partition("-")
        try:
            low = float(low_text)
            high = float(high_text)
        except ValueError:
            continue
        amp = _as_float(row.get("mean_vibration_strength_db"))
        if amp is None:
            continue
        speed_amp_points.append(((low + high) / 2.0, amp))

    for finding in summary.get("findings", []):
        if not isinstance(finding, dict):
            continue
        points_raw = finding.get("matched_points")
        if not isinstance(points_raw, list):
            continue
        points: list[tuple[float, float]] = []
        for row in points_raw:
            if not isinstance(row, dict):
                continue
            speed = _as_float(row.get("speed_kmh"))
            amp = _as_float(row.get("amp"))
            if speed is None or amp is None or speed <= 0:
                continue
            points.append((speed, amp))
        if points:
            matched_by_finding.append(
                {
                    "label": str(finding.get("frequency_hz_or_order") or finding.get("finding_id")),
                    "points": points,
                }
            )
        freq_points: list[tuple[float, float]] = []
        pred_points: list[tuple[float, float]] = []
        for row in points_raw:
            if not isinstance(row, dict):
                continue
            speed = _as_float(row.get("speed_kmh"))
            matched_hz = _as_float(row.get("matched_hz"))
            predicted_hz = _as_float(row.get("predicted_hz"))
            if speed is None or speed <= 0:
                continue
            if matched_hz is not None and matched_hz > 0:
                freq_points.append((speed, matched_hz))
            if predicted_hz is not None and predicted_hz > 0:
                pred_points.append((speed, predicted_hz))
        if freq_points:
            freq_vs_speed_by_finding.append(
                {
                    "label": str(finding.get("frequency_hz_or_order") or finding.get("finding_id")),
                    "matched": freq_points,
                    "predicted": pred_points,
                }
            )

    speed_stats = summary.get("speed_stats", {})
    if isinstance(speed_stats, dict) and bool(speed_stats.get("steady_speed")) and vib_mag_points:
        vals = sorted(v for _t, v, _phase in vib_mag_points if v >= 0)
        if vals:
            steady_speed_distribution = {
                "p10": percentile(vals, 0.10),
                "p50": percentile(vals, 0.50),
                "p90": percentile(vals, 0.90),
                "p95": percentile(vals, 0.95),
            }

    # Build amp_vs_phase from phase_speed_breakdown (temporal phase context).
    # Complements amp_vs_speed (magnitude bins) by grouping by driving phase
    # instead of speed range, addressing issue #189.
    amp_vs_phase: list[dict[str, object]] = []
    for row in summary.get("phase_speed_breakdown", []):
        if not isinstance(row, dict):
            continue
        phase = str(row.get("phase", ""))
        mean_vib = _as_float(row.get("mean_vibration_strength_db"))
        if not phase or mean_vib is None:
            continue
        amp_vs_phase.append(
            {
                "phase": phase,
                "count": int(row.get("count") or 0),
                "mean_vib_db": mean_vib,
                "max_vib_db": _as_float(row.get("max_vibration_strength_db")),
                "mean_speed_kmh": _as_float(row.get("mean_speed_kmh")),
            }
        )

    fft_spectrum = _aggregate_fft_spectrum(samples, run_noise_baseline_g=run_noise_baseline_g)
    fft_spectrum_raw = _aggregate_fft_spectrum_raw(
        samples,
        run_noise_baseline_g=run_noise_baseline_g,
    )
    peaks_spectrogram = _spectrogram_from_peaks(
        samples,
        run_noise_baseline_g=run_noise_baseline_g,
    )
    peaks_spectrogram_raw = _spectrogram_from_peaks_raw(
        samples,
        run_noise_baseline_g=run_noise_baseline_g,
    )
    peaks_table = _top_peaks_table_rows(
        samples,
        run_noise_baseline_g=run_noise_baseline_g,
    )

    phase_segments_out = [
        {"phase": seg.phase.value, "start_t_s": seg.start_t_s, "end_t_s": seg.end_t_s}
        for seg in phase_segs
    ]
    phase_boundaries: list[dict[str, Any]] = [
        {"phase": seg.phase.value, "t_s": seg.start_t_s, "end_t_s": seg.end_t_s}
        for seg in phase_segs
    ]

    return {
        "vib_magnitude": vib_mag_points,
        "dominant_freq": dominant_freq_points,
        "amp_vs_speed": speed_amp_points,
        "amp_vs_phase": amp_vs_phase,
        "matched_amp_vs_speed": matched_by_finding,
        "freq_vs_speed_by_finding": freq_vs_speed_by_finding,
        "steady_speed_distribution": steady_speed_distribution,
        "fft_spectrum": fft_spectrum,
        "fft_spectrum_raw": fft_spectrum_raw,
        "peaks_spectrogram": peaks_spectrogram,
        "peaks_spectrogram_raw": peaks_spectrogram_raw,
        "peaks_table": peaks_table,
        "phase_segments": phase_segments_out,
        "phase_boundaries": phase_boundaries,
    }
