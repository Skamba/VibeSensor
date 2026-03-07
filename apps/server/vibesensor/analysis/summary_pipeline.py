"""Focused helpers for assembling the run-summary analysis pipeline."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from vibesensor_core.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

from ..analysis_settings import tire_circumference_m_from_spec
from ..runlog import as_float_or_none as _as_float
from ..runlog import parse_iso8601
from .findings.intensity import _sensor_intensity_by_location
from .helpers import (
    MEMS_NOISE_FLOOR_G,
    PHASE_I18N_KEYS,
    SPEED_COVERAGE_MIN_PCT,
    SPEED_MIN_POINTS,
    _format_duration,
    _location_label,
    _locations_connected_throughout_run,
    _mean_variance,
    _outlier_summary,
    _percent_missing,
    _primary_vibration_strength_db,
    _sensor_limit_g,
    _speed_stats,
    counter_delta,
    weak_spatial_dominance_threshold,
)
from .order_analysis import _i18n_ref
from .phase_segmentation import DrivingPhase, PhaseSegment, segment_run_phases

# Fraction of sensor ADC limit above which a sample is considered clipping.
# 2% headroom accounts for quantization effects near the ADC rail.
_SATURATION_FRACTION = 0.98


def build_phase_timeline(
    phase_segments: list[PhaseSegment],
    findings: list[dict[str, Any]],
    *,
    min_confidence: float,
) -> list[dict[str, Any]]:
    """Build a simple phase timeline annotated with finding evidence."""
    if not phase_segments:
        return []

    finding_phases: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        if str(finding.get("finding_id", "")).startswith("REF_"):
            continue
        conf = float(finding.get("confidence_0_to_1") or 0)
        if conf < min_confidence:
            continue
        phase_ev = finding.get("phase_evidence")
        if isinstance(phase_ev, dict):
            for phase in phase_ev.get("phases_detected", []):
                finding_phases.add(str(phase))

    entries: list[dict[str, Any]] = []
    for segment in phase_segments:
        phase_val = segment.phase.value
        entries.append(
            {
                "phase": phase_val,
                "start_t_s": None if math.isnan(segment.start_t_s) else segment.start_t_s,
                "end_t_s": None if math.isnan(segment.end_t_s) else segment.end_t_s,
                "speed_min_kmh": segment.speed_min_kmh,
                "speed_max_kmh": segment.speed_max_kmh,
                "has_fault_evidence": phase_val in finding_phases,
            }
        )
    return entries


def serialize_phase_segments(phase_segments: list[PhaseSegment]) -> list[dict[str, Any]]:
    """Serialize phase segments to JSON-safe dicts."""
    return [
        {
            "phase": seg.phase.value,
            "start_idx": seg.start_idx,
            "end_idx": seg.end_idx,
            "start_t_s": (
                None
                if isinstance(seg.start_t_s, float) and math.isnan(seg.start_t_s)
                else seg.start_t_s
            ),
            "end_t_s": (
                None if isinstance(seg.end_t_s, float) and math.isnan(seg.end_t_s) else seg.end_t_s
            ),
            "speed_min_kmh": seg.speed_min_kmh,
            "speed_max_kmh": seg.speed_max_kmh,
            "sample_count": seg.sample_count,
        }
        for seg in phase_segments
    ]


def noise_baseline_db(run_noise_baseline_g: float | None) -> float | None:
    """Convert a run noise baseline amplitude in g to dB, or return None."""
    if run_noise_baseline_g is None:
        return None
    return canonical_vibration_db(
        peak_band_rms_amp_g=max(MEMS_NOISE_FLOOR_G, run_noise_baseline_g),
        floor_amp_g=MEMS_NOISE_FLOOR_G,
    )


def prepare_speed_and_phases(
    samples: list[dict[str, Any]],
) -> tuple[list[float], dict[str, Any], float, bool, list[DrivingPhase], list[PhaseSegment]]:
    """Compute speed stats and phase segmentation shared by multiple entry points."""
    speed_values = [
        speed
        for speed in (_as_float(sample.get("speed_kmh")) for sample in samples)
        if speed is not None and speed > 0
    ]
    speed_stats = _speed_stats(speed_values)
    speed_non_null_pct = (len(speed_values) / len(samples) * 100.0) if samples else 0.0
    speed_sufficient = (
        speed_non_null_pct >= SPEED_COVERAGE_MIN_PCT and len(speed_values) >= SPEED_MIN_POINTS
    )
    per_sample_phases, phase_segments = segment_run_phases(samples)
    return (
        speed_values,
        speed_stats,
        speed_non_null_pct,
        speed_sufficient,
        per_sample_phases,
        phase_segments,
    )


def compute_run_timing(
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    file_name: str,
) -> tuple[str, datetime | None, datetime | None, float]:
    """Extract run_id, start/end timestamps and duration from metadata+samples."""
    run_id = str(metadata.get("run_id") or f"run-{file_name}")
    start_ts = parse_iso8601(metadata.get("start_time_utc"))
    end_ts = parse_iso8601(metadata.get("end_time_utc"))

    if end_ts is None and samples:
        sample_max_t = max((_as_float(sample.get("t_s")) or 0.0) for sample in samples)
        if start_ts is not None:
            end_ts = start_ts + timedelta(seconds=sample_max_t)
    duration_s = 0.0
    if start_ts is not None and end_ts is not None:
        duration_s = max(0.0, (end_ts - start_ts).total_seconds())
    elif samples:
        duration_s = max((_as_float(sample.get("t_s")) or 0.0) for sample in samples)

    return run_id, start_ts, end_ts, duration_s


def compute_accel_statistics(
    samples: list[dict[str, Any]],
    sensor_model: object,
) -> dict[str, Any]:
    """Compute per-axis values, aggregate amplitude metrics, and saturation counts."""
    sensor_limit = _sensor_limit_g(sensor_model)
    sat_threshold = sensor_limit * _SATURATION_FRACTION if sensor_limit is not None else None

    _sqrt = math.sqrt
    _to_float = _as_float
    _vib_db = _primary_vibration_strength_db
    accel_x_vals: list[float] = []
    accel_y_vals: list[float] = []
    accel_z_vals: list[float] = []
    accel_mag_vals: list[float] = []
    amp_metric_values: list[float] = []
    sat_count = 0

    for sample in samples:
        _get = sample.get
        x = _to_float(_get("accel_x_g"))
        y = _to_float(_get("accel_y_g"))
        z = _to_float(_get("accel_z_g"))
        if x is not None:
            accel_x_vals.append(x)
        if y is not None:
            accel_y_vals.append(y)
        if z is not None:
            accel_z_vals.append(z)
        if x is not None and y is not None and z is not None:
            accel_mag_vals.append(_sqrt(x * x + y * y + z * z))
        if sat_threshold is not None and any(
            axis_val is not None and abs(axis_val) >= sat_threshold for axis_val in (x, y, z)
        ):
            sat_count += 1
        amp = _vib_db(sample)
        if amp is not None:
            amp_metric_values.append(amp)

    x_mean, x_var = _mean_variance(accel_x_vals)
    y_mean, y_var = _mean_variance(accel_y_vals)
    z_mean, z_var = _mean_variance(accel_z_vals)

    return {
        "accel_x_vals": accel_x_vals,
        "accel_y_vals": accel_y_vals,
        "accel_z_vals": accel_z_vals,
        "accel_mag_vals": accel_mag_vals,
        "amp_metric_values": amp_metric_values,
        "sat_count": sat_count,
        "sensor_limit": sensor_limit,
        "x_mean": x_mean,
        "x_var": x_var,
        "y_mean": y_mean,
        "y_var": y_var,
        "z_mean": z_mean,
        "z_var": z_var,
    }


def compute_frame_integrity_counts(samples: list[dict[str, Any]]) -> tuple[int, int]:
    """Compute ``(total_dropped, total_overflow)`` across all client sensors."""
    per_client_dropped: dict[str, list[float]] = defaultdict(list)
    per_client_overflow: dict[str, list[float]] = defaultdict(list)
    for sample in samples:
        client_id = str(sample.get("client_id") or "")
        if not client_id:
            continue
        dropped = _as_float(sample.get("frames_dropped_total"))
        if dropped is not None:
            per_client_dropped[client_id].append(dropped)
        overflow = _as_float(sample.get("queue_overflow_drops"))
        if overflow is not None:
            per_client_overflow[client_id].append(overflow)
    total_dropped = sum(counter_delta(values) for values in per_client_dropped.values())
    total_overflow = sum(counter_delta(values) for values in per_client_overflow.values())
    return total_dropped, total_overflow


def build_run_suitability_checks(
    *,
    steady_speed: bool,
    speed_sufficient: bool,
    sensor_ids: set[str],
    reference_complete: bool,
    sat_count: int,
    samples: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Construct the language-neutral run-suitability checklist."""
    sensor_count_sufficient = len(sensor_ids) >= 3
    speed_variation_ok = speed_sufficient and not steady_speed
    run_suitability: list[dict[str, Any]] = [
        {
            "check": "SUITABILITY_CHECK_SPEED_VARIATION",
            "check_key": "SUITABILITY_CHECK_SPEED_VARIATION",
            "state": "pass" if speed_variation_ok else "warn",
            "explanation": (
                _i18n_ref("SUITABILITY_SPEED_VARIATION_PASS")
                if speed_variation_ok
                else _i18n_ref("SUITABILITY_SPEED_VARIATION_WARN")
            ),
        },
        {
            "check": "SUITABILITY_CHECK_SENSOR_COVERAGE",
            "check_key": "SUITABILITY_CHECK_SENSOR_COVERAGE",
            "state": "pass" if sensor_count_sufficient else "warn",
            "explanation": (
                _i18n_ref("SUITABILITY_SENSOR_COVERAGE_PASS")
                if sensor_count_sufficient
                else _i18n_ref("SUITABILITY_SENSOR_COVERAGE_WARN")
            ),
        },
        {
            "check": "SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
            "check_key": "SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
            "state": "pass" if reference_complete else "warn",
            "explanation": (
                _i18n_ref("SUITABILITY_REFERENCE_COMPLETENESS_PASS")
                if reference_complete
                else _i18n_ref("SUITABILITY_REFERENCE_COMPLETENESS_WARN")
            ),
        },
        {
            "check": "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
            "check_key": "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
            "state": "pass" if sat_count == 0 else "warn",
            "explanation": (
                _i18n_ref("SUITABILITY_SATURATION_PASS")
                if sat_count == 0
                else _i18n_ref("SUITABILITY_SATURATION_WARN", sat_count=sat_count)
            ),
        },
    ]

    total_dropped, total_overflow = compute_frame_integrity_counts(samples)
    frame_issues = total_dropped + total_overflow
    run_suitability.append(
        {
            "check": "SUITABILITY_CHECK_FRAME_INTEGRITY",
            "check_key": "SUITABILITY_CHECK_FRAME_INTEGRITY",
            "state": "pass" if frame_issues == 0 else "warn",
            "explanation": (
                _i18n_ref("SUITABILITY_FRAME_INTEGRITY_PASS")
                if frame_issues == 0
                else _i18n_ref(
                    "SUITABILITY_FRAME_INTEGRITY_WARN",
                    total_dropped=total_dropped,
                    total_overflow=total_overflow,
                )
            ),
        }
    )
    return run_suitability


