# ruff: noqa: E501
"""Plot data builders – FFT spectrum, spectrogram, peak tables, and composite plot payload."""

from __future__ import annotations

from math import floor
from typing import Any, Literal

from vibesensor_core.vibration_strength import percentile

from ..runlog import as_float_or_none as _as_float
from .helpers import (
    _primary_vibration_strength_db,
    _sample_top_peaks,
)


def _aggregate_fft_spectrum(
    samples: list[dict[str, Any]],
    *,
    freq_bin_hz: float = 2.0,
    aggregation: str = "persistence",
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
    result: dict[float, float] = {}
    for bin_center, amps in bin_amps.items():
        if aggregation == "max":
            result[bin_center] = max(amps)
        else:
            presence_ratio = len(amps) / max(1, n_samples)
            sorted_amps = sorted(amps)
            p95 = percentile(sorted_amps, 0.95) if len(sorted_amps) >= 2 else sorted_amps[-1]
            result[bin_center] = (presence_ratio**2) * p95
    return sorted(result.items(), key=lambda item: item[0])


def _aggregate_fft_spectrum_raw(
    samples: list[dict[str, Any]],
    *,
    freq_bin_hz: float = 2.0,
) -> list[tuple[float, float]]:
    """Return max-amplitude FFT spectrum (raw/debug view)."""
    return _aggregate_fft_spectrum(samples, freq_bin_hz=freq_bin_hz, aggregation="max")


def _spectrogram_from_peaks(
    samples: list[dict[str, Any]],
    *,
    aggregation: Literal["persistence", "max"] = "persistence",
) -> dict[str, Any]:
    """Build a 2-D spectrogram grid from per-sample peak lists.

    *aggregation* controls cell values:
    - ``"persistence"`` – ``(presence_ratio²) × p95_amp`` (default, diagnostic view).
    - ``"max"``         – simple ``max(amplitude)`` per cell (raw/debug view).
    """
    peak_rows: list[tuple[float, float, float]] = []
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
        for hz, amp in peaks:
            if hz <= 0 or amp <= 0:
                continue
            if t_s is not None and t_s >= 0:
                peak_rows.append((t_s, hz, amp))
            elif speed is not None and speed > 0:
                peak_rows.append((speed, hz, amp))

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

    peak_freqs = [hz for _x, hz, _amp in peak_rows]
    if not peak_freqs:
        empty_result.update(x_axis=x_axis, x_label_key=x_label_key)
        return empty_result

    observed_max_hz = max(peak_freqs)
    freq_cap_hz = min(200.0, max(40.0, observed_max_hz))
    freq_bin_hz = max(2.0, freq_cap_hz / 45.0)

    # Collect amplitudes per (x_bin, y_bin) cell.
    cell_by_bin: dict[tuple[float, float], list[float]] = {}
    x_sample_counts: dict[float, int] = {}
    if aggregation == "persistence":
        for x_val in x_values:
            x_bin_low = floor((x_val - x_min) / x_bin_width) * x_bin_width + x_min
            x_sample_counts[x_bin_low] = x_sample_counts.get(x_bin_low, 0) + 1

    for x_val, hz, amp in peak_rows:
        if hz > freq_cap_hz:
            continue
        x_bin_low = floor((x_val - x_min) / x_bin_width) * x_bin_width + x_min
        y_bin_low = floor(hz / freq_bin_hz) * freq_bin_hz
        key = (x_bin_low, y_bin_low)
        cell_by_bin.setdefault(key, []).append(amp)

    x_bins = sorted({x for x, _y in cell_by_bin})
    y_bins = sorted({y for _x, y in cell_by_bin})
    if not x_bins or not y_bins:
        empty_result.update(x_axis=x_axis, x_label_key=x_label_key)
        return empty_result

    x_index = {value: idx for idx, value in enumerate(x_bins)}
    y_index = {value: idx for idx, value in enumerate(y_bins)}
    cells = [[0.0 for _ in x_bins] for _ in y_bins]
    max_amp = 0.0

    for (x_key, y_key), amps in cell_by_bin.items():
        yi = y_index[y_key]
        xi = x_index[x_key]
        if aggregation == "persistence":
            sorted_amps = sorted(amps)
            if not sorted_amps:
                continue
            p95_amp = (
                percentile(sorted_amps, 0.95) if len(sorted_amps) >= 2 else sorted_amps[-1]
            )
            presence_ratio = len(sorted_amps) / max(1, x_sample_counts.get(x_key, 1))
            val = (presence_ratio**2) * p95_amp
        else:
            val = max(amps)
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


def _spectrogram_from_peaks_raw(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Max-amplitude spectrogram (raw/debug view)."""
    return _spectrogram_from_peaks(samples, aggregation="max")


def _top_peaks_table_rows(
    samples: list[dict[str, Any]],
    *,
    top_n: int = 12,
    freq_bin_hz: float = 1.0,
) -> list[dict[str, Any]]:
    """Build ranked peak table using persistence-weighted scoring.

    Each frequency bin collects all amplitude observations across samples.
    Ranking uses ``presence_ratio² × p95_amp`` so that persistent peaks
    rank above one-off transient spikes.
    """
    grouped: dict[float, dict[str, Any]] = {}
    if freq_bin_hz <= 0:
        freq_bin_hz = 1.0

    n_samples = 0
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        n_samples += 1
        speed = _as_float(sample.get("speed_kmh"))
        for hz, amp in _sample_top_peaks(sample):
            if hz <= 0 or amp <= 0:
                continue
            freq_key = round(hz / freq_bin_hz) * freq_bin_hz
            bucket = grouped.setdefault(
                freq_key,
                {
                    "frequency_hz": freq_key,
                    "amps": [],
                    "speeds": [],
                },
            )
            bucket["amps"].append(amp)
            if speed is not None and speed > 0:
                bucket["speeds"].append(speed)

    for bucket in grouped.values():
        amps = sorted(bucket["amps"])
        count = len(amps)
        presence_ratio = count / max(1, n_samples)
        median_amp = percentile(amps, 0.50) if count >= 2 else (amps[0] if amps else 0.0)
        p95_amp = percentile(amps, 0.95) if count >= 2 else (amps[-1] if amps else 0.0)
        max_amp = amps[-1] if amps else 0.0
        burstiness = (max_amp / median_amp) if median_amp > 1e-9 else 0.0
        bucket["max_amp_g"] = max_amp
        bucket["median_amp_g"] = median_amp
        bucket["p95_amp_g"] = p95_amp
        bucket["presence_ratio"] = presence_ratio
        bucket["burstiness"] = burstiness
        bucket["persistence_score"] = (presence_ratio**2) * p95_amp

    ordered = sorted(
        grouped.values(),
        key=lambda item: float(item.get("persistence_score") or 0.0),
        reverse=True,
    )[:top_n]

    rows: list[dict[str, Any]] = []
    for idx, item in enumerate(ordered, start=1):
        speeds = [float(v) for v in item.get("speeds", []) if isinstance(v, (int, float))]
        speed_band = "-"
        if speeds:
            speed_band = f"{min(speeds):.0f}-{max(speeds):.0f} km/h"
        rows.append(
            {
                "rank": idx,
                "frequency_hz": float(item.get("frequency_hz") or 0.0),
                "order_label": "",
                "max_amp_g": float(item.get("max_amp_g") or 0.0),
                "median_amp_g": float(item.get("median_amp_g") or 0.0),
                "p95_amp_g": float(item.get("p95_amp_g") or 0.0),
                "presence_ratio": float(item.get("presence_ratio") or 0.0),
                "burstiness": float(item.get("burstiness") or 0.0),
                "persistence_score": float(item.get("persistence_score") or 0.0),
                "peak_classification": (
                    "transient"
                    if (
                        float(item.get("presence_ratio") or 0.0) < 0.15
                        or float(item.get("burstiness") or 0.0) > 5.0
                    )
                    else (
                        "patterned"
                        if (
                            float(item.get("presence_ratio") or 0.0) >= 0.40
                            and float(item.get("burstiness") or 0.0) < 3.0
                        )
                        else "persistent"
                    )
                ),
                "typical_speed_band": speed_band,
            }
        )
    return rows


def _plot_data(summary: dict[str, Any]) -> dict[str, Any]:
    samples: list[dict[str, Any]] = summary.get("samples", [])
    raw_sample_rate_hz = _as_float(summary.get("raw_sample_rate_hz"))
    vib_mag_points: list[tuple[float, float]] = []
    dominant_freq_points: list[tuple[float, float]] = []
    speed_amp_points: list[tuple[float, float]] = []
    matched_by_finding: list[dict[str, object]] = []
    freq_vs_speed_by_finding: list[dict[str, object]] = []
    steady_speed_distribution: dict[str, float] | None = None

    for sample in samples:
        t_s = _as_float(sample.get("t_s"))
        if t_s is None:
            continue
        vib = _primary_vibration_strength_db(sample)
        if vib is not None:
            vib_mag_points.append((t_s, vib))
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
        amp = _as_float(row.get("mean_amplitude_g"))
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
        vals = sorted(v for _t, v in vib_mag_points if v >= 0)
        if vals:
            steady_speed_distribution = {
                "p10": percentile(vals, 0.10),
                "p50": percentile(vals, 0.50),
                "p90": percentile(vals, 0.90),
                "p95": percentile(vals, 0.95),
            }

    fft_spectrum = _aggregate_fft_spectrum(samples)
    fft_spectrum_raw = _aggregate_fft_spectrum_raw(samples)
    peaks_spectrogram = _spectrogram_from_peaks(samples)
    peaks_spectrogram_raw = _spectrogram_from_peaks_raw(samples)
    peaks_table = _top_peaks_table_rows(samples)

    return {
        "vib_magnitude": vib_mag_points,
        "dominant_freq": dominant_freq_points,
        "amp_vs_speed": speed_amp_points,
        "matched_amp_vs_speed": matched_by_finding,
        "freq_vs_speed_by_finding": freq_vs_speed_by_finding,
        "steady_speed_distribution": steady_speed_distribution,
        "fft_spectrum": fft_spectrum,
        "fft_spectrum_raw": fft_spectrum_raw,
        "peaks_spectrogram": peaks_spectrogram,
        "peaks_spectrogram_raw": peaks_spectrogram_raw,
        "peaks_table": peaks_table,
    }
