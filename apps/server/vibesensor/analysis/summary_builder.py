"""Structured orchestration for building analysis summaries from run samples."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median as _median

from vibesensor.analysis.analysis_window import AnalysisWindow
from vibesensor.vibration_strength import compute_db

from ..constants import MEMS_NOISE_FLOOR_G, SPEED_COVERAGE_MIN_PCT, SPEED_MIN_POINTS
from ..json_utils import as_float_or_none as _as_float
from ..report_i18n import normalize_lang
from ..run_context import build_summary_warnings, order_reference_context_complete
from ..runlog import parse_iso8601, utc_now_iso
from ._types import (
    AccelStatistics,
    AnalysisSummary,
    FindingPayload,
    I18nRef,
    IntensityRow,
    JsonObject,
    JsonValue,
    MetadataDict,
    PhaseSegmentSummary,
    PhaseSpeedBreakdownRow,
    PhaseSpeedStats,
    PhaseSummary,
    PhaseTimelineEntry,
    RunSuitabilityCheck,
    Sample,
    SpeedBreakdownRow,
    SpeedStats,
    SuspectedVibrationOrigin,
    TestStep,
    i18n_ref,
    is_json_object,
)
from .diagnosis_candidates import non_reference_findings
from .findings import (
    _build_findings,
    _phase_speed_breakdown,
    _sensor_intensity_by_location,
    _speed_breakdown,
)
from .helpers import (
    PHASE_I18N_KEYS,
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
    weak_spatial_dominance_threshold,
)
from .phase_segmentation import DrivingPhase, PhaseSegment, segment_run_phases
from .plots import _plot_data
from .strength_labels import strength_label as _strength_label
from .test_plan import _merge_test_plan
from .top_cause_selection import select_top_causes

# ═══════════════════════════════════════════════════════════════════════════
# Suitability checks and data quality
# ═══════════════════════════════════════════════════════════════════════════


# Fraction of sensor ADC limit above which a sample is considered clipping.
# 2% headroom accounts for quantization effects near the ADC rail.
_SATURATION_FRACTION = 0.98


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


def build_run_suitability_checks(
    *,
    steady_speed: bool,
    speed_sufficient: bool,
    sensor_ids: set[str],
    reference_complete: bool,
    sat_count: int,
    samples: list[Sample],
) -> list[RunSuitabilityCheck]:
    """Construct the language-neutral run-suitability checklist."""
    sensor_count_sufficient = len(sensor_ids) >= 3
    speed_variation_ok = speed_sufficient and not steady_speed
    run_suitability: list[RunSuitabilityCheck] = [
        {
            "check": "SUITABILITY_CHECK_SPEED_VARIATION",
            "check_key": "SUITABILITY_CHECK_SPEED_VARIATION",
            "state": "pass" if speed_variation_ok else "warn",
            "explanation": (
                i18n_ref("SUITABILITY_SPEED_VARIATION_PASS")
                if speed_variation_ok
                else i18n_ref("SUITABILITY_SPEED_VARIATION_WARN")
            ),
        },
        {
            "check": "SUITABILITY_CHECK_SENSOR_COVERAGE",
            "check_key": "SUITABILITY_CHECK_SENSOR_COVERAGE",
            "state": "pass" if sensor_count_sufficient else "warn",
            "explanation": (
                i18n_ref("SUITABILITY_SENSOR_COVERAGE_PASS")
                if sensor_count_sufficient
                else i18n_ref("SUITABILITY_SENSOR_COVERAGE_WARN")
            ),
        },
        {
            "check": "SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
            "check_key": "SUITABILITY_CHECK_REFERENCE_COMPLETENESS",
            "state": "pass" if reference_complete else "warn",
            "explanation": (
                i18n_ref("SUITABILITY_REFERENCE_COMPLETENESS_PASS")
                if reference_complete
                else i18n_ref("SUITABILITY_REFERENCE_COMPLETENESS_WARN")
            ),
        },
        {
            "check": "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
            "check_key": "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
            "state": "pass" if sat_count == 0 else "warn",
            "explanation": (
                i18n_ref("SUITABILITY_SATURATION_PASS")
                if sat_count == 0
                else i18n_ref("SUITABILITY_SATURATION_WARN", sat_count=sat_count)
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
                i18n_ref("SUITABILITY_FRAME_INTEGRITY_PASS")
                if frame_issues == 0
                else i18n_ref(
                    "SUITABILITY_FRAME_INTEGRITY_WARN",
                    total_dropped=total_dropped,
                    total_overflow=total_overflow,
                )
            ),
        },
    )
    return run_suitability


def compute_reference_completeness(metadata: MetadataDict) -> bool:
    """Return True when enough reference metadata is present for order analysis."""
    return bool(order_reference_context_complete(metadata))


def build_data_quality_dict(
    samples: list[Sample],
    speed_values: list[float],
    speed_stats: SpeedStats,
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
            "accel_magnitude": _json_outlier_summary(accel_stats["accel_mag_vals"]),
            "amplitude_metric": _json_outlier_summary(amp_metric_values),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# Phase timeline and speed analysis
# ═══════════════════════════════════════════════════════════════════════════


def build_phase_timeline(
    phase_segments: list[PhaseSegment],
    findings: list[FindingPayload],
    *,
    min_confidence: float,
) -> list[PhaseTimelineEntry]:
    """Build a simple phase timeline annotated with finding evidence."""
    if not phase_segments:
        return []

    finding_phases: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        if str(finding.get("finding_id", "")).startswith("REF_"):
            continue
        conf = _as_float(finding.get("confidence")) or 0.0
        if conf < min_confidence:
            continue
        phase_ev = finding.get("phase_evidence")
        if isinstance(phase_ev, dict):
            detected_phases = phase_ev.get("phases_detected", [])
            if not isinstance(detected_phases, list):
                continue
            for phase in detected_phases:
                finding_phases.add(str(phase))

    return [
        {
            "phase": segment.phase.value,
            "start_t_s": None if math.isnan(segment.start_t_s) else segment.start_t_s,
            "end_t_s": None if math.isnan(segment.end_t_s) else segment.end_t_s,
            "speed_min_kmh": segment.speed_min_kmh,
            "speed_max_kmh": segment.speed_max_kmh,
            "has_fault_evidence": segment.phase.value in finding_phases,
        }
        for segment in phase_segments
    ]


def serialize_phase_segments(phase_segments: list[PhaseSegment]) -> list[PhaseSegmentSummary]:
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
    return compute_db(
        max(MEMS_NOISE_FLOOR_G, run_noise_baseline_g),
        MEMS_NOISE_FLOOR_G,
    )


def prepare_speed_and_phases(
    samples: list[Sample],
) -> tuple[list[float], SpeedStats, float, bool, list[DrivingPhase], list[PhaseSegment]]:
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
    metadata: MetadataDict,
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
) -> tuple[list[str], set[str], list[IntensityRow]]:
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


@dataclass
class LocalizationAssessment:
    """Interpreted assessment of spatial/localization meaning for a finding.

    Owns localized-vs-diffuse classification, separation quality,
    primary/supporting location access, and confidence interpretation
    so that callers no longer scatter localization reasoning across
    procedural code.
    """

    _primary_location: str
    _alternative_locations: list[str]
    dominance_ratio: float | None
    _weak_spatial: bool
    _diffuse_excitation: bool
    _localization_confidence: float
    _adaptive_threshold: float

    # -- construction -------------------------------------------------------

    @staticmethod
    def from_finding(finding: FindingPayload) -> LocalizationAssessment:
        """Build from a single FindingPayload, extracting localization fields."""
        hotspot = finding.get("location_hotspot")
        primary = str(finding.get("strongest_location") or "").strip() or "unknown"
        alternatives = _collect_alternative_locations(hotspot, primary_location=primary)
        dominance = _as_float(finding.get("dominance_ratio"))
        threshold = _resolve_weak_spatial_threshold(finding, hotspot=hotspot)
        weak = bool(finding.get("weak_spatial_separation")) or (
            dominance is not None and dominance < threshold
        )
        loc_conf = 0.0
        if isinstance(hotspot, dict):
            loc_conf = float(_as_float(hotspot.get("localization_confidence")) or 0.0)
        return LocalizationAssessment(
            _primary_location=primary,
            _alternative_locations=alternatives,
            dominance_ratio=dominance,
            _weak_spatial=weak,
            _diffuse_excitation=finding.get("diffuse_excitation", False),
            _localization_confidence=loc_conf,
            _adaptive_threshold=threshold,
        )

    # -- classification -----------------------------------------------------

    @property
    def is_localized(self) -> bool:
        """Whether the primary location is known and actionable."""
        return self._primary_location.lower() not in {"", "unknown"}

    @property
    def is_diffuse(self) -> bool:
        """Whether the excitation is diffuse across locations."""
        return self._diffuse_excitation

    @property
    def has_clear_separation(self) -> bool:
        """Whether spatial separation between sensor locations is clear."""
        return not self._weak_spatial

    # -- location access ----------------------------------------------------

    @property
    def primary_location(self) -> str:
        """The strongest sensor location (or ``'unknown'``)."""
        return self._primary_location

    def supporting_locations(self) -> list[str]:
        """Alternative/corroborating locations beyond the primary."""
        return list(self._alternative_locations)

    # -- confidence interpretation ------------------------------------------

    def confidence_band(self) -> str:
        """Return ``'high'``, ``'medium'``, or ``'low'`` for localization confidence."""
        if self._localization_confidence >= 0.7:
            return "high"
        if self._localization_confidence >= 0.4:
            return "medium"
        return "low"

    # -- display helpers ----------------------------------------------------

    def display_location(self) -> str:
        """Build the display-ready location summary string."""
        if not (
            self._weak_spatial
            and self.dominance_ratio is not None
            and self.dominance_ratio < self._adaptive_threshold
        ):
            return self._primary_location
        display_locations = [self._primary_location, *self._alternative_locations]
        return " / ".join(
            candidate
            for idx, candidate in enumerate(display_locations)
            if candidate and candidate not in display_locations[:idx]
        )

    # -- mutation (multi-finding enrichment) --------------------------------

    def enrich_from_second_finding(
        self,
        second_finding: FindingPayload,
        *,
        top_confidence: float,
    ) -> None:
        """Promote ambiguity when the second finding is close in confidence."""
        second_loc = str(second_finding.get("strongest_location") or "").strip()
        second_conf = _as_float(second_finding.get("confidence")) or 0.0
        if (
            second_loc
            and self._primary_location
            and second_loc != self._primary_location
            and top_confidence > 0
            and second_conf / top_confidence >= 0.7
        ):
            self._weak_spatial = True
            if second_loc not in self._alternative_locations:
                self._alternative_locations.append(second_loc)


# ---------------------------------------------------------------------------
# LocalizationAssessment support helpers
# ---------------------------------------------------------------------------


def _collect_alternative_locations(
    hotspot: object,
    *,
    primary_location: str,
) -> list[str]:
    """Collect alternative hotspot locations from the location hotspot dict."""
    alternative_locations: list[str] = []
    if not isinstance(hotspot, dict):
        return alternative_locations
    ambiguous_locations = hotspot.get("ambiguous_locations", [])
    if not isinstance(ambiguous_locations, list):
        ambiguous_locations = []
    for candidate in ambiguous_locations:
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


def _resolve_weak_spatial_threshold(top_finding: FindingPayload, *, hotspot: object) -> float:
    """Resolve the adaptive weak-spatial threshold for the strongest finding."""
    location_count = _as_float(top_finding.get("location_count"))
    if location_count is None and isinstance(hotspot, dict):
        location_count = _as_float(hotspot.get("location_count"))
    return weak_spatial_dominance_threshold(int(location_count) if location_count else None)


def summarize_origin(findings: list[FindingPayload]) -> SuspectedVibrationOrigin:
    """Build the most-likely-origin summary from ranked diagnostic findings."""
    if not findings:
        return {
            "location": "unknown",
            "alternative_locations": [],
            "suspected_source": "unknown",
            "dominance_ratio": None,
            "weak_spatial_separation": True,
            "explanation": i18n_ref("ORIGIN_NO_RANKED_FINDING_AVAILABLE"),
        }

    top = findings[0]
    loc = LocalizationAssessment.from_finding(top)
    source = str(top.get("suspected_source") or "unknown")

    if len(findings) >= 2:
        loc.enrich_from_second_finding(
            findings[1],
            top_confidence=_as_float(top.get("confidence")) or 0.0,
        )

    location = loc.display_location()
    speed_band = str(top.get("strongest_speed_band") or "")
    dominant_phase = str(top.get("dominant_phase") or "").strip()
    explanation = build_origin_explanation(
        source=source,
        speed_band=speed_band,
        location=location,
        dominance=loc.dominance_ratio,
        weak=not loc.has_clear_separation,
        dominant_phase=dominant_phase,
    )
    return {
        "location": location,
        "alternative_locations": loc.supporting_locations(),
        "suspected_source": source,
        "dominance_ratio": loc.dominance_ratio,
        "weak_spatial_separation": not loc.has_clear_separation,
        "speed_band": speed_band or None,
        "dominant_phase": dominant_phase or None,
        "explanation": explanation,
    }


def build_origin_explanation(
    *,
    source: str,
    speed_band: str,
    location: str,
    dominance: float | None,
    weak: bool,
    dominant_phase: str,
) -> JsonValue:
    """Build the language-neutral origin explanation block."""
    explanation_parts: list[JsonValue] = [
        i18n_ref(
            "ORIGIN_EXPLANATION_FINDING_1",
            source=source,
            speed_band=speed_band or "unknown",
            location=location,
            dominance=f"{dominance:.2f}x" if dominance is not None else "n/a",
        ),
    ]
    if weak:
        explanation_parts.append(i18n_ref("WEAK_SPATIAL_SEPARATION_INSPECT_NEARBY"))
    if dominant_phase and dominant_phase in PHASE_I18N_KEYS:
        explanation_parts.append(i18n_ref("ORIGIN_PHASE_ONSET_NOTE", phase=dominant_phase))
    return explanation_parts[0] if len(explanation_parts) == 1 else explanation_parts


def build_summary_payload(
    *,
    file_name: str,
    run_id: str,
    samples: list[Sample],
    duration_s: float,
    language: str,
    metadata: MetadataDict,
    raw_sample_rate_hz: float | None,
    speed_breakdown: list[SpeedBreakdownRow],
    phase_speed_breakdown: list[PhaseSpeedBreakdownRow],
    phase_segments: list[PhaseSegment],
    run_noise_baseline_g: float | None,
    speed_breakdown_skipped_reason: I18nRef | None,
    findings: list[FindingPayload],
    top_causes: list[FindingPayload],
    most_likely_origin: SuspectedVibrationOrigin,
    test_plan: list[TestStep],
    phase_timeline: list[PhaseTimelineEntry],
    speed_stats: SpeedStats,
    speed_stats_by_phase: dict[str, PhaseSpeedStats],
    phase_info: PhaseSummary,
    sensor_locations: list[str],
    connected_locations: set[str],
    sensor_intensity_by_location: list[IntensityRow],
    run_suitability: list[RunSuitabilityCheck],
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

    order_annotations: list[tuple[float, str]] = []
    for finding in findings:
        if finding.get("finding_id") != "F_ORDER":
            continue
        label = str(finding.get("frequency_hz_or_order") or "").strip()
        matched_points = finding.get("matched_points")
        if not label or not isinstance(matched_points, list) or not matched_points:
            continue
        matched_freqs = [
            value
            for point in matched_points
            if isinstance(point, dict) and (value := _as_float(point.get("matched_hz"))) is not None
        ]
        if matched_freqs:
            order_annotations.append((_median(matched_freqs), label))

    if not order_annotations:
        return

    tolerance_hz = 2.0
    used_rows: set[int] = set()
    for median_hz, label in order_annotations:
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
            used_rows.add(best_idx)


@dataclass(frozen=True)
class PreparedRunData:
    """Shared timing, speed, and phase context for summary generation."""

    run_id: str
    start_ts: datetime | None
    end_ts: datetime | None
    duration_s: float
    raw_sample_rate_hz: float | None
    speed_values: list[float]
    speed_stats: SpeedStats
    speed_non_null_pct: float
    speed_sufficient: bool
    per_sample_phases: list[DrivingPhase]
    phase_segments: list[PhaseSegment]
    run_noise_baseline_g: float | None
    phase_info: PhaseSummary
    speed_stats_by_phase: dict[str, PhaseSpeedStats]
    speed_breakdown: list[SpeedBreakdownRow]
    speed_breakdown_skipped_reason: I18nRef | None
    phase_speed_breakdown: list[PhaseSpeedBreakdownRow]

    # -- derived convenience ------------------------------------------------

    @property
    def is_steady_speed(self) -> bool:
        """Whether the run had steady speed (relevant to confidence scoring)."""
        return bool(self.speed_stats.get("steady_speed"))

    @property
    def speed_stddev_kmh(self) -> float | None:
        return _as_float(self.speed_stats.get("stddev_kmh"))

    @property
    def analysis_windows(self) -> list[AnalysisWindow]:
        """Domain-level view of phase segments as :class:`AnalysisWindow` objects."""
        return [seg.to_analysis_window() for seg in self.phase_segments]


def prepare_run_data(
    metadata: MetadataDict,
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
    speed_breakdown_skipped_reason: I18nRef | None = None
    if not speed_sufficient:
        speed_breakdown_skipped_reason = i18n_ref(
            "SPEED_DATA_MISSING_OR_INSUFFICIENT_SPEED_BINNED_AND",
        )

    return PreparedRunData(
        run_id=run_id,
        start_ts=start_ts,
        end_ts=end_ts,
        duration_s=duration_s,
        raw_sample_rate_hz=_as_float(metadata.get("raw_sample_rate_hz")),
        speed_values=speed_values,
        speed_stats=speed_stats,
        speed_non_null_pct=speed_non_null_pct,
        speed_sufficient=speed_sufficient,
        per_sample_phases=per_sample_phases,
        phase_segments=phase_segments,
        run_noise_baseline_g=run_noise_baseline_g,
        phase_info=build_phase_summary(phase_segments),
        speed_stats_by_phase=_speed_stats_by_phase(samples, per_sample_phases),
        speed_breakdown=speed_breakdown,
        speed_breakdown_skipped_reason=speed_breakdown_skipped_reason,
        phase_speed_breakdown=_phase_speed_breakdown(samples, per_sample_phases),
    )


def build_phase_summary(phase_segments: list[PhaseSegment]) -> PhaseSummary:
    """Small wrapper to keep summary-building imports localized."""
    from .phase_segmentation import phase_summary

    return phase_summary(phase_segments)


def build_findings_bundle(
    metadata: MetadataDict,
    samples: list[Sample],
    *,
    language: str,
    prepared: PreparedRunData,
    overall_strength_band_key: str | None,
    findings_builder: Callable[..., list[FindingPayload]] | None = None,
) -> tuple[
    list[FindingPayload],
    SuspectedVibrationOrigin,
    list[TestStep],
    list[PhaseTimelineEntry],
    list[FindingPayload],
]:
    """Build findings plus derived diagnosis narrative fields."""
    builder = findings_builder or _build_findings
    findings = builder(
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
    diagnostic_findings = non_reference_findings(findings)
    most_likely_origin = summarize_origin(diagnostic_findings)
    test_plan = _merge_test_plan(findings, language)
    phase_timeline = build_phase_timeline(
        prepared.phase_segments,
        findings,
        min_confidence=0.25,
    )
    top_causes = select_top_causes(findings, strength_band_key=overall_strength_band_key)
    return findings, most_likely_origin, test_plan, phase_timeline, top_causes


def build_sensor_bundle(
    samples: list[Sample],
    *,
    language: str,
    per_sample_phases: list[DrivingPhase],
) -> tuple[list[str], set[str], list[IntensityRow]]:
    """Build location-scoped sensor summaries used by analysis and reports."""
    return build_sensor_analysis(
        samples=samples,
        language=language,
        per_sample_phases=per_sample_phases,
    )


def build_run_suitability_bundle(
    metadata: MetadataDict,
    samples: list[Sample],
    *,
    prepared: PreparedRunData,
    accel_stats: AccelStatistics,
) -> tuple[bool, list[RunSuitabilityCheck], str | None]:
    """Build run-suitability checks and related confidence context."""
    reference_complete = compute_reference_completeness(metadata)
    sensor_ids = {
        str(cid)
        for sample in samples
        if isinstance(sample, dict) and (cid := sample.get("client_id"))
    }
    run_suitability = build_run_suitability_checks(
        steady_speed=prepared.is_steady_speed,
        speed_sufficient=prepared.speed_sufficient,
        sensor_ids=sensor_ids,
        reference_complete=reference_complete,
        sat_count=accel_stats["sat_count"],
        samples=samples,
    )
    amp_metric_values = accel_stats["amp_metric_values"]
    overall_strength_band_key = (
        _strength_label(_median(amp_metric_values))[0] if amp_metric_values else None
    )
    return reference_complete, run_suitability, overall_strength_band_key


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
    )

    def __init__(
        self,
        metadata: MetadataDict,
        samples: list[Sample],
        *,
        file_name: str = "run",
        lang: str | None = None,
        include_samples: bool = True,
        findings_builder: Callable[..., list[FindingPayload]] | None = None,
    ) -> None:
        self._metadata = metadata
        self._samples = samples
        self._file_name = file_name
        self._language = normalize_lang(lang)
        self._include_samples = include_samples
        self._findings_builder = findings_builder

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
        return self._language

    # -- orchestration -----------------------------------------------------

    def summarize(self) -> AnalysisSummary:
        """Run the full analysis pipeline and return the summary dict."""
        reference_complete, run_suitability, overall_strength_band_key = (
            build_run_suitability_bundle(
                self._metadata,
                self._samples,
                prepared=self._prepared,
                accel_stats=self._accel_stats,
            )
        )
        findings, most_likely_origin, test_plan, phase_timeline, top_causes = build_findings_bundle(
            self._metadata,
            self._samples,
            language=self._language,
            prepared=self._prepared,
            overall_strength_band_key=overall_strength_band_key,
            findings_builder=self._findings_builder,
        )
        sensor_locations, connected_locations, sensor_intensity_by_location = build_sensor_bundle(
            self._samples,
            language=self._language,
            per_sample_phases=self._prepared.per_sample_phases,
        )

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
            test_plan=test_plan,
            phase_timeline=phase_timeline,
            speed_stats=self._prepared.speed_stats,
            speed_stats_by_phase=self._prepared.speed_stats_by_phase,
            phase_info=self._prepared.phase_info,
            sensor_locations=sensor_locations,
            connected_locations=connected_locations,
            sensor_intensity_by_location=sensor_intensity_by_location,
            run_suitability=run_suitability,
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
        if not self._include_samples:
            summary.pop("samples", None)
        return summary


def summarize_run_data(
    metadata: MetadataDict,
    samples: list[Sample],
    lang: str | None = None,
    file_name: str = "run",
    include_samples: bool = True,
    findings_builder: Callable[..., list[FindingPayload]] | None = None,
) -> AnalysisSummary:
    """Analyze pre-loaded run data and return the full summary dict.

    Delegates to :class:`RunAnalysis` which owns the full orchestration.
    """
    return RunAnalysis(
        metadata,
        samples,
        file_name=file_name,
        lang=lang,
        include_samples=include_samples,
        findings_builder=findings_builder,
    ).summarize()


def build_findings_for_samples(
    *,
    metadata: MetadataDict,
    samples: list[Sample],
    lang: str | None = None,
    findings_builder: Callable[..., list[FindingPayload]] | None = None,
) -> list[FindingPayload]:
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
    findings_builder: Callable[..., list[FindingPayload]] | None = None,
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
