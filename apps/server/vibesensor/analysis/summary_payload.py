"""Origin, sensor-analysis, and payload-assembly helpers for run summaries."""

from __future__ import annotations

from typing import Any

from ..runlog import as_float_or_none as _as_float
from .findings.intensity import _sensor_intensity_by_location
from .helpers import (
    PHASE_I18N_KEYS,
    _format_duration,
    _location_label,
    _locations_connected_throughout_run,
    weak_spatial_dominance_threshold,
)
from .order_analysis import _i18n_ref
from .phase_segmentation import DrivingPhase, PhaseSegment
from .summary_phases import noise_baseline_db, serialize_phase_segments
from .summary_suitability import build_data_quality_dict


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


def summarize_origin(findings: list[dict[str, Any]]) -> dict[str, Any]:
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
    alternative_locations = collect_alternative_locations(top, primary_location=primary_location)
    source = str(top.get("suspected_source") or "unknown")
    hotspot = top.get("location_hotspot")
    dominance = _as_float(top.get("dominance_ratio"))
    adaptive_threshold = weak_spatial_threshold(top, hotspot=hotspot)
    weak = bool(top.get("weak_spatial_separation")) or (
        dominance is not None and dominance < adaptive_threshold
    )
    weak, alternative_locations = enrich_with_second_finding(
        findings,
        weak=weak,
        primary_location=primary_location,
        alternative_locations=alternative_locations,
    )
    location = summarize_display_location(
        primary_location=primary_location,
        alternative_locations=alternative_locations,
        weak=weak,
        dominance=dominance,
        adaptive_threshold=adaptive_threshold,
    )
    speed_band = str(top.get("strongest_speed_band") or "")
    dominant_phase = str(top.get("dominant_phase") or "").strip()
    explanation = build_origin_explanation(
        source=source,
        speed_band=speed_band,
        location=location,
        dominance=dominance,
        weak=weak,
        dominant_phase=dominant_phase,
    )
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


def collect_alternative_locations(
    top_finding: dict[str, Any],
    *,
    primary_location: str,
) -> list[str]:
    """Collect alternative hotspot locations from the strongest finding."""
    alternative_locations: list[str] = []
    hotspot = top_finding.get("location_hotspot")
    if not isinstance(hotspot, dict):
        return alternative_locations
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
    return alternative_locations


def weak_spatial_threshold(top_finding: dict[str, Any], *, hotspot: object) -> float:
    """Resolve the adaptive weak-spatial threshold for the strongest finding."""
    location_count = _as_float(top_finding.get("location_count"))
    if location_count is None and isinstance(hotspot, dict):
        location_count = _as_float(hotspot.get("location_count"))
    return weak_spatial_dominance_threshold(int(location_count) if location_count else None)


def enrich_with_second_finding(
    findings: list[dict[str, Any]],
    *,
    weak: bool,
    primary_location: str,
    alternative_locations: list[str],
) -> tuple[bool, list[str]]:
    """Promote ambiguity when the second finding is close in confidence."""
    if len(findings) < 2:
        return weak, alternative_locations
    second = findings[1]
    second_loc = str(second.get("strongest_location") or "").strip()
    second_conf = _as_float(second.get("confidence_0_to_1")) or 0.0
    top_conf = _as_float(findings[0].get("confidence_0_to_1")) or 0.0
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
    return weak, alternative_locations


def summarize_display_location(
    *,
    primary_location: str,
    alternative_locations: list[str],
    weak: bool,
    dominance: float | None,
    adaptive_threshold: float,
) -> str:
    """Build the display-ready location summary string."""
    if not (weak and dominance is not None and dominance < adaptive_threshold):
        return primary_location
    display_locations = [primary_location, *alternative_locations]
    return " / ".join(
        [
            candidate
            for idx, candidate in enumerate(display_locations)
            if candidate and candidate not in display_locations[:idx]
        ]
    )


def build_origin_explanation(
    *,
    source: str,
    speed_band: str,
    location: str,
    dominance: float | None,
    weak: bool,
    dominant_phase: str,
) -> object:
    """Build the language-neutral origin explanation block."""
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
    if dominant_phase and dominant_phase in PHASE_I18N_KEYS:
        explanation_parts.append(_i18n_ref("ORIGIN_PHASE_ONSET_NOTE", phase=dominant_phase))
    return explanation_parts[0] if len(explanation_parts) == 1 else explanation_parts


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
