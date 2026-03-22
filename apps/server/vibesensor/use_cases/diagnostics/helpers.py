"""Low-level helpers, constants, and utility functions for report analysis."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from vibesensor.domain import OrderReferenceSpec, TireSpec
from vibesensor.shared.boundaries.run_log import read_jsonl_run
from vibesensor.shared.constants import (
    KMH_TO_MPS,
    MEMS_NOISE_FLOOR_G,
    MIN_ANALYSIS_FREQ_HZ,
    SECONDS_PER_MINUTE,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.locations import label_for_code as _label_for_code
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.use_cases.diagnostics._types import (
    AnalysisSampleInput,
    Sample,
    ensure_analysis_sample,
)
from vibesensor.vibration_strength import percentile


def _validate_required_strength_metrics(samples: Sequence[AnalysisSampleInput]) -> None:
    typed_samples = [ensure_analysis_sample(sample) for sample in samples]
    if not typed_samples:
        return
    first_bad_idx: int | None = None
    for idx, sample in enumerate(typed_samples):
        if sample.vibration_strength_db is not None:
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


def _sensor_limit_g(sensor_model: object) -> float | None:
    if not isinstance(sensor_model, str):
        return None
    if "adxl345" in sensor_model.lower():
        return 16.0
    return None


def _tire_reference_from_metadata(metadata: JsonObject) -> tuple[float | None, str | None]:
    spec = _order_reference_spec_from_context(metadata)
    if spec is not None and spec.supports_wheel_reference:
        return spec.tire_circumference_m, "order_reference_spec"

    direct = _as_float(metadata.get("tire_circumference_m"))
    if direct is not None and direct > 0:
        return direct, "metadata.tire_circumference_m"

    _w = _as_float(metadata.get("tire_width_mm"))
    _a = _as_float(metadata.get("tire_aspect_pct"))
    _r = _as_float(metadata.get("rim_in"))
    if _w is not None and _a is not None and _r is not None:
        _df = _as_float(metadata.get("tire_deflection_factor"))
        _spec = TireSpec.from_aspects(
            {"tire_width_mm": _w, "tire_aspect_pct": _a, "rim_in": _r},
            deflection_factor=_df if _df is not None else 1.0,
        )
        if _spec is not None and _spec.circumference_m > 0:
            return _spec.circumference_m, "derived_from_tire_dimensions"
    return None, None


def _order_reference_spec_from_context(
    metadata: JsonObject,
    sample: Sample | None = None,
) -> OrderReferenceSpec | None:
    settings: dict[str, object] = dict(metadata)
    if sample is not None:
        if (final_drive_ratio := sample.final_drive_ratio) is not None:
            settings["final_drive_ratio"] = final_drive_ratio
        if (gear_ratio := sample.gear) is not None:
            settings["current_gear_ratio"] = gear_ratio
    return OrderReferenceSpec.from_settings(settings)


def _effective_engine_rpm(
    sample: AnalysisSampleInput,
    metadata: JsonObject,
    tire_circumference_m: float | None,
) -> tuple[float | None, str]:
    typed_sample = ensure_analysis_sample(sample)
    measured = typed_sample.engine_rpm
    if measured is not None and measured > 0:
        return measured, typed_sample.engine_rpm_source or "measured"

    estimated_in_sample = typed_sample.engine_rpm_estimated
    if estimated_in_sample is not None and estimated_in_sample > 0:
        return estimated_in_sample, "estimated_from_speed_and_ratios"

    speed_kmh = typed_sample.speed_kmh
    spec = _order_reference_spec_from_context(metadata, typed_sample)
    if (
        speed_kmh is not None
        and speed_kmh > 0
        and spec is not None
        and spec.supports_engine_reference
    ):
        rpm = spec.engine_rpm_from_speed_kmh(speed_kmh)
        if rpm is not None and rpm > 0:
            return rpm, "estimated_from_speed_and_ratios"

    final_drive_ratio = typed_sample.final_drive_ratio or _as_float(
        metadata.get("final_drive_ratio"),
    )
    gear_val = typed_sample.gear
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

    whz = speed_kmh * KMH_TO_MPS / tire_circumference_m
    rpm = whz * final_drive_ratio * gear_ratio * SECONDS_PER_MINUTE
    return float(rpm), "estimated_from_speed_and_ratios"


def _load_run(path: Path) -> tuple[JsonObject, list[JsonObject], list[str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() != ".jsonl":
        raise ValueError(f"Unsupported run format for report: {path.name}")
    run_data = read_jsonl_run(path)
    return dict(run_data.metadata), list(run_data.samples), []


def _primary_vibration_strength_db(sample: Sample) -> float | None:
    typed_sample = ensure_analysis_sample(sample)
    value = typed_sample.vibration_strength_db
    return float(value) if value is not None else None


def _sample_top_peaks(sample: AnalysisSampleInput) -> list[tuple[float, float]]:
    typed_sample = ensure_analysis_sample(sample)
    out: list[tuple[float, float]] = []
    for peak in typed_sample.top_peaks[:8]:
        hz = peak.hz
        amp = peak.amp
        if hz <= 0 or amp <= 0:
            continue
        # Defence-in-depth: skip sub-road-resonance frequencies that may
        # exist in old recorded run data (new data is filtered at the FFT
        # level via ``spectrum_min_hz``).
        if hz < MIN_ANALYSIS_FREQ_HZ:
            continue
        out.append((hz, amp))
    return out


def _estimate_strength_floor_amp_g(sample: AnalysisSampleInput) -> float | None:
    """Estimate per-sample floor amplitude.

    Policy: accept strictly positive ``strength_floor_amp_g``; otherwise
    fall back to P20 of strictly positive top-peak amplitudes when at least
    three peaks are available (keeps floor estimation aligned with existing
    run-baseline guards and avoids unstable sparse-peak fallbacks).
    """
    typed_sample = ensure_analysis_sample(sample)
    floor_amp = typed_sample.strength_floor_amp_g
    if floor_amp is not None and floor_amp > 0:
        return float(floor_amp)
    peak_amps = sorted(amp for _hz, amp in _sample_top_peaks(typed_sample) if amp > 0)
    if len(peak_amps) < 3:
        return None
    floor_from_peaks = float(percentile(peak_amps, 0.20))
    return float(floor_from_peaks) if floor_from_peaks > 0 else None


def _run_noise_baseline_g(samples: Sequence[AnalysisSampleInput]) -> float | None:
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


def _location_label(sample: AnalysisSampleInput, *, lang: str = "en") -> str:
    """Return a stable language-neutral location label for the sample.

    NOTE: This is used as a **grouping key** across the data pipeline, so it
    must be language-invariant.  Translation to the report language happens at
    render time in the PDF builder / template layer.
    """
    typed_sample = ensure_analysis_sample(sample)
    # Prefer structured location code (from SensorConfig) if available
    location_code = typed_sample.location.strip()
    if location_code:
        translated = _label_for_code(location_code)
        return str(translated) if translated else location_code

    client_name_raw = typed_sample.client_name.strip()
    if client_name_raw:
        return client_name_raw
    client_id_raw = typed_sample.client_id.strip()
    if client_id_raw:
        return f"Sensor \u2026{client_id_raw[-4:]}"
    return "Unknown sensor"


def _locations_connected_throughout_run(
    samples: Sequence[AnalysisSampleInput],
    *,
    lang: str = "en",
) -> set[str]:
    by_location_times: dict[str, set[float]] = defaultdict(set)
    all_times: list[float] = []

    for raw_sample in samples:
        sample = ensure_analysis_sample(raw_sample)
        location = _location_label(sample, lang=lang)
        if not location:
            continue
        t_s = sample.t_s
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
