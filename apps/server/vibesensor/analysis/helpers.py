"""Low-level helpers, constants, and utility functions for report analysis."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from math import isfinite, sqrt
from pathlib import Path
from typing import TypedDict, cast

from vibesensor.vibration_strength import percentile

from ..analysis_settings import (
    engine_rpm_from_wheel_hz,
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_kmh,
)
from ..constants import (
    MEMS_NOISE_FLOOR_G,
    MIN_ANALYSIS_FREQ_HZ,
    SPEED_BIN_WIDTH_KMH,
    STEADY_SPEED_RANGE_KMH,
    STEADY_SPEED_STDDEV_KMH,
    WEAK_SPATIAL_DOMINANCE_THRESHOLD,
)
from ..domain_models import as_float_or_none as _as_float
from ..json_types import JsonObject
from ..locations import label_for_code as _label_for_code
from ..runlog import read_jsonl_run
from ._types import MetadataDict, PhaseLabel, PhaseSpeedStats, Sample, SpeedStats

# Maps driving-phase keys to their canonical i18n label keys.
# Shared by summary-building logic (phase-onset notes) and report mapping
# (phase param resolution in resolve_i18n) to prevent drift between the two.
PHASE_I18N_KEYS: dict[str, str] = {
    "acceleration": "DRIVING_PHASE_ACCELERATION",
    "deceleration": "DRIVING_PHASE_DECELERATION",
    "coast_down": "DRIVING_PHASE_COAST_DOWN",
}


def weak_spatial_dominance_threshold(location_count: int | None) -> float:
    """Return adaptive dominance threshold for weak spatial separation.

    Baseline is the historical 1.2 ratio for two locations. For larger sensor
    sets, we require stronger separation (+10% per additional location) because
    chance ties become more likely as the number of compared locations grows.
    """
    if location_count is None:
        return float(WEAK_SPATIAL_DOMINANCE_THRESHOLD)
    n_locations = max(2, int(location_count))
    return float(WEAK_SPATIAL_DOMINANCE_THRESHOLD) * (1.0 + (0.1 * (n_locations - 2)))


def _validate_required_strength_metrics(samples: list[Sample]) -> None:
    if not samples:
        return
    first_bad_idx: int | None = None
    for idx, sample in enumerate(samples):
        if _as_float(sample.get("vibration_strength_db")) is not None:
            return  # at least one valid sample → OK
        if first_bad_idx is None:
            first_bad_idx = idx
    # first_bad_idx is always set (to 0) when we reach this raise because the
    # loop iterates from index 0 and any bad sample at idx=0 sets it immediately.
    # Using 'or 0' as a fallback for None is misleading here: replace with an
    # explicit None-check to make the intent clear.
    raise ValueError(
        f"Missing required precomputed strength metrics in sample index "
        f"{first_bad_idx}: vibration_strength_db",
    )


def _format_duration(seconds: float) -> str:
    total = max(0.0, round(float(seconds), 1)) if isfinite(seconds) else 0.0
    minutes = int(total // 60)
    rem = total - (minutes * 60)
    return f"{minutes:02d}:{rem:04.1f}"


def _percent_missing(samples: list[Sample], key: str) -> float:
    if not samples:
        return 100.0
    missing = sum(1 for sample in samples if sample.get(key) in (None, ""))
    return (missing / len(samples)) * 100.0


def _mean_variance(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    n = len(values)
    m = sum(values) / n
    if n < 2:
        return m, 0.0
    var = sum((v - m) ** 2 for v in values) / (n - 1)
    return m, var


class _OutlierSummary(TypedDict):
    """Return type of :func:`_outlier_summary`."""

    count: int
    outlier_count: int
    outlier_pct: float
    lower_bound: float | None
    upper_bound: float | None


def _outlier_summary(values: list[float]) -> _OutlierSummary:
    if not values:
        return {
            "count": 0,
            "outlier_count": 0,
            "outlier_pct": 0.0,
            "lower_bound": None,
            "upper_bound": None,
        }
    sorted_vals = sorted(values)
    q1 = float(percentile(sorted_vals, 0.25))
    q3 = float(percentile(sorted_vals, 0.75))
    iqr = max(0.0, q3 - q1)
    low = q1 - (1.5 * iqr)
    high = q3 + (1.5 * iqr)
    outlier_count = sum(1 for v in sorted_vals if v < low or v > high)
    return {
        "count": len(sorted_vals),
        "outlier_count": outlier_count,
        "outlier_pct": (outlier_count / len(sorted_vals)) * 100.0,
        "lower_bound": low,
        "upper_bound": high,
    }


def _speed_bin_label(kmh: float) -> str:
    if not isfinite(kmh) or kmh < 0:
        kmh = 0.0
    low = int(kmh // SPEED_BIN_WIDTH_KMH) * SPEED_BIN_WIDTH_KMH
    high = low + SPEED_BIN_WIDTH_KMH
    return f"{low}-{high} km/h"


def _speed_bin_sort_key(label: str) -> int:
    head = label.split(" ", 1)[0]
    low_text = head.split("-", 1)[0]
    try:
        return int(low_text)
    except ValueError:
        return 0


def _amplitude_weighted_speed_window(
    speeds: list[float],
    amplitudes: list[float],
) -> tuple[float | None, float | None]:
    """Return the dominant amplitude-weighted speed bin window.

    Inputs are expected to be parallel observations for the same phenomenon.
    """
    bin_weight: dict[str, float] = defaultdict(float)
    for speed, amp in zip(speeds, amplitudes, strict=False):
        speed_val = _as_float(speed)
        amp_val = _as_float(amp)
        if speed_val is None or speed_val <= 0 or amp_val is None or amp_val <= 0:
            continue
        bin_weight[_speed_bin_label(speed_val)] += amp_val

    if not bin_weight:
        return (None, None)

    strongest_bin = max(
        bin_weight.items(),
        key=lambda item: (item[1], _speed_bin_sort_key(item[0])),
    )[0]
    low_kmh = float(_speed_bin_sort_key(strongest_bin))
    return (low_kmh, low_kmh + float(SPEED_BIN_WIDTH_KMH))


def _speed_stats(speed_values: list[float]) -> SpeedStats:
    if not speed_values:
        return {
            "min_kmh": None,
            "max_kmh": None,
            "mean_kmh": None,
            "stddev_kmh": None,
            "range_kmh": None,
            "steady_speed": False,
        }
    vmin = min(speed_values)
    vmax = max(speed_values)
    vmean, var = _mean_variance(speed_values)
    stddev = sqrt(var) if var is not None else 0.0
    vrange = max(0.0, vmax - vmin)
    return {
        "min_kmh": vmin,
        "max_kmh": vmax,
        "mean_kmh": vmean,
        "stddev_kmh": stddev,
        "range_kmh": vrange,
        "steady_speed": stddev < STEADY_SPEED_STDDEV_KMH and vrange < STEADY_SPEED_RANGE_KMH,
    }


def _speed_stats_by_phase(
    samples: list[Sample],
    per_sample_phases: Sequence[PhaseLabel],
) -> dict[str, PhaseSpeedStats]:
    """Compute speed statistics broken down by driving phase.

    Returns a dict mapping each phase label (string) to the same structure as
    ``_speed_stats()`` extended with a ``sample_count`` key for the total
    number of samples assigned to that phase (regardless of speed availability).
    """
    phase_speeds: dict[str, list[float]] = defaultdict(list)
    phase_sample_counts: dict[str, int] = defaultdict(int)
    for sample, phase in zip(samples, per_sample_phases, strict=True):
        phase_key = str(phase)
        phase_sample_counts[phase_key] += 1
        speed = _as_float(sample.get("speed_kmh"))
        if speed is not None and speed > 0:
            phase_speeds[phase_key].append(speed)
    result: dict[str, PhaseSpeedStats] = {}
    for phase_key in phase_sample_counts:
        stats = dict(_speed_stats(phase_speeds.get(phase_key, [])))
        stats["sample_count"] = phase_sample_counts[phase_key]
        result[phase_key] = cast("PhaseSpeedStats", stats)
    return result


def _sensor_limit_g(sensor_model: object) -> float | None:
    if not isinstance(sensor_model, str):
        return None
    if "adxl345" in sensor_model.lower():
        return 16.0
    return None


def _tire_reference_from_metadata(metadata: MetadataDict) -> tuple[float | None, str | None]:
    direct = _as_float(metadata.get("tire_circumference_m"))
    if direct is not None and direct > 0:
        return direct, "metadata.tire_circumference_m"

    derived = tire_circumference_m_from_spec(
        _as_float(metadata.get("tire_width_mm")),
        _as_float(metadata.get("tire_aspect_pct")),
        _as_float(metadata.get("rim_in")),
        deflection_factor=_as_float(metadata.get("tire_deflection_factor")),
    )
    if derived is not None and derived > 0:
        return float(derived), "derived_from_tire_dimensions"
    return None, None


def _effective_engine_rpm(
    sample: Sample,
    metadata: MetadataDict,
    tire_circumference_m: float | None,
) -> tuple[float | None, str]:
    measured = _as_float(sample.get("engine_rpm"))
    if measured is not None and measured > 0:
        return measured, str(sample.get("engine_rpm_source") or "measured")

    estimated_in_sample = _as_float(sample.get("engine_rpm_estimated"))
    if estimated_in_sample is not None and estimated_in_sample > 0:
        return estimated_in_sample, "estimated_from_speed_and_ratios"

    speed_kmh = _as_float(sample.get("speed_kmh"))
    final_drive_ratio = _as_float(sample.get("final_drive_ratio")) or _as_float(
        metadata.get("final_drive_ratio"),
    )
    gear_val = _as_float(sample.get("gear"))
    gear_ratio = gear_val if gear_val is not None else _as_float(metadata.get("current_gear_ratio"))
    if (
        speed_kmh is None
        or speed_kmh <= 0
        or tire_circumference_m is None
        or tire_circumference_m <= 0
        or final_drive_ratio is None
        or final_drive_ratio <= 0
        or gear_ratio is None
        or gear_ratio <= 0
    ):
        return None, "missing"

    whz = wheel_hz_from_speed_kmh(speed_kmh, tire_circumference_m)
    if whz is None:
        return None, "missing"
    rpm = engine_rpm_from_wheel_hz(whz, final_drive_ratio, gear_ratio)
    if rpm is None:
        return None, "missing"
    return float(rpm), "estimated_from_speed_and_ratios"


def _load_run(path: Path) -> tuple[JsonObject, list[JsonObject], list[str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() != ".jsonl":
        raise ValueError(f"Unsupported run format for report: {path.name}")
    run_data = read_jsonl_run(path)
    return dict(run_data.metadata), list(run_data.samples), []


def _primary_vibration_strength_db(sample: Sample) -> float | None:
    value = _as_float(sample.get("vibration_strength_db"))
    return float(value) if value is not None else None


def _corr_abs(x_vals: list[float], y_vals: list[float]) -> float | None:
    if len(x_vals) != len(y_vals) or len(x_vals) < 3:
        return None
    n = len(x_vals)
    mx = sum(x_vals) / n
    my = sum(y_vals) / n
    cov = 0.0
    sx_sq = 0.0
    sy_sq = 0.0
    for x, y in zip(x_vals, y_vals, strict=False):
        dx = x - mx
        dy = y - my
        cov += dx * dy
        sx_sq += dx * dx
        sy_sq += dy * dy
    sx = sqrt(sx_sq)
    sy = sqrt(sy_sq)
    if sx <= 1e-9 or sy <= 1e-9:
        return None
    result = abs(cov / (sx * sy))
    return result if isfinite(result) else None


def _sample_top_peaks(sample: Sample) -> list[tuple[float, float]]:
    top_peaks = sample.get("top_peaks")
    out: list[tuple[float, float]] = []
    if isinstance(top_peaks, list):
        for peak in top_peaks[:8]:
            if not isinstance(peak, dict):
                continue
            hz = _as_float(peak.get("hz"))
            amp = _as_float(peak.get("amp"))
            if hz is None or amp is None or hz <= 0:
                continue
            # Defence-in-depth: skip sub-road-resonance frequencies that may
            # exist in old recorded run data (new data is filtered at the FFT
            # level via ``spectrum_min_hz``).
            if hz < MIN_ANALYSIS_FREQ_HZ:
                continue
            out.append((hz, amp))
    return out


def _corr_abs_clamped(x: list[float], y: list[float]) -> float | None:
    """Absolute Pearson correlation, clamped to [0, 1].

    Delegates to ``_corr_abs`` and clamps the result to handle
    floating-point overshoot (e.g. 1.0000000000000002) or undershoot.
    Both bounds are applied: ``abs()`` in ``_corr_abs`` guarantees
    non-negative values in theory, but the explicit lower clamp protects
    against hypothetical floating-point edge cases.
    """
    raw = _corr_abs(x, y)
    if raw is None:
        return None
    return max(0.0, min(1.0, raw))


def _estimate_strength_floor_amp_g(sample: Sample) -> float | None:
    """Estimate per-sample floor amplitude.

    Policy: accept strictly positive ``strength_floor_amp_g``; otherwise
    fall back to P20 of strictly positive top-peak amplitudes when at least
    three peaks are available (keeps floor estimation aligned with existing
    run-baseline guards and avoids unstable sparse-peak fallbacks).
    """
    floor_amp = _as_float(sample.get("strength_floor_amp_g"))
    if floor_amp is not None and floor_amp > 0:
        return float(floor_amp)
    peak_amps = sorted(amp for _hz, amp in _sample_top_peaks(sample) if amp > 0)
    if len(peak_amps) < 3:
        return None
    floor_from_peaks = float(percentile(peak_amps, 0.20))
    return float(floor_from_peaks) if floor_from_peaks > 0 else None


def _run_noise_baseline_g(samples: list[Sample]) -> float | None:
    """Estimate run-level noise baseline as median of per-sample floor estimates.

    Per-sample floor uses ``strength_floor_amp_g`` when available; otherwise it
    falls back to P20 of that sample's top-peak amplitudes.
    """
    floors: list[float] = []
    for sample in samples:
        floor_amp = _estimate_strength_floor_amp_g(sample)
        if floor_amp is not None:
            floors.append(floor_amp)
    if not floors:
        return None
    return float(percentile(sorted(floors), 0.50))


def _effective_baseline_floor(
    run_noise_baseline_g: float | None,
    *,
    extra_fallback: float | None = None,
) -> float:
    """Return a safe noise-floor value for SNR computations.

    Resolution order: *run_noise_baseline_g* → *extra_fallback* → 0.0,
    clamped to at least :data:`MEMS_NOISE_FLOOR_G`.
    """
    val = (
        run_noise_baseline_g
        if run_noise_baseline_g is not None
        else (extra_fallback if extra_fallback is not None else 0.0)
    )
    return float(max(float(MEMS_NOISE_FLOOR_G), float(val)))


def _location_label(sample: Sample, *, lang: str = "en") -> str:
    """Return a stable language-neutral location label for the sample.

    NOTE: This is used as a **grouping key** across the data pipeline, so it
    must be language-invariant.  Translation to the report language happens at
    render time in the PDF builder / template layer.
    """
    # Prefer structured location code (from SensorConfig) if available
    location_code = str(sample.get("location") or "").strip()
    if location_code:
        translated = _label_for_code(location_code)
        return str(translated) if translated else location_code

    client_name_raw = str(sample.get("client_name") or "").strip()
    if client_name_raw:
        return client_name_raw
    client_id_raw = str(sample.get("client_id") or "").strip()
    if client_id_raw:
        return f"Sensor \u2026{client_id_raw[-4:]}"
    return "Unknown sensor"


def _locations_connected_throughout_run(samples: list[Sample], *, lang: str = "en") -> set[str]:
    by_location_times: dict[str, set[float]] = defaultdict(set)
    all_times: list[float] = []

    for sample in samples:
        if not isinstance(sample, dict):
            continue
        location = _location_label(sample, lang=lang)
        if not location:
            continue
        t_s = _as_float(sample.get("t_s"))
        if t_s is None:
            continue
        by_location_times[location].add(t_s)
        all_times.append(t_s)

    if not by_location_times:
        return set()
    if not all_times:
        return set(by_location_times.keys())

    run_start = min(all_times)
    run_end = max(all_times)
    run_duration = max(0.0, run_end - run_start)
    edge_tolerance_s = max(0.75, min(3.0, run_duration * 0.08))

    max_count = max((len(times) for times in by_location_times.values()), default=0)
    min_required_count = int(max_count * 0.80) if max_count >= 5 else 1

    connected: set[str] = set()
    for location, times in by_location_times.items():
        if not times:
            continue
        if len(times) < min_required_count:
            continue
        sorted_times = sorted(times)
        loc_start = sorted_times[0]
        loc_end = sorted_times[-1]
        if loc_start <= (run_start + edge_tolerance_s) and loc_end >= (run_end - edge_tolerance_s):
            max_internal_gap = max(
                (curr - prev for prev, curr in zip(sorted_times, sorted_times[1:], strict=False)),
                default=0.0,
            )
            if max_internal_gap <= (edge_tolerance_s * 2.0):
                connected.add(location)

    return connected


def _weighted_percentile(
    pairs: list[tuple[float, float]],
    q: float,
) -> float | None:
    """Return the *q*-th weighted percentile from *(value, weight)* pairs.

    *q* is clamped to [0, 1].  Pairs with non-positive weights are ignored.
    Returns ``None`` when no valid pairs remain.
    """
    if not pairs:
        return None
    q_clamped = max(0.0, min(1.0, q))
    filtered = [(value, weight) for value, weight in pairs if weight > 0]
    if not filtered:
        return None
    ordered = sorted(filtered)
    total_weight = sum(weight for _, weight in ordered)
    if total_weight <= 0:
        return None
    threshold = q_clamped * total_weight
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return ordered[-1][0]


def counter_delta(counter_values: list[float]) -> int:
    """Compute cumulative positive delta from a list of monotonic counter values.

    Returns the total increment, ignoring any decreases (which indicate
    counter resets).  Accepts ``list[float]`` — callers with timestamped
    tuples should sort and extract the value column before calling.
    """
    if len(counter_values) < 2:
        return 0
    delta = 0.0
    prev = float(counter_values[0])
    for current_raw in counter_values[1:]:
        current = float(current_raw)
        delta += max(0.0, current - prev)
        prev = current
    return int(delta)
