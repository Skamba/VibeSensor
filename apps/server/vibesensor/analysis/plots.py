"""Plot-data builders: spectrum, series, peak tables, and orchestration.

Consolidates the former ``plot_spectrum``, ``plot_series``,
``plot_peak_table``, and ``plot_data`` modules into a single file.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from math import floor
from typing import Literal, Required, TypedDict

from vibesensor.domain.core import VibrationReading
from vibesensor.vibration_strength import percentile

from ..constants import MEMS_NOISE_FLOOR_G
from ..domain_models import as_float_or_none as _as_float
from ._types import Sample, SummaryData
from .findings import _classify_peak_type
from .helpers import (
    _amplitude_weighted_speed_window,
    _effective_baseline_floor,
    _estimate_strength_floor_amp_g,
    _location_label,
    _primary_vibration_strength_db,
    _run_noise_baseline_g,
    _sample_top_peaks,
    _speed_bin_label,
)
from .phase_segmentation import DrivingPhase, PhaseSegment
from .phase_segmentation import segment_run_phases as _segment_run_phases

# ---------------------------------------------------------------------------
# Spectrum types & builders (formerly plot_spectrum.py)
# ---------------------------------------------------------------------------


class SpectrogramResult(TypedDict, total=False):
    """Shape returned by spectrogram builders.

    Required fields are always present; ``x_bin_width`` and ``y_bin_width``
    are only set in non-empty results.
    """

    x_axis: Required[str]
    x_label_key: Required[str]
    x_bins: Required[list[float]]
    y_bins: Required[list[float]]
    cells: Required[list[list[float]]]
    max_amp: Required[float]
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


# ---------------------------------------------------------------------------
# Series types & builders (formerly plot_series.py)
# ---------------------------------------------------------------------------


class MatchedAmpVsSpeedSeries(TypedDict):
    """Per-finding matched-point series for amp-vs-speed."""

    label: str
    points: list[tuple[float, float]]


class FreqVsSpeedByFindingSeries(TypedDict):
    """Per-finding frequency-vs-speed series with predicted overlay."""

    label: str
    matched: list[tuple[float, float]]
    predicted: list[tuple[float, float]]


class AmpVsPhaseRow(TypedDict):
    """A single phase-grouped vibration row."""

    phase: str
    count: int
    mean_vib_db: float
    max_vib_db: float | None
    mean_speed_kmh: float | None


class PhaseSegmentOut(TypedDict):
    """Serialised driving-phase segment for plot consumers."""

    phase: str
    start_t_s: float | None
    end_t_s: float | None


class PhaseBoundary(TypedDict):
    """Phase boundary marker for plot overlay."""

    phase: str
    t_s: float | None
    end_t_s: float | None


@dataclass(frozen=True)
class PlotSeriesBundle:
    """Intermediate series grouped by plot concern."""

    vib_magnitude: list[tuple[float, float, str]]
    dominant_freq: list[tuple[float, float]]
    amp_vs_speed: list[tuple[float, float]]
    matched_amp_vs_speed: list[MatchedAmpVsSpeedSeries]
    freq_vs_speed_by_finding: list[FreqVsSpeedByFindingSeries]
    steady_speed_distribution: dict[str, float] | None
    amp_vs_phase: list[AmpVsPhaseRow]
    phase_segments_out: list[PhaseSegmentOut]
    phase_boundaries: list[PhaseBoundary]


def build_plot_series(
    summary: SummaryData,
    *,
    per_sample_phases: list[DrivingPhase],
    phase_segments: list[PhaseSegment],
    raw_sample_rate_hz: float | None,
) -> PlotSeriesBundle:
    """Build reusable time/speed/finding series for the plot payload."""
    samples: list[Sample] = summary.get("samples", [])
    vib_mag_points: list[tuple[float, float, str]] = []
    dominant_freq_points: list[tuple[float, float]] = []
    speed_amp_points: list[tuple[float, float]] = []
    matched_by_finding: list[MatchedAmpVsSpeedSeries] = []
    freq_vs_speed_by_finding: list[FreqVsSpeedByFindingSeries] = []

    for i, sample in enumerate(samples):
        t_s = _as_float(sample.get("t_s"))
        if t_s is None:
            continue
        phase_label = per_sample_phases[i].value if i < len(per_sample_phases) else "unknown"
        vib = _primary_vibration_strength_db(sample)
        if vib is not None:
            vib_mag_points.append((t_s, vib, phase_label))
        if raw_sample_rate_hz and raw_sample_rate_hz > 0:
            dominant_hz = _as_float(sample.get("dominant_freq_hz"))
            if dominant_hz is not None and dominant_hz > 0:
                dominant_freq_points.append((t_s, dominant_hz))

    for row in summary.get("speed_breakdown", []):
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
        points_raw = finding.get("matched_points")
        if not isinstance(points_raw, list):
            continue
        finding_label = str(finding.get("frequency_hz_or_order") or finding.get("finding_id"))
        matched_points: list[tuple[float, float]] = []
        freq_points: list[tuple[float, float]] = []
        predicted_points: list[tuple[float, float]] = []
        for pt in points_raw:
            if not isinstance(pt, dict):
                continue
            speed = _as_float(pt.get("speed_kmh"))
            amp = _as_float(pt.get("amp"))
            matched_hz = _as_float(pt.get("matched_hz"))
            predicted_hz = _as_float(pt.get("predicted_hz"))
            if speed is None or speed <= 0:
                continue
            if amp is not None:
                matched_points.append((speed, amp))
            if matched_hz is not None and matched_hz > 0:
                freq_points.append((speed, matched_hz))
            if predicted_hz is not None and predicted_hz > 0:
                predicted_points.append((speed, predicted_hz))
        if matched_points:
            matched_by_finding.append(
                MatchedAmpVsSpeedSeries(label=finding_label, points=matched_points),
            )
        if freq_points:
            freq_vs_speed_by_finding.append(
                FreqVsSpeedByFindingSeries(
                    label=finding_label,
                    matched=freq_points,
                    predicted=predicted_points,
                ),
            )

    steady_speed_distribution = build_steady_speed_distribution(
        summary,
        vib_mag_points=vib_mag_points,
    )
    amp_vs_phase = build_amp_vs_phase(summary)
    phase_segments_out, phase_boundaries = serialize_phase_context(phase_segments)
    return PlotSeriesBundle(
        vib_magnitude=vib_mag_points,
        dominant_freq=dominant_freq_points,
        amp_vs_speed=speed_amp_points,
        matched_amp_vs_speed=matched_by_finding,
        freq_vs_speed_by_finding=freq_vs_speed_by_finding,
        steady_speed_distribution=steady_speed_distribution,
        amp_vs_phase=amp_vs_phase,
        phase_segments_out=phase_segments_out,
        phase_boundaries=phase_boundaries,
    )


def build_steady_speed_distribution(
    summary: SummaryData,
    *,
    vib_mag_points: list[tuple[float, float, str]],
) -> dict[str, float] | None:
    """Build steady-speed percentile distribution when appropriate."""
    speed_stats = summary.get("speed_stats")
    if not (speed_stats and bool(speed_stats.get("steady_speed")) and vib_mag_points):
        return None
    vals = sorted(v for _t, v, _phase in vib_mag_points if v >= 0)
    if not vals:
        return None
    return {
        "p10": percentile(vals, 0.10),
        "p50": percentile(vals, 0.50),
        "p90": percentile(vals, 0.90),
        "p95": percentile(vals, 0.95),
    }


def build_amp_vs_phase(summary: SummaryData) -> list[AmpVsPhaseRow]:
    """Shape the phase-grouped vibration rows for plotting."""
    amp_vs_phase: list[AmpVsPhaseRow] = []
    for row in summary.get("phase_speed_breakdown", []):
        phase = str(row.get("phase", ""))
        mean_vib = _as_float(row.get("mean_vibration_strength_db"))
        if not phase or mean_vib is None:
            continue
        amp_vs_phase.append(
            AmpVsPhaseRow(
                phase=phase,
                count=int(row.get("count") or 0),
                mean_vib_db=mean_vib,
                max_vib_db=_as_float(row.get("max_vibration_strength_db")),
                mean_speed_kmh=_as_float(row.get("mean_speed_kmh")),
            ),
        )
    return amp_vs_phase


def serialize_phase_context(
    phase_segments: list[PhaseSegment],
) -> tuple[list[PhaseSegmentOut], list[PhaseBoundary]]:
    """Serialize phase segments for plot consumers."""
    phase_segments_out: list[PhaseSegmentOut] = []
    phase_boundaries: list[PhaseBoundary] = []
    for segment in phase_segments:
        phase_value = segment.phase.value
        phase_segments_out.append(
            PhaseSegmentOut(
                phase=phase_value,
                start_t_s=segment.start_t_s,
                end_t_s=segment.end_t_s,
            ),
        )
        phase_boundaries.append(
            PhaseBoundary(
                phase=phase_value,
                t_s=segment.start_t_s,
                end_t_s=segment.end_t_s,
            ),
        )
    return phase_segments_out, phase_boundaries


# ---------------------------------------------------------------------------
# Peak-table types & builders (formerly plot_peak_table.py)
# ---------------------------------------------------------------------------


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
        VibrationReading.compute_db(
            _effective_baseline_floor(run_noise_baseline_g),
            MEMS_NOISE_FLOOR_G,
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
        max_intensity_db = VibrationReading.compute_db_or_none(max_amp, floor_amp_val)
        median_intensity_db = VibrationReading.compute_db_or_none(median_amp, floor_amp_val)
        p95_intensity_db = VibrationReading.compute_db_or_none(p95_amp, floor_amp_val)
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
        bucket.strength_floor_db = VibrationReading.compute_db_or_none(
            floor_amp_val, MEMS_NOISE_FLOOR_G
        )
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


# ---------------------------------------------------------------------------
# Plot-data orchestration (formerly plot_data.py)
# ---------------------------------------------------------------------------


class PlotDataResult(TypedDict):
    """Shape returned by the plot-data orchestration layer."""

    vib_magnitude: list[tuple[float, float, str]]
    dominant_freq: list[tuple[float, float]]
    amp_vs_speed: list[tuple[float, float]]
    amp_vs_phase: list[AmpVsPhaseRow]
    matched_amp_vs_speed: list[MatchedAmpVsSpeedSeries]
    freq_vs_speed_by_finding: list[FreqVsSpeedByFindingSeries]
    steady_speed_distribution: dict[str, float] | None
    fft_spectrum: list[tuple[float, float]]
    fft_spectrum_raw: list[tuple[float, float]]
    peaks_spectrogram: SpectrogramResult
    peaks_spectrogram_raw: SpectrogramResult
    peaks_table: list[PeakTableRow]
    phase_segments: list[PhaseSegmentOut]
    phase_boundaries: list[PhaseBoundary]


def _plot_data(
    summary: SummaryData,
    *,
    run_noise_baseline_g: float | None = None,
    per_sample_phases: list[DrivingPhase] | None = None,
    phase_segments: list[PhaseSegment] | None = None,
) -> PlotDataResult:
    samples: list[Sample] = summary.get("samples", [])
    raw_sample_rate_hz = _as_float(summary.get("raw_sample_rate_hz"))
    if run_noise_baseline_g is None:
        run_noise_baseline_g = _run_noise_baseline_g(samples)

    if per_sample_phases is not None and phase_segments is not None:
        resolved_phases = per_sample_phases
        resolved_phase_segments = phase_segments
    else:
        resolved_phases, resolved_phase_segments = _segment_run_phases(samples)

    peak_scan = scan_peak_samples(samples)

    series = build_plot_series(
        summary,
        per_sample_phases=resolved_phases,
        phase_segments=resolved_phase_segments,
        raw_sample_rate_hz=raw_sample_rate_hz,
    )
    return PlotDataResult(
        vib_magnitude=series.vib_magnitude,
        dominant_freq=series.dominant_freq,
        amp_vs_speed=series.amp_vs_speed,
        amp_vs_phase=series.amp_vs_phase,
        matched_amp_vs_speed=series.matched_amp_vs_speed,
        freq_vs_speed_by_finding=series.freq_vs_speed_by_finding,
        steady_speed_distribution=series.steady_speed_distribution,
        fft_spectrum=aggregate_fft_spectrum(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=peak_scan,
        ),
        fft_spectrum_raw=aggregate_fft_spectrum_raw(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=peak_scan,
        ),
        peaks_spectrogram=spectrogram_from_peaks(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=peak_scan,
        ),
        peaks_spectrogram_raw=spectrogram_from_peaks_raw(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=peak_scan,
        ),
        peaks_table=top_peaks_table_rows(
            samples,
            run_noise_baseline_g=run_noise_baseline_g,
            peak_scan=peak_scan,
        ),
        phase_segments=series.phase_segments_out,
        phase_boundaries=series.phase_boundaries,
    )
