"""Structured orchestration for building analysis summaries from run samples."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median as _median
from typing import cast

from vibesensor.domain import (
    ConfigurationSnapshot,
    DiagnosticCase,
    DrivingPhaseInterval,
    LocationIntensitySummary,
    RunCapture,
    RunSetup,
    RunSuitability,
    Sensor,
    SpeedProfile,
    SpeedSource,
    TestRun,
)
from vibesensor.domain import (
    DrivingSegment as DomainDrivingSegment,
)
from vibesensor.domain import (
    Finding as DomainFinding,
)
from vibesensor.domain.snapshots import DrivingPhaseSummary, SpeedProfileSummary
from vibesensor.domain.test_plan import plan_test_actions
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.report_i18n import normalize_lang
from vibesensor.shared.boundaries.analysis_payload import (
    AnalysisSummary,
    FindingPayload,
    PhaseSpeedBreakdownRow,
    SpeedBreakdownRow,
)
from vibesensor.shared.boundaries.diagnostic_case import (
    case_context_from_metadata,
    run_suitability_payload,
    speed_profile_from_stats,
)
from vibesensor.shared.boundaries.finding import step_payloads_from_plan
from vibesensor.shared.boundaries.vibration_origin import (
    SuspectedVibrationOrigin,
    build_origin_explanation,
)
from vibesensor.shared.constants import (
    MEMS_NOISE_FLOOR_G,
    SPEED_COVERAGE_MIN_PCT,
    SPEED_MIN_POINTS,
)
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.json_utils import i18n_ref
from vibesensor.shared.run_context import build_summary_warnings, order_reference_context_complete
from vibesensor.shared.time_utils import parse_iso8601, utc_now_iso
from vibesensor.shared.types.json_types import JsonObject, is_json_object
from vibesensor.strength_bands import bucket_for_strength
from vibesensor.use_cases.diagnostics._types import (
    AccelStatistics,
    Sample,
)
from vibesensor.use_cases.diagnostics.findings import (
    _build_findings,
    _phase_speed_breakdown,
    _sensor_intensity_by_location,
    _speed_breakdown,
)
from vibesensor.use_cases.diagnostics.helpers import (
    _format_duration,
    _load_run,
    _location_label,
    _locations_connected_throughout_run,
    _mean_variance,
    _outlier_summary,
    _percent_missing,
    _primary_vibration_strength_db,
    _run_noise_baseline_g,
    _sensor_limit_g,
    _speed_stats,
    _speed_stats_by_phase,
    _validate_required_strength_metrics,
    counter_delta,
)
from vibesensor.use_cases.diagnostics.phase_segmentation import (
    DrivingPhase,
    PhaseSegment,
    segment_run_phases,
)
from vibesensor.use_cases.diagnostics.plots import _plot_data
from vibesensor.use_cases.diagnostics.top_cause_selection import select_top_causes
from vibesensor.vibration_strength import compute_db

# ═══════════════════════════════════════════════════════════════════════════
# Suitability checks and data quality
# ═══════════════════════════════════════════════════════════════════════════


# Fraction of sensor ADC limit above which a sample is considered clipping.
# 2% headroom accounts for quantization effects near the ADC rail.
_SATURATION_FRACTION = 0.98

_STRENGTH_LABEL_KEY_BY_BUCKET: dict[str, str] = {
    "l0": "negligible",
    "l1": "light",
    "l2": "moderate",
    "l3": "strong",
    "l4": "very_strong",
    "l5": "very_strong",
}


def _strength_band_key(db_value: float | None) -> str | None:
    if db_value is None or not math.isfinite(db_value):
        return None
    return _STRENGTH_LABEL_KEY_BY_BUCKET.get(bucket_for_strength(db_value), "very_strong")


def _json_outlier_summary(values: list[float]) -> JsonObject:
    """Convert the local outlier summary helper output into the shared JSON shape."""
    summary = _outlier_summary(values)
    return {
        "count": summary["count"],
        "outlier_count": summary["outlier_count"],
        "outlier_pct": summary["outlier_pct"],
        "lower_bound": summary["lower_bound"],
        "upper_bound": summary["upper_bound"],
    }


def compute_accel_statistics(
    samples: list[Sample],
    sensor_model: object,
) -> AccelStatistics:
    """Compute per-axis values, aggregate amplitude metrics, and saturation counts."""
    sensor_limit = _sensor_limit_g(sensor_model)
    sat_threshold = sensor_limit * _SATURATION_FRACTION if sensor_limit is not None else None

    accel_x_vals: list[float] = []
    accel_y_vals: list[float] = []
    accel_z_vals: list[float] = []
    accel_mag_vals: list[float] = []
    amp_metric_values: list[float] = []
    sat_count = 0

    for sample in samples:
        x = _as_float(sample.get("accel_x_g"))
        y = _as_float(sample.get("accel_y_g"))
        z = _as_float(sample.get("accel_z_g"))
        if x is not None:
            accel_x_vals.append(x)
        if y is not None:
            accel_y_vals.append(y)
        if z is not None:
            accel_z_vals.append(z)
        if x is not None and y is not None and z is not None:
            accel_mag_vals.append(math.sqrt(x * x + y * y + z * z))
        if sat_threshold is not None and any(
            axis_val is not None and abs(axis_val) >= sat_threshold for axis_val in (x, y, z)
        ):
            sat_count += 1
        amp = _primary_vibration_strength_db(sample)
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


def compute_frame_integrity_counts(samples: list[Sample]) -> tuple[int, int]:
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


def compute_reference_completeness(metadata: JsonObject) -> bool:
    """Return True when enough reference metadata is present for order analysis."""
    return bool(order_reference_context_complete(metadata))


def build_data_quality_dict(
    samples: list[Sample],
    speed_values: list[float],
    speed_stats: SpeedProfileSummary,
    speed_non_null_pct: float,
    accel_stats: AccelStatistics,
    amp_metric_values: list[float],
) -> JsonObject:
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
            "mean_kmh": speed_stats.mean_kmh,
            "stddev_kmh": speed_stats.stddev_kmh,
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
            "accel_magnitude": _json_outlier_summary(accel_stats["accel_mag_vals"]),
            "amplitude_metric": _json_outlier_summary(amp_metric_values),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# Phase timeline and speed analysis
# ═══════════════════════════════════════════════════════════════════════════


def build_phase_timeline(
    phase_segments: list[PhaseSegment],
    findings: Sequence[DomainFinding],
    *,
    min_confidence: float,
) -> list[DrivingPhaseInterval]:
    """Build a simple phase timeline annotated with finding evidence."""
    if not phase_segments:
        return []

    # NOTE: has_fault_evidence is always False because phases_detected is not
    # preserved on the domain Finding (only cruise_fraction survives the
    # payload→domain decode).  Keeping the field for schema stability.
    return [
        DrivingPhaseInterval(
            phase=segment.phase,
            start_t_s=None if math.isnan(segment.start_t_s) else segment.start_t_s,
            end_t_s=None if math.isnan(segment.end_t_s) else segment.end_t_s,
            speed_min_kmh=segment.speed_min_kmh,
            speed_max_kmh=segment.speed_max_kmh,
            has_fault_evidence=False,
        )
        for segment in phase_segments
    ]


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


def build_domain_driving_segments(
    phase_segments: list[PhaseSegment],
) -> tuple[DomainDrivingSegment, ...]:
    return tuple(
        DomainDrivingSegment(
            phase=segment.phase,
            start_idx=segment.start_idx,
            end_idx=segment.end_idx,
            start_t_s=(
                None
                if isinstance(segment.start_t_s, float) and math.isnan(segment.start_t_s)
                else segment.start_t_s
            ),
            end_t_s=(
                None
                if isinstance(segment.end_t_s, float) and math.isnan(segment.end_t_s)
                else segment.end_t_s
            ),
            speed_min_kmh=segment.speed_min_kmh,
            speed_max_kmh=segment.speed_max_kmh,
            sample_count=segment.sample_count,
        )
        for segment in phase_segments
    )


def noise_baseline_db(run_noise_baseline_g: float | None) -> float | None:
    """Convert a run noise baseline amplitude in g to dB, or return None."""
    if run_noise_baseline_g is None:
        return None
    result: float = compute_db(
        max(MEMS_NOISE_FLOOR_G, run_noise_baseline_g),
        MEMS_NOISE_FLOOR_G,
    )
    return result


def prepare_speed_and_phases(
    samples: list[Sample],
) -> tuple[list[float], SpeedProfileSummary, float, bool, list[DrivingPhase], list[PhaseSegment]]:
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
    metadata: JsonObject,
    samples: list[Sample],
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


# ═══════════════════════════════════════════════════════════════════════════
# Summary payload assembly
# ═══════════════════════════════════════════════════════════════════════════


def build_sensor_analysis(
    *,
    samples: list[Sample],
    language: str,
    per_sample_phases: list[DrivingPhase],
) -> tuple[list[str], set[str], list[LocationIntensitySummary]]:
    """Build sensor location lists and intensity rows from analysed samples."""
    sensor_locations = sorted(
        {
            label
            for sample in samples
            if isinstance(sample, dict) and (label := _location_label(sample, lang=language))
        },
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
    findings: tuple[DomainFinding, ...],
) -> VibrationOrigin | None:
    """Return the most-likely origin as a domain value object."""
    return VibrationOrigin.from_ranked_findings(findings)


def _serialize_origin_summary(
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
        "most_likely_origin": _serialize_origin_summary(most_likely_origin),
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


# ═══════════════════════════════════════════════════════════════════════════
# Main orchestration
# ═══════════════════════════════════════════════════════════════════════════


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


@dataclass(frozen=True)
class PreparedRunData:
    """Input coordinator: shared timing, speed, and phase context for summary generation.

    Retained as the canonical input coordinator for the analysis pipeline.
    Computed once by :func:`prepare_run_data` and consumed by
    :func:`build_findings_bundle`, :func:`build_run_suitability_bundle`,
    and :class:`RunAnalysis`.
    """

    run_id: str
    start_ts: datetime | None
    end_ts: datetime | None
    duration_s: float
    raw_sample_rate_hz: float | None
    speed_values: list[float]
    speed_non_null_pct: float
    speed_sufficient: bool
    per_sample_phases: list[DrivingPhase]
    phase_segments: list[PhaseSegment]
    run_noise_baseline_g: float | None
    speed_profile: SpeedProfile
    speed_stats_by_phase: dict[str, SpeedProfileSummary]
    speed_breakdown: list[SpeedBreakdownRow]
    speed_breakdown_skipped_reason: JsonObject | None
    phase_speed_breakdown: list[PhaseSpeedBreakdownRow]

    # -- derived convenience ------------------------------------------------

    @property
    def is_steady_speed(self) -> bool:
        """Whether the run had steady speed (relevant to confidence scoring)."""
        steady: bool = self.speed_profile.steady_speed
        return steady

    @property
    def speed_stddev_kmh(self) -> float | None:
        return self.speed_profile.stddev_kmh if self.speed_values else None


def prepare_run_data(
    metadata: JsonObject,
    samples: list[Sample],
    *,
    file_name: str,
) -> PreparedRunData:
    """Prepare shared timing, speed, and phase context for summary generation."""
    run_id, start_ts, end_ts, duration_s = compute_run_timing(metadata, samples, file_name)
    (
        speed_values,
        speed_stats,
        speed_non_null_pct,
        speed_sufficient,
        per_sample_phases,
        phase_segments,
    ) = prepare_speed_and_phases(samples)
    run_noise_baseline_g = _run_noise_baseline_g(samples)
    speed_breakdown = _speed_breakdown(samples) if speed_sufficient else []
    speed_breakdown_skipped_reason: JsonObject | None = None
    if not speed_sufficient:
        speed_breakdown_skipped_reason = i18n_ref(
            "SPEED_DATA_MISSING_OR_INSUFFICIENT_SPEED_BINNED_AND",
        )
    phase_info = build_phase_summary(phase_segments)

    return PreparedRunData(
        run_id=run_id,
        start_ts=start_ts,
        end_ts=end_ts,
        duration_s=duration_s,
        raw_sample_rate_hz=_as_float(metadata.get("raw_sample_rate_hz")),
        speed_values=speed_values,
        speed_non_null_pct=speed_non_null_pct,
        speed_sufficient=speed_sufficient,
        per_sample_phases=per_sample_phases,
        phase_segments=phase_segments,
        run_noise_baseline_g=run_noise_baseline_g,
        speed_profile=speed_profile_from_stats(
            speed_stats,
            phase_info,
        ),
        speed_stats_by_phase=_speed_stats_by_phase(samples, per_sample_phases),
        speed_breakdown=speed_breakdown,
        speed_breakdown_skipped_reason=speed_breakdown_skipped_reason,
        phase_speed_breakdown=_phase_speed_breakdown(samples, per_sample_phases),
    )


def build_phase_summary(phase_segments: list[PhaseSegment]) -> DrivingPhaseSummary:
    """Small wrapper to keep summary-building imports localized."""
    from vibesensor.use_cases.diagnostics.phase_segmentation import phase_summary

    return phase_summary(phase_segments)


def build_findings_bundle(
    metadata: JsonObject,
    samples: list[Sample],
    *,
    language: str,
    prepared: PreparedRunData,
    overall_strength_band_key: str | None,
    has_reference_gaps: bool,
    sensor_count: int,
    findings_builder: Callable[..., tuple[DomainFinding, ...]] | None = None,
) -> tuple[
    VibrationOrigin | None,
    list[DrivingPhaseInterval],
    tuple[DomainFinding, ...],
    tuple[DomainFinding, ...],
]:
    """Build findings plus derived diagnosis narrative fields.

    Returns ``(origin, timeline, domain_findings, domain_top_causes)``.
    Findings are returned with :class:`ConfidenceAssessment` already
    attached via :meth:`Finding.with_confidence_assessment`.
    """
    builder = findings_builder or _build_findings
    domain_findings = builder(
        metadata=metadata,
        samples=samples,
        speed_sufficient=prepared.speed_sufficient,
        steady_speed=prepared.is_steady_speed,
        speed_stddev_kmh=prepared.speed_stddev_kmh,
        speed_non_null_pct=prepared.speed_non_null_pct,
        raw_sample_rate_hz=prepared.raw_sample_rate_hz,
        lang=language,
        per_sample_phases=prepared.per_sample_phases,
        run_noise_baseline_g=prepared.run_noise_baseline_g,
    )

    # Enrich findings with ConfidenceAssessment at construction time
    domain_findings = tuple(
        f
        if f.confidence_assessment is not None
        else f.with_confidence_assessment(
            strength_band_key=overall_strength_band_key or "",
            steady_speed=prepared.is_steady_speed,
            has_reference_gaps=has_reference_gaps,
            sensor_count=sensor_count,
        )
        for f in domain_findings
    )

    domain_diagnostic_findings = tuple(f for f in domain_findings if not f.is_reference)
    most_likely_origin = summarize_origin(
        domain_diagnostic_findings,
    )
    phase_timeline = build_phase_timeline(
        prepared.phase_segments,
        domain_findings,
        min_confidence=0.25,
    )
    domain_top_causes = select_top_causes(
        domain_findings,
    )
    return (
        most_likely_origin,
        phase_timeline,
        domain_findings,
        domain_top_causes,
    )


def build_sensor_bundle(
    samples: list[Sample],
    *,
    language: str,
    per_sample_phases: list[DrivingPhase],
) -> tuple[list[str], set[str], list[LocationIntensitySummary]]:
    """Build location-scoped sensor summaries used by analysis and reports."""
    return build_sensor_analysis(
        samples=samples,
        language=language,
        per_sample_phases=per_sample_phases,
    )


def build_run_suitability_bundle(
    metadata: JsonObject,
    samples: list[Sample],
    *,
    prepared: PreparedRunData,
    accel_stats: AccelStatistics,
) -> tuple[bool, RunSuitability | None, str | None]:
    """Build run-suitability checks and related confidence context."""
    reference_complete = compute_reference_completeness(metadata)
    sensor_ids = {
        str(cid)
        for sample in samples
        if isinstance(sample, dict) and (cid := sample.get("client_id"))
    }
    total_dropped, total_overflow = compute_frame_integrity_counts(samples)
    run_suitability = RunSuitability.evaluate(
        steady_speed=prepared.is_steady_speed,
        speed_sufficient=prepared.speed_sufficient,
        sensor_count=len(sensor_ids),
        reference_complete=reference_complete,
        sat_count=accel_stats["sat_count"],
        total_dropped=total_dropped,
        total_overflow=total_overflow,
    )
    amp_metric_values = accel_stats["amp_metric_values"]
    overall_strength_band_key = (
        _strength_band_key(_median(amp_metric_values)) if amp_metric_values else None
    )
    return reference_complete, run_suitability, overall_strength_band_key


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Output coordinator: carries domain aggregates alongside the boundary summary dict.

    Returned by :meth:`RunAnalysis.summarize`.  The ``summary`` dict is
    still needed for persistence (SQLite stores it as JSON) and many
    existing boundary consumers.  ``test_run`` and ``diagnostic_case``
    expose the fully-constructed domain aggregates so that callers no
    longer need to discard them.
    """

    test_run: TestRun
    diagnostic_case: DiagnosticCase
    summary: AnalysisSummary


