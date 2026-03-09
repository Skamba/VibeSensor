"""FFT spectrum and spectrogram builders for analysis plot payloads."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import floor
from typing import Literal, TypedDict

from vibesensor_core.vibration_strength import percentile
from vibesensor_core.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

from ..constants import MEMS_NOISE_FLOOR_G
from ..runlog import as_float_or_none as _as_float
from ._types import Sample
from .helpers import (
    _effective_baseline_floor,
    _estimate_strength_floor_amp_g,
    _location_label,
    _run_noise_baseline_g,
    _sample_top_peaks,
    _speed_bin_label,
)


class _SpectrogramResultRequired(TypedDict):
    """Required fields present in every spectrogram result (including empty)."""

    x_axis: str
    x_label_key: str
    x_bins: list[float]
    y_bins: list[float]
    cells: list[list[float]]
    max_amp: float


class SpectrogramResult(_SpectrogramResultRequired, total=False):
    """Shape returned by spectrogram builders.

    All :class:`_SpectrogramResultRequired` fields are always present.
    ``x_bin_width`` and ``y_bin_width`` are only set in non-empty results.
    """

    x_bin_width: float
    y_bin_width: float


@dataclass(frozen=True, slots=True)
class PeakSampleScanRow:
    t_s: float | None
    speed_kmh: float | None
    peaks: list[tuple[float, float]]
    floor_amp_g: float | None
    location: str | None
    speed_bin: str | None


@dataclass(frozen=True, slots=True)
class PeakSampleScan:
    sample_count: int
    rows: list[PeakSampleScanRow]
    time_values: list[float]
    speed_values: list[float]
    total_locations: set[str]
    total_speed_bin_counts: dict[str, int]


def scan_peak_samples(samples: list[Sample]) -> PeakSampleScan:
    """Scan raw samples once and cache the peak-facing data needed by plot builders."""
    rows: list[PeakSampleScanRow] = []
    time_values: list[float] = []
    speed_values: list[float] = []
    total_locations: set[str] = set()
    total_speed_bin_counts: dict[str, int] = defaultdict(int)
    sample_count = 0

    for sample in samples:
        if not isinstance(sample, dict):
            continue
        sample_count += 1
        t_s = _as_float(sample.get("t_s"))
        speed = _as_float(sample.get("speed_kmh"))
        peaks = [(hz, amp) for hz, amp in _sample_top_peaks(sample) if hz > 0 and amp > 0]
        floor_amp = _estimate_strength_floor_amp_g(sample)
        location = _location_label(sample)
        speed_bin = _speed_bin_label(speed) if speed is not None and speed > 0 else None

        if t_s is not None and t_s >= 0:
            time_values.append(t_s)
        if speed is not None and speed > 0:
            speed_values.append(speed)
        if location:
            total_locations.add(location)
        if speed_bin is not None:
            total_speed_bin_counts[speed_bin] += 1

        rows.append(
            PeakSampleScanRow(
                t_s=t_s,
                speed_kmh=speed,
                peaks=peaks,
                floor_amp_g=floor_amp,
                location=location,
                speed_bin=speed_bin,
            ),
        )

    return PeakSampleScan(
        sample_count=sample_count,
        rows=rows,
        time_values=time_values,
        speed_values=speed_values,
        total_locations=total_locations,
        total_speed_bin_counts=dict(total_speed_bin_counts),
    )


def safe_percentile(sorted_vals: list[float], q: float, *, default: float = 0.0) -> float:
    """Return ``percentile(sorted_vals, q)`` when possible, else a safe fallback."""
    if len(sorted_vals) >= 2:
        return float(percentile(sorted_vals, q))
    return sorted_vals[-1] if sorted_vals else default


def vibration_db_or_none(peak_amp: float | None, floor_amp: float | None) -> float | None:
    """Return the canonical vibration dB value when both inputs are present."""
    if peak_amp is None or floor_amp is None:
        return None
    return float(canonical_vibration_db(peak_band_rms_amp_g=peak_amp, floor_amp_g=floor_amp))


def aggregate_fft_spectrum(
    samples: list[Sample],
    *,
    freq_bin_hz: float = 2.0,
    aggregation: str = "persistence",
    run_noise_baseline_g: float | None = None,
    peak_scan: PeakSampleScan | None = None,
) -> list[tuple[float, float]]:
    """Return aggregated FFT spectrum for the requested aggregation mode."""
    if freq_bin_hz <= 0:
        freq_bin_hz = 2.0

    bin_amps: defaultdict[float, list[float]] = defaultdict(list)
    resolved_scan = peak_scan or scan_peak_samples(samples)
    n_samples = resolved_scan.sample_count
    for row in resolved_scan.rows:
        for hz, amp in row.peaks:
            bin_low = floor(hz / freq_bin_hz) * freq_bin_hz
            bin_center = round(bin_low + (freq_bin_hz / 2.0), 4)
            bin_amps[bin_center].append(amp)
    if not bin_amps:
        return []

    if run_noise_baseline_g is None:
        run_noise_baseline_g = _run_noise_baseline_g(samples)
    baseline_floor = _effective_baseline_floor(run_noise_baseline_g)

    result: dict[float, float] = {}
    for bin_center, amps in bin_amps.items():
        if aggregation == "max":
            result[bin_center] = max(amps)
            continue
        presence_ratio = min(1.0, len(amps) / max(1, n_samples))
        p95 = safe_percentile(sorted(amps), 0.95)
        result[bin_center] = (presence_ratio**2) * (p95 / baseline_floor)
    return sorted(result.items())


def aggregate_fft_spectrum_raw(
    samples: list[Sample],
    *,
    freq_bin_hz: float = 2.0,
    run_noise_baseline_g: float | None = None,
    peak_scan: PeakSampleScan | None = None,
) -> list[tuple[float, float]]:
    """Return the raw max-amplitude FFT spectrum."""
    return aggregate_fft_spectrum(
        samples,
        freq_bin_hz=freq_bin_hz,
        aggregation="max",
        run_noise_baseline_g=run_noise_baseline_g,
        peak_scan=peak_scan,
    )


def spectrogram_from_peaks(
    samples: list[Sample],
    *,
    aggregation: Literal["persistence", "max"] = "persistence",
    run_noise_baseline_g: float | None = None,
    peak_scan: PeakSampleScan | None = None,
) -> SpectrogramResult:
    """Build a 2-D spectrogram grid from per-sample peak lists."""
    resolved_scan = peak_scan or scan_peak_samples(samples)
    peak_rows: list[tuple[float, float, float, float | None]] = []
    time_values = resolved_scan.time_values
    speed_values = resolved_scan.speed_values

    for row in resolved_scan.rows:
        if not row.peaks:
            continue
        for hz, amp in row.peaks:
            if row.t_s is not None and row.t_s >= 0:
                peak_rows.append((row.t_s, hz, amp, row.floor_amp_g))
            elif row.speed_kmh is not None and row.speed_kmh > 0:
                peak_rows.append((row.speed_kmh, hz, amp, row.floor_amp_g))

    use_time = bool(time_values)
    empty_result = SpectrogramResult(
        x_axis="none",
        x_label_key="TIME_S",
        x_bins=[],
        y_bins=[],
        cells=[],
        max_amp=0.0,
    )
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
        empty_result["x_axis"] = x_axis
        empty_result["x_label_key"] = x_label_key
        return empty_result

    observed_max_hz = max(peak_freqs)
    freq_cap_hz = min(200.0, max(40.0, observed_max_hz))
    freq_bin_hz = max(2.0, freq_cap_hz / 45.0)

    cell_by_bin: defaultdict[tuple[float, float], list[tuple[float, float | None]]] = defaultdict(
        list,
    )
    x_sample_counts: defaultdict[float, int] = defaultdict(int)
    if aggregation == "persistence":
        for x_val in x_values:
            x_bin_low = floor((x_val - x_min) / x_bin_width) * x_bin_width + x_min
            x_sample_counts[x_bin_low] += 1

    for x_val, hz, amp, floor_amp in peak_rows:
        if hz > freq_cap_hz:
            continue
        x_bin_low = floor((x_val - x_min) / x_bin_width) * x_bin_width + x_min
        y_bin_low = floor(hz / freq_bin_hz) * freq_bin_hz
        cell_by_bin[(x_bin_low, y_bin_low)].append((amp, floor_amp))

    x_bins = sorted({x for x, _y in cell_by_bin})
    y_bins = sorted({y for _x, y in cell_by_bin})
    if not x_bins or not y_bins:
        empty_result["x_axis"] = x_axis
        empty_result["x_label_key"] = x_label_key
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
            effective_amps: list[float] = []
            for amp, floor_amp in amp_floor_pairs:
                local_floor = max(
                    MEMS_NOISE_FLOOR_G,
                    floor_amp if floor_amp is not None and floor_amp > 0 else baseline_floor,
                )
                snr = amp / local_floor
                if snr < min_presence_snr:
                    continue
                effective_amps.append(amp * min(1.0, snr / 5.0))
            if not effective_amps:
                continue
            p95_amp = safe_percentile(sorted(effective_amps), 0.95)
            presence_ratio = min(1.0, len(effective_amps) / max(1, x_sample_counts.get(x_key, 1)))
            val = (presence_ratio**2) * p95_amp
        else:
            val = max(amp for amp, _floor in amp_floor_pairs)
        cells[yi][xi] = val
        max_amp = max(max_amp, val)

    return SpectrogramResult(
        x_axis=x_axis,
        x_label_key=x_label_key,
        x_bin_width=x_bin_width,
        y_bin_width=freq_bin_hz,
        x_bins=[x + (x_bin_width / 2.0) for x in x_bins],
        y_bins=[y + (freq_bin_hz / 2.0) for y in y_bins],
        cells=cells,
        max_amp=max_amp,
    )


def spectrogram_from_peaks_raw(
    samples: list[Sample],
    *,
    run_noise_baseline_g: float | None = None,
    peak_scan: PeakSampleScan | None = None,
) -> SpectrogramResult:
    """Build the raw/max-amplitude spectrogram view."""
    return spectrogram_from_peaks(
        samples,
        aggregation="max",
        run_noise_baseline_g=run_noise_baseline_g,
        peak_scan=peak_scan,
    )