def compute_reference_completeness(metadata: dict[str, Any]) -> bool:
    """Return True when enough reference metadata is present for order analysis."""
    return bool(
        _as_float(metadata.get("raw_sample_rate_hz"))
        and (
            _as_float(metadata.get("tire_circumference_m"))
            or tire_circumference_m_from_spec(
                _as_float(metadata.get("tire_width_mm")),
                _as_float(metadata.get("tire_aspect_pct")),
                _as_float(metadata.get("rim_in")),
            )
        )
        and (
            _as_float(metadata.get("engine_rpm"))
            or (
                _as_float(metadata.get("final_drive_ratio"))
                and _as_float(metadata.get("current_gear_ratio"))
            )
        )
    )


def build_data_quality_dict(
    samples: list[dict[str, Any]],
    speed_values: list[float],
    speed_stats: dict[str, Any],
    speed_non_null_pct: float,
    accel_stats: dict[str, Any],
    amp_metric_values: list[float],
) -> dict[str, Any]:
    """Build the ``data_quality`` sub-dict for the run summary."""
    return {
        "required_missing_pct": {
            "t_s": _percent_missing(samples, "t_s"),
            "speed_kmh": _percent_missing(samples, "speed_kmh"),
            "accel_x": _percent_missing(samples, "accel_x_g"),
            "accel_y": _percent_missing(samples, "accel_y_g"),
            "accel_z": _percent_missing(samples, "accel_z_g"),
        },
        "speed_coverage": {
            "non_null_pct": speed_non_null_pct,
            "min_kmh": min(speed_values) if speed_values else None,
            "max_kmh": max(speed_values) if speed_values else None,
            "mean_kmh": speed_stats.get("mean_kmh"),
            "stddev_kmh": speed_stats.get("stddev_kmh"),
            "count_non_null": len(speed_values),
        },
        "accel_sanity": {
            "x_mean": accel_stats["x_mean"],
            "x_variance": accel_stats["x_var"],
            "y_mean": accel_stats["y_mean"],
            "y_variance": accel_stats["y_var"],
            "z_mean": accel_stats["z_mean"],
            "z_variance": accel_stats["z_var"],
            "sensor_limit": accel_stats["sensor_limit"],
            "saturation_count": accel_stats["sat_count"],
        },
        "outliers": {
            "accel_magnitude": _outlier_summary(accel_stats["accel_mag_vals"]),
            "amplitude_metric": _outlier_summary(amp_metric_values),
        },
    }