class RunAnalysis:
    """Cohesive object around a single analyzed run.

    Owns run timing, speed/phase preparation, data quality, suitability,
    sensor bundle, findings bundle, and summary export.  Replaces the
    procedural orchestration in ``summarize_run_data`` with a richer
    object that keeps all derived state together.

    The public ``summarize_run_data()`` function delegates here.
    """

    __slots__ = (
        "_metadata",
        "_samples",
        "_file_name",
        "_language",
        "_include_samples",
        "_findings_builder",
        "_prepared",
        "_accel_stats",
        "_test_run",
    )

    def __init__(
        self,
        metadata: JsonObject,
        samples: list[Sample],
        *,
        file_name: str = "run",
        lang: str | None = None,
        include_samples: bool = True,
        findings_builder: Callable[..., tuple[DomainFinding, ...]] | None = None,
    ) -> None:
        self._metadata = metadata
        self._samples = samples
        self._file_name = file_name
        self._language = normalize_lang(lang)
        self._include_samples = include_samples
        self._findings_builder = findings_builder
        self._test_run: TestRun | None = None

        _validate_required_strength_metrics(samples)
        self._prepared = prepare_run_data(metadata, samples, file_name=file_name)
        self._accel_stats: AccelStatistics = compute_accel_statistics(
            samples, metadata.get("sensor_model")
        )

    # -- read-only access --------------------------------------------------

    @property
    def prepared(self) -> PreparedRunData:
        return self._prepared

    @property
    def accel_stats(self) -> AccelStatistics:
        return self._accel_stats

    @property
    def language(self) -> str:
        lang: str = self._language
        return lang

    @property
    def test_run(self) -> TestRun | None:
        return self._test_run

    # -- orchestration -----------------------------------------------------

    def summarize(self) -> AnalysisResult:
        """Run the full analysis pipeline and return the output coordinator.

        Returns an :class:`AnalysisResult` carrying the domain aggregates
        (``test_run``, ``diagnostic_case``) alongside the boundary
        ``summary`` dict.
        """
        reference_complete, run_suitability, overall_strength_band_key = (
            build_run_suitability_bundle(
                self._metadata,
                self._samples,
                prepared=self._prepared,
                accel_stats=self._accel_stats,
            )
        )
        sensor_locations, connected_locations, sensor_intensity_by_location = build_sensor_bundle(
            self._samples,
            language=self._language,
            per_sample_phases=self._prepared.per_sample_phases,
        )
        (
            most_likely_origin,
            phase_timeline,
            domain_findings,
            domain_top_causes,
        ) = build_findings_bundle(
            self._metadata,
            self._samples,
            language=self._language,
            prepared=self._prepared,
            overall_strength_band_key=overall_strength_band_key,
            has_reference_gaps=not reference_complete,
            sensor_count=len(sensor_locations),
            findings_builder=self._findings_builder,
        )

        # Build the domain aggregate with run-level value objects
        speed_profile = self._prepared.speed_profile if self._prepared.speed_values else None
        domain_suitability = run_suitability

        # Derive top_causes as a subset of the enriched findings,
        # preserving signatures collected by group_findings_by_source
        top_cause_ids = {f.finding_id for f in domain_top_causes if f.finding_id}
        top_cause_sigs = {f.finding_id: f.signatures for f in domain_top_causes if f.signatures}
        final_top_causes_list: list[DomainFinding] = []
        for f in domain_findings:
            if f.finding_id in top_cause_ids:
                sigs = top_cause_sigs.get(f.finding_id)
                final_top_causes_list.append(replace(f, signatures=sigs) if sigs else f)
        final_top_causes = tuple(final_top_causes_list)

        configuration_snapshot = ConfigurationSnapshot.from_metadata(self._metadata)
        driving_segments = build_domain_driving_segments(self._prepared.phase_segments)
        domain_test_plan = plan_test_actions(domain_findings)
        summary_test_plan: list[JsonObject] = cast(
            list[JsonObject], step_payloads_from_plan(domain_test_plan)
        )
        _raw_settings = self._metadata.get("analysis_settings")
        _scalar_settings: list[tuple[str, int | float | bool | str]] = []
        if isinstance(_raw_settings, dict):
            for _k, _v in sorted(_raw_settings.items()):
                if isinstance(_v, (int, float, bool, str)):
                    _scalar_settings.append((_k, _v))
        capture = RunCapture(
            run_id=self._prepared.run_id,
            setup=RunSetup(
                sensors=Sensor.from_location_codes(sensor_locations) if sensor_locations else (),
                speed_source=SpeedSource(),
                configuration_snapshot=configuration_snapshot,
            ),
            analysis_settings=tuple(_scalar_settings),
            sample_count=len(self._samples),
            duration_s=self._prepared.duration_s,
        )
        self._test_run = TestRun(
            capture=capture,
            driving_segments=driving_segments,
            findings=domain_findings,
            top_causes=final_top_causes,
            speed_profile=speed_profile,
            suitability=domain_suitability,
            test_plan=domain_test_plan,
        )
        domain_car, domain_symptoms = case_context_from_metadata(self._metadata)
        diagnostic_case = DiagnosticCase.start(
            car=domain_car,
            symptoms=domain_symptoms,
            test_plan=domain_test_plan,
        ).add_run(self._test_run)

        summary_speed_stats = _speed_stats(self._prepared.speed_values)
        summary_phase_info = build_phase_summary(self._prepared.phase_segments)

        # Serialize domain findings to payloads for the summary
        from vibesensor.shared.boundaries.finding import finding_payload_from_domain

        findings: list[FindingPayload] = [
            cast(FindingPayload, finding_payload_from_domain(f)) for f in domain_findings
        ]
        top_causes: list[FindingPayload] = [
            cast(FindingPayload, finding_payload_from_domain(f)) for f in final_top_causes
        ]

        summary = build_summary_payload(
            file_name=self._file_name,
            run_id=self._prepared.run_id,
            samples=self._samples,
            duration_s=self._prepared.duration_s,
            language=self._language,
            metadata=self._metadata,
            raw_sample_rate_hz=self._prepared.raw_sample_rate_hz,
            speed_breakdown=self._prepared.speed_breakdown,
            phase_speed_breakdown=self._prepared.phase_speed_breakdown,
            phase_segments=self._prepared.phase_segments,
            run_noise_baseline_g=self._prepared.run_noise_baseline_g,
            speed_breakdown_skipped_reason=self._prepared.speed_breakdown_skipped_reason,
            findings=findings,
            top_causes=top_causes,
            most_likely_origin=most_likely_origin,
            test_plan=summary_test_plan,
            phase_timeline=phase_timeline,
            speed_stats=summary_speed_stats,
            speed_stats_by_phase=self._prepared.speed_stats_by_phase,
            phase_info=summary_phase_info,
            sensor_locations=sensor_locations,
            connected_locations=connected_locations,
            sensor_intensity_by_location=sensor_intensity_by_location,
            run_suitability=domain_suitability,
            speed_values=self._prepared.speed_values,
            speed_non_null_pct=self._prepared.speed_non_null_pct,
            accel_stats=self._accel_stats,
            amp_metric_values=self._accel_stats["amp_metric_values"],
        )
        summary["warnings"] = build_summary_warnings(
            self._metadata,
            reference_complete=reference_complete,
        )
        summary["report_date"] = self._metadata.get("end_time_utc") or utc_now_iso()
        summary["plots"] = _plot_data(
            summary,
            run_noise_baseline_g=self._prepared.run_noise_baseline_g,
            per_sample_phases=self._prepared.per_sample_phases,
            phase_segments=self._prepared.phase_segments,
        )
        annotate_peaks_with_order_labels(summary)
        cast(dict[str, object], summary)["_summary_version"] = 2
        if not self._include_samples:
            summary.pop("samples", None)
        return AnalysisResult(
            test_run=self._test_run,
            diagnostic_case=diagnostic_case,
            summary=summary,
        )


