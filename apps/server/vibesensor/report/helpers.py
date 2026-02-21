# ruff: noqa: E501
"""Low-level helpers, constants, and utility functions for report analysis."""

from __future__ import annotations

from collections import defaultdict
from math import sqrt
from pathlib import Path
from statistics import mean
from typing import Any

from vibesensor_core.vibration_strength import percentile

from ..analysis_settings import (
    engine_rpm_from_wheel_hz,
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_kmh,
)
from ..constants import WEAK_SPATIAL_DOMINANCE_THRESHOLD
from ..report_i18n import normalize_lang
from ..report_i18n import tr as _tr
from ..runlog import as_float_or_none as _as_float
from ..runlog import read_jsonl_run

SPEED_BIN_WIDTH_KMH = 10
SPEED_COVERAGE_MIN_PCT = 35.0
SPEED_MIN_POINTS = 8

ORDER_TOLERANCE_REL = 0.08
ORDER_TOLERANCE_MIN_HZ = 0.5
ORDER_MIN_MATCH_POINTS = 4
ORDER_MIN_COVERAGE_POINTS = 6
ORDER_MIN_CONFIDENCE = 0.25
ORDER_CONSTANT_SPEED_MIN_MATCH_RATE = 0.55
CONSTANT_SPEED_STDDEV_KMH = 0.5
STEADY_SPEED_STDDEV_KMH = 2.0
STEADY_SPEED_RANGE_KMH = 8.0


def weak_spatial_dominance_threshold(location_count: int | None) -> float:
    """Return adaptive dominance threshold for weak spatial separation.

    Baseline is the historical 1.2 ratio for two locations. For larger sensor
    sets, we require stronger separation (+10% per additional location) because
    chance ties become more likely as the number of compared locations grows.
    """
    if location_count is None:
        return WEAK_SPATIAL_DOMINANCE_THRESHOLD
    n_locations = max(2, int(location_count))
    return WEAK_SPATIAL_DOMINANCE_THRESHOLD * (1.0 + (0.1 * (n_locations - 2)))


def _validate_required_strength_metrics(samples: list[dict[str, Any]]) -> None:
    valid_samples = 0
    first_missing_index: int | None = None
    first_missing_fields: list[str] = []
    for idx, sample in enumerate(samples):
        missing: list[str] = []
        if _as_float(sample.get("vibration_strength_db")) is None:
            missing.append("vibration_strength_db")
        if not missing:
            valid_samples += 1
            continue
        if first_missing_index is None:
            first_missing_index = idx
            first_missing_fields = missing

    if samples and valid_samples == 0:
        fields = ", ".join(first_missing_fields)
        idx = first_missing_index if first_missing_index is not None else 0
        raise ValueError(
            f"Missing required precomputed strength metrics in sample index {idx}: {fields}"
        )