def build_sensor_analysis(
    *,
    samples: list[dict[str, Any]],
    language: str,
    per_sample_phases: list[DrivingPhase],
) -> tuple[list[str], set[str], list[dict[str, Any]]]:
    """Build sensor location lists and intensity rows from analysed samples."""
    sensor_locations = sorted(
        {
            label
            for sample in samples
            if isinstance(sample, dict) and (label := _location_label(sample, lang=language))
        }
    )
    connected_locations = _locations_connected_throughout_run(samples, lang=language)
    sensor_intensity_by_location = _sensor_intensity_by_location(
        samples,
        include_locations=set(sensor_locations),
        lang=language,
        connected_locations=connected_locations,
        per_sample_phases=per_sample_phases,
    )
    return sensor_locations, connected_locations, sensor_intensity_by_location


def summarize_origin(
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the most-likely-origin summary from ranked diagnostic findings."""
    if not findings:
        return {
            "location": "unknown",
            "alternative_locations": [],
            "source": "unknown",
            "dominance_ratio": None,
            "weak_spatial_separation": True,
            "explanation": _i18n_ref("ORIGIN_NO_RANKED_FINDING_AVAILABLE"),
        }
    top = findings[0]
    primary_location = str(top.get("strongest_location") or "").strip() or "unknown"
    alternative_locations: list[str] = []
    hotspot = top.get("location_hotspot")
    if isinstance(hotspot, dict):
        for candidate in hotspot.get("ambiguous_locations", []):
            loc = str(candidate or "").strip()
            if loc and loc != primary_location and loc not in alternative_locations:
                alternative_locations.append(loc)
        second_location = str(hotspot.get("second_location") or "").strip()
        if (
            second_location
            and second_location != primary_location
            and second_location not in alternative_locations
        ):
            alternative_locations.append(second_location)

    source = str(top.get("suspected_source") or "unknown")
    dominance = _as_float(top.get("dominance_ratio"))
    location_count = _as_float(top.get("location_count"))
    if location_count is None and isinstance(hotspot, dict):
        location_count = _as_float(hotspot.get("location_count"))
    adaptive_weak_spatial_threshold = weak_spatial_dominance_threshold(
        int(location_count) if location_count else None
    )
    weak = bool(top.get("weak_spatial_separation")) or (
        dominance is not None and dominance < adaptive_weak_spatial_threshold
    )

    if len(findings) >= 2:
        second = findings[1]
        second_loc = str(second.get("strongest_location") or "").strip()
        second_conf = _as_float(second.get("confidence_0_to_1")) or 0.0
        top_conf = _as_float(top.get("confidence_0_to_1")) or 0.0
        if (
            second_loc
            and primary_location
            and second_loc != primary_location
            and top_conf > 0
            and second_conf / top_conf >= 0.7
        ):
            weak = True
            if second_loc not in alternative_locations:
                alternative_locations.append(second_loc)

    location = primary_location
    if weak and dominance is not None and dominance < adaptive_weak_spatial_threshold:
        display_locations = [primary_location, *alternative_locations]
        location = " / ".join(
            [
                candidate
                for idx, candidate in enumerate(display_locations)
                if candidate and candidate not in display_locations[:idx]
            ]
        )

    speed_band = str(top.get("strongest_speed_band") or "")
    explanation_parts: list[object] = [
        _i18n_ref(
            "ORIGIN_EXPLANATION_FINDING_1",
            source=source,
            speed_band=speed_band or "unknown",
            location=location,
            dominance=f"{dominance:.2f}x" if dominance is not None else "n/a",
        ),
    ]
    if weak:
        explanation_parts.append(_i18n_ref("WEAK_SPATIAL_SEPARATION_INSPECT_NEARBY"))
    dominant_phase = str(top.get("dominant_phase") or "").strip()
    if dominant_phase and dominant_phase in PHASE_I18N_KEYS:
        explanation_parts.append(_i18n_ref("ORIGIN_PHASE_ONSET_NOTE", phase=dominant_phase))

    explanation = explanation_parts[0] if len(explanation_parts) == 1 else explanation_parts
    return {
        "location": location,
        "alternative_locations": alternative_locations,
        "source": source,
        "dominance_ratio": dominance,
        "weak_spatial_separation": weak,
        "speed_band": speed_band or None,
        "dominant_phase": dominant_phase or None,
        "explanation": explanation,
    }


def build_summary_payload(
    *,
    file_name: str,
    run_id: str,
    samples: list[dict[str, Any]],
    duration_s: float,
    language: str,
    metadata: dict[str, Any],
    raw_sample_rate_hz: float | None,
    speed_breakdown: list[dict[str, Any]],
    phase_speed_breakdown: list[dict[str, Any]],
    phase_segments: list[PhaseSegment],
    run_noise_baseline_g: float | None,
    speed_breakdown_skipped_reason: object,
    findings: list[dict[str, Any]],
    top_causes: list[dict[str, Any]],
    most_likely_origin: dict[str, Any],
    test_plan: list[dict[str, Any]],
    phase_timeline: list[dict[str, Any]],
    speed_stats: dict[str, Any],
    speed_stats_by_phase: dict[str, Any],
    phase_info: dict[str, Any],
    sensor_locations: list[str],
    connected_locations: set[str],
    sensor_intensity_by_location: list[dict[str, Any]],
    run_suitability: list[dict[str, Any]],
    speed_values: list[float],
    speed_non_null_pct: float,
    accel_stats: dict[str, Any],
    amp_metric_values: list[float],
) -> dict[str, Any]:
    """Assemble the final summary payload from already-computed artifacts."""
    return {
        "file_name": file_name,
        "run_id": run_id,
        "rows": len(samples),
        "duration_s": duration_s,
        "record_length": _format_duration(duration_s),
        "lang": language,
        "report_date": metadata.get("end_time_utc") or metadata.get("report_date"),
        "start_time_utc": metadata.get("start_time_utc"),
        "end_time_utc": metadata.get("end_time_utc"),
        "sensor_model": metadata.get("sensor_model"),
        "firmware_version": metadata.get("firmware_version"),
        "raw_sample_rate_hz": raw_sample_rate_hz,
        "feature_interval_s": _as_float(metadata.get("feature_interval_s")),
        "fft_window_size_samples": metadata.get("fft_window_size_samples"),
        "fft_window_type": metadata.get("fft_window_type"),
        "peak_picker_method": metadata.get("peak_picker_method"),
        "accel_scale_g_per_lsb": _as_float(metadata.get("accel_scale_g_per_lsb")),
        "incomplete_for_order_analysis": bool(metadata.get("incomplete_for_order_analysis")),
        "metadata": metadata,
        "warnings": [],
        "speed_breakdown": speed_breakdown,
        "phase_speed_breakdown": phase_speed_breakdown,
        "phase_segments": serialize_phase_segments(phase_segments),
        "run_noise_baseline_db": noise_baseline_db(run_noise_baseline_g),
        "speed_breakdown_skipped_reason": speed_breakdown_skipped_reason,
        "findings": findings,
        "top_causes": top_causes,
        "most_likely_origin": most_likely_origin,
        "test_plan": test_plan,
        "phase_timeline": phase_timeline,
        "speed_stats": speed_stats,
        "speed_stats_by_phase": speed_stats_by_phase,
        "phase_info": phase_info,
        "sensor_locations": sensor_locations,
        "sensor_locations_connected_throughout": sorted(connected_locations),
        "sensor_count_used": len(sensor_locations),
        "sensor_intensity_by_location": sensor_intensity_by_location,
        "run_suitability": run_suitability,
        "samples": samples,
        "data_quality": build_data_quality_dict(
            samples,
            speed_values,
            speed_stats,
            speed_non_null_pct,
            accel_stats,
            amp_metric_values,
        ),
    }