def summarize_run_data(
    metadata: JsonObject,
    samples: list[Sample],
    lang: str | None = None,
    file_name: str = "run",
    include_samples: bool = True,
    findings_builder: Callable[..., tuple[DomainFinding, ...]] | None = None,
) -> AnalysisSummary:
    """Analyze pre-loaded run data and return the full summary dict.

    Delegates to :class:`RunAnalysis` which owns the full orchestration.
    """
    return (
        RunAnalysis(
            metadata,
            samples,
            file_name=file_name,
            lang=lang,
            include_samples=include_samples,
            findings_builder=findings_builder,
        )
        .summarize()
        .summary
    )


def build_findings_for_samples(
    *,
    metadata: JsonObject,
    samples: list[Sample],
    lang: str | None = None,
    findings_builder: Callable[..., tuple[DomainFinding, ...]] | None = None,
) -> tuple[DomainFinding, ...]:
    """Build the findings list from *samples* using the full analysis pipeline."""
    language = normalize_lang(lang)
    rows = list(samples)
    _validate_required_strength_metrics(rows)
    prepared = prepare_run_data(metadata, rows, file_name="run")
    builder = findings_builder or _build_findings
    return builder(
        metadata=dict(metadata),
        samples=rows,
        speed_sufficient=prepared.speed_sufficient,
        steady_speed=prepared.is_steady_speed,
        speed_stddev_kmh=prepared.speed_stddev_kmh,
        speed_non_null_pct=prepared.speed_non_null_pct,
        raw_sample_rate_hz=prepared.raw_sample_rate_hz,
        lang=language,
        per_sample_phases=prepared.per_sample_phases,
    )


def summarize_log(
    log_path: Path,
    lang: str | None = None,
    include_samples: bool = True,
    findings_builder: Callable[..., tuple[DomainFinding, ...]] | None = None,
) -> AnalysisSummary:
    """Read a JSONL run file and analyse it."""
    metadata, samples, _warnings = _load_run(log_path)
    return summarize_run_data(
        metadata,
        samples,
        lang=lang,
        file_name=log_path.name,
        include_samples=include_samples,
        findings_builder=findings_builder,
    )