def _format_duration(seconds: float) -> str:
    total = max(0.0, float(seconds))
    minutes = int(total // 60)
    rem = total - (minutes * 60)
    return f"{minutes:02d}:{rem:04.1f}"


def _required_text(value: object, consequence: str, lang: object = "en") -> str:
    if value in (None, "", []):
        return _tr(lang, "MISSING_CONSEQUENCE", consequence=consequence)
    return str(value)


def _text(lang: object, en_text: str, nl_text: str) -> str:
    return nl_text if normalize_lang(lang) == "nl" else en_text


def _percent_missing(samples: list[dict[str, Any]], key: str) -> float:
    if not samples:
        return 100.0
    missing = sum(1 for sample in samples if sample.get(key) in (None, ""))
    return (missing / len(samples)) * 100.0


def _mean_variance(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    m = mean(values)
    var = sum((v - m) ** 2 for v in values) / len(values)
    return m, var


def _outlier_summary(values: list[float]) -> dict[str, object]:
    if not values:
        return {
            "count": 0,
            "outlier_count": 0,
            "outlier_pct": 0.0,
            "lower_bound": None,
            "upper_bound": None,
        }
    sorted_vals = sorted(values)
    q1 = percentile(sorted_vals, 0.25)
    q3 = percentile(sorted_vals, 0.75)
    iqr = max(0.0, q3 - q1)
    low = q1 - (1.5 * iqr)
    high = q3 + (1.5 * iqr)
    outliers = [v for v in sorted_vals if v < low or v > high]
    return {
        "count": len(sorted_vals),
        "outlier_count": len(outliers),
        "outlier_pct": (len(outliers) / len(sorted_vals)) * 100.0,
        "lower_bound": low,
        "upper_bound": high,
    }


def _speed_bin_label(kmh: float) -> str:
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


def _speed_stats(speed_values: list[float]) -> dict[str, float | None]:
    if not speed_values:
        return {
            "min_kmh": None,
            "max_kmh": None,
            "mean_kmh": None,
            "stddev_kmh": None,
            "range_kmh": None,
            "steady_speed": True,
        }
    vmin = min(speed_values)
    vmax = max(speed_values)
    vmean, var = _mean_variance(speed_values)
    stddev = sqrt(var)
    vrange = max(0.0, vmax - vmin)
    return {
        "min_kmh": vmin,
        "max_kmh": vmax,
        "mean_kmh": vmean,
        "stddev_kmh": stddev,
        "range_kmh": vrange,
        "steady_speed": stddev < STEADY_SPEED_STDDEV_KMH or vrange < STEADY_SPEED_RANGE_KMH,
    }


def _sensor_limit_g(sensor_model: object) -> float | None:
    if not isinstance(sensor_model, str):
        return None
    if "adxl345" in sensor_model.lower():
        return 16.0
    return None


def _tire_reference_from_metadata(metadata: dict[str, Any]) -> tuple[float | None, str | None]:
    direct = _as_float(metadata.get("tire_circumference_m"))
    if direct is not None and direct > 0:
        return direct, "metadata.tire_circumference_m"

    derived = tire_circumference_m_from_spec(
        _as_float(metadata.get("tire_width_mm")),
        _as_float(metadata.get("tire_aspect_pct")),
        _as_float(metadata.get("rim_in")),
    )
    if derived is not None and derived > 0:
        return derived, "derived_from_tire_dimensions"
    return None, None


def _effective_engine_rpm(
    sample: dict[str, Any],
    metadata: dict[str, Any],
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
        metadata.get("final_drive_ratio")
    )
    gear_ratio = _as_float(sample.get("gear")) or _as_float(metadata.get("current_gear_ratio"))
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
    return engine_rpm_from_wheel_hz(whz, final_drive_ratio, gear_ratio), (
        "estimated_from_speed_and_ratios"
    )


def _load_run(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() != ".jsonl":
        raise ValueError(f"Unsupported run format for report: {path.name}")
    run_data = read_jsonl_run(path)
    return dict(run_data.metadata), list(run_data.samples), []


def _primary_vibration_strength_db(sample: dict[str, Any]) -> float | None:
    return _as_float(sample.get("vibration_strength_db"))


def _corr_abs(x_vals: list[float], y_vals: list[float]) -> float | None:
    if len(x_vals) != len(y_vals) or len(x_vals) < 3:
        return None
    mx = mean(x_vals)
    my = mean(y_vals)
    cov = sum((x - mx) * (y - my) for x, y in zip(x_vals, y_vals, strict=False))
    sx = sqrt(sum((x - mx) ** 2 for x in x_vals))
    sy = sqrt(sum((y - my) ** 2 for y in y_vals))
    if sx <= 1e-9 or sy <= 1e-9:
        return None
    return abs(cov / (sx * sy))


def _sample_top_peaks(sample: dict[str, Any]) -> list[tuple[float, float]]:
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
            out.append((hz, amp))
    return out


def _run_noise_baseline_g(samples: list[dict[str, Any]]) -> float | None:
    """Estimate run-level noise baseline as median of per-sample floor estimates.

    Per-sample floor uses ``strength_floor_amp_g`` when available; otherwise it
    falls back to P20 of that sample's top-peak amplitudes.
    """
    floors: list[float] = []
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        floor_amp = _as_float(sample.get("strength_floor_amp_g"))
        if floor_amp is not None and floor_amp > 0:
            floors.append(float(floor_amp))
            continue
        peak_amps = [amp for _hz, amp in _sample_top_peaks(sample) if amp > 0]
        if len(peak_amps) < 3:
            continue
        peak_amps_sorted = sorted(peak_amps)
        floor_from_peaks = (
            percentile(peak_amps_sorted, 0.20)
            if len(peak_amps_sorted) >= 2
            else peak_amps_sorted[0]
        )
        if floor_from_peaks > 0:
            floors.append(float(floor_from_peaks))
    if not floors:
        return None
    floors_sorted = sorted(floors)
    return percentile(floors_sorted, 0.50) if len(floors_sorted) >= 2 else floors_sorted[0]


def _location_label(sample: dict[str, Any], *, lang: object = "en") -> str:
    """Return a stable English location label for the sample.

    NOTE: This is used as a **grouping key** across the data pipeline, so it
    must be language-invariant.  Translation to the report language happens at
    render time in the PDF builder / template layer.
    """
    # Prefer structured location code (from SensorConfig) if available
    from ..locations import label_for_code as _label_for_code  # local to avoid circular import

    location_code = str(sample.get("location") or "").strip()
    if location_code:
        human = _label_for_code(location_code)
        if human:
            return human
        # If code is not in our table but non-empty, use it directly
        return location_code

    client_name_raw = str(sample.get("client_name") or "").strip()
    if client_name_raw:
        return client_name_raw
    client_id_raw = str(sample.get("client_id") or "").strip()
    if client_id_raw:
        return _tr(lang, "SENSOR_ID_SUFFIX", sensor_id=client_id_raw[-4:])
    return _tr(lang, "UNLABELED_SENSOR")


def _locations_connected_throughout_run(
    samples: list[dict[str, Any]], *, lang: object = "en"
) -> set[str]:
    by_location_times: dict[str, list[float]] = defaultdict(list)
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
        by_location_times[location].append(t_s)
        all_times.append(t_s)

    if not by_location_times:
        return set()
    if not all_times:
        return set(by_location_times.keys())

    run_start = min(all_times)
    run_end = max(all_times)
    run_duration = max(0.0, run_end - run_start)
    edge_tolerance_s = max(0.75, min(3.0, run_duration * 0.08))

    counts_by_location = {location: len(times) for location, times in by_location_times.items()}
    max_count = max(counts_by_location.values()) if counts_by_location else 0
    min_required_count = int(max_count * 0.80) if max_count >= 5 else 1

    connected: set[str] = set()
    for location, times in by_location_times.items():
        if not times:
            continue
        if len(times) < min_required_count:
            continue
        loc_start = min(times)
        loc_end = max(times)
        if loc_start <= (run_start + edge_tolerance_s) and loc_end >= (run_end - edge_tolerance_s):
            connected.add(location)

    return connected if connected else set(by_location_times.keys())
