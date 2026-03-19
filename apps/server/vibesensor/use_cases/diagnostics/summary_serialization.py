"""Summary payload serialization extracted from summary_builder.

Functions here transform already-computed domain artifacts into the
JSON-serialisable ``AnalysisSummary`` dict used for persistence and
boundary consumers.
"""

from __future__ import annotations

import math
from dataclasses import asdict
from statistics import median as _median
from typing import cast

from vibesensor.domain import (
    DrivingPhaseInterval,
    LocationIntensitySummary,
    RunSuitability,
)
from vibesensor.domain.snapshots import DrivingPhaseSummary, SpeedProfileSummary
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.boundaries.analysis_payload import (
    AnalysisSummary,
    FindingPayload,
    PhaseSpeedBreakdownRow,
    SpeedBreakdownRow,
)
from vibesensor.shared.boundaries.diagnostic_case import run_suitability_payload
from vibesensor.shared.boundaries.vibration_origin import (
    SuspectedVibrationOrigin,
    build_origin_explanation,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.json_utils import i18n_ref
from vibesensor.shared.types.json_types import JsonObject, is_json_object
from vibesensor.use_cases.diagnostics._types import AccelStatistics, Sample
from vibesensor.use_cases.diagnostics.helpers import _format_duration
from vibesensor.use_cases.diagnostics.phase_segmentation import PhaseSegment
from vibesensor.use_cases.diagnostics.statistics import (
    build_data_quality_dict,
    noise_baseline_db,
)

# ── Phase segment serialization ──────────────────────────────────────────


def serialize_phase_segments(phase_segments: list[PhaseSegment]) -> list[JsonObject]:
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


# ── Origin serialization ─────────────────────────────────────────────────


def serialize_origin_summary(
    origin: VibrationOrigin | None,
) -> SuspectedVibrationOrigin:
    """Project a domain origin into the persisted summary payload shape."""
    if origin is None:
        return {
            "location": "unknown",
            "alternative_locations": [],
            "suspected_source": "unknown",
            "dominance_ratio": None,
            "weak_spatial_separation": True,
            "explanation": i18n_ref("ORIGIN_NO_RANKED_FINDING_AVAILABLE"),
        }

    location = origin.summary_location
    source = str(origin.suspected_source)
    speed_band = origin.speed_band or ""
    dominant_phase = origin.dominant_phase or ""
    dominance = origin.hotspot.dominance_ratio if origin.hotspot else origin.dominance_ratio
    weak = origin.weak_spatial_separation

    return {
        "location": location,
        "alternative_locations": list(origin.alternative_locations),
        "suspected_source": source,
        "dominance_ratio": dominance,
        "weak_spatial_separation": weak,
        "speed_band": speed_band or None,
        "dominant_phase": dominant_phase or None,
        "explanation": build_origin_explanation(
            source=source,
            speed_band=speed_band,
            location=location,
            dominance=dominance,
            weak=weak,
            dominant_phase=dominant_phase,
        ),
    }


# ── Summary payload assembly ─────────────────────────────────────────────


def build_summary_payload(
    *,
    file_name: str,
    run_id: str,
    samples: list[Sample],
    duration_s: float,
    language: str,
    metadata: JsonObject,
    raw_sample_rate_hz: float | None,
    speed_breakdown: list[SpeedBreakdownRow],
    phase_speed_breakdown: list[PhaseSpeedBreakdownRow],
    phase_segments: list[PhaseSegment],
    run_noise_baseline_g: float | None,
    speed_breakdown_skipped_reason: JsonObject | None,
    findings: list[FindingPayload],
    top_causes: list[FindingPayload],
    most_likely_origin: VibrationOrigin | None,
    test_plan: list[JsonObject],
    phase_timeline: list[DrivingPhaseInterval],
    speed_stats: SpeedProfileSummary,
    speed_stats_by_phase: dict[str, SpeedProfileSummary],
    phase_info: DrivingPhaseSummary,
    sensor_locations: list[str],
    connected_locations: set[str],
    sensor_intensity_by_location: list[LocationIntensitySummary],
    run_suitability: RunSuitability | None,
    speed_values: list[float],
    speed_non_null_pct: float,
    accel_stats: AccelStatistics,
    amp_metric_values: list[float],
) -> AnalysisSummary:
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
        "most_likely_origin": serialize_origin_summary(most_likely_origin),
        "test_plan": test_plan,
        "phase_timeline": [
            {
                "phase": entry.phase.value,
                "start_t_s": entry.start_t_s,
                "end_t_s": entry.end_t_s,
                "speed_min_kmh": entry.speed_min_kmh,
                "speed_max_kmh": entry.speed_max_kmh,
                "has_fault_evidence": entry.has_fault_evidence,
            }
            for entry in phase_timeline
        ],
        "speed_stats": cast(JsonObject, speed_stats.to_dict()),
        "speed_stats_by_phase": {
            k: cast(JsonObject, v.to_dict()) for k, v in speed_stats_by_phase.items()
        },
        "phase_info": cast(JsonObject, phase_info.to_dict()),
        "sensor_locations": sensor_locations,
        "sensor_locations_connected_throughout": sorted(connected_locations),
        "sensor_count_used": len(sensor_locations),
        "sensor_intensity_by_location": [asdict(row) for row in sensor_intensity_by_location],
        "run_suitability": run_suitability_payload(run_suitability),
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


# ── Post-assembly annotation ─────────────────────────────────────────────


def annotate_peaks_with_order_labels(summary: AnalysisSummary) -> None:
    """Back-fill peak-table order labels by matching order findings to peak rows."""
    plots = summary.get("plots")
    if not is_json_object(plots):
        return
    raw_peaks_table = plots.get("peaks_table", [])
    peaks_table = (
        [row for row in raw_peaks_table if is_json_object(row)]
        if isinstance(raw_peaks_table, list)
        else []
    )
    raw_findings = summary.get("findings", [])
    findings = (
        [finding for finding in raw_findings if is_json_object(finding)]
        if isinstance(raw_findings, list)
        else []
    )
    if not peaks_table or not findings:
        return

    order_annotations: list[tuple[float, str, str]] = []
    for finding in findings:
        if finding.get("finding_id") != "F_ORDER":
            continue
        label = str(finding.get("frequency_hz_or_order") or "").strip()
        suspected_source = str(finding.get("suspected_source") or "").strip()
        matched_points = finding.get("matched_points")
        if not label or not isinstance(matched_points, list) or not matched_points:
            continue
        matched_freqs = [
            value
            for point in matched_points
            if isinstance(point, dict) and (value := _as_float(point.get("matched_hz"))) is not None
        ]
        if matched_freqs:
            order_annotations.append((_median(matched_freqs), label, suspected_source))

    if not order_annotations:
        return

    tolerance_hz = 2.0
    used_rows: set[int] = set()
    for median_hz, label, suspected_source in order_annotations:
        best_idx: int | None = None
        best_dist = tolerance_hz + 1.0
        for idx, row in enumerate(peaks_table):
            if idx in used_rows:
                continue
            freq = _as_float(row.get("frequency_hz"))
            if freq is None:
                continue
            dist = abs(freq - median_hz)
            if dist < best_dist:
                best_idx = idx
                best_dist = dist
        if best_idx is not None and best_dist <= tolerance_hz:
            peaks_table[best_idx]["order_label"] = label
            peaks_table[best_idx]["suspected_source"] = suspected_source
            used_rows.add(best_idx)
