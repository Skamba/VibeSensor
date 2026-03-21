"""Top-level summary assembly helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from typing import cast

from vibesensor.domain import DrivingPhaseInterval, LocationIntensitySummary, RunSuitability
from vibesensor.domain import (
    Finding as DomainFinding,
)
from vibesensor.domain.driving_phase_summary import DrivingPhaseSummary
from vibesensor.domain.speed_profile_summary import SpeedProfileSummary
from vibesensor.domain.vibration_origin import VibrationOrigin
from vibesensor.shared.boundaries.analysis_payload import (
    AnalysisSummary,
    DataQualityPayload,
    LocationIntensitySummaryPayload,
    OutlierSummaryPayload,
    PhaseInfoPayload,
    PhaseTimelineEntryPayload,
    SpeedStatsPayload,
    TestPlanStepPayload,
)
from vibesensor.shared.boundaries.diagnostic_case import run_suitability_payload
from vibesensor.shared.boundaries.vibration_origin import (
    SuspectedVibrationOrigin,
    build_origin_explanation,
)
from vibesensor.shared.constants import MEMS_NOISE_FLOOR_G
from vibesensor.shared.json_utils import as_float_or_none as _as_float
from vibesensor.shared.json_utils import i18n_ref
from vibesensor.shared.statistics_utils import _json_outlier_summary, _percent_missing
from vibesensor.shared.time_utils import format_duration_mm_ss
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.vibration_strength import compute_db

from ._contracts import (
    AccelStatisticsLike,
    PhaseSegmentLike,
    PhaseSpeedBreakdownRowLike,
    SpeedBreakdownRowLike,
)
from ._findings import serialize_findings
from ._plots import (
    serialize_phase_segments,
    serialize_phase_speed_breakdown,
    serialize_speed_breakdown,
)


def _float_list(stats: AccelStatisticsLike, key: str) -> list[float]:
    value = stats.get(key)
    if not isinstance(value, list):
        return []
    return [float(item) for item in value if isinstance(item, (int, float))]


def _int_value(stats: AccelStatisticsLike, key: str) -> int | None:
    value = stats.get(key)
    return int(value) if isinstance(value, (int, float)) else None


def noise_baseline_db(run_noise_baseline_g: float | None) -> float | None:
    """Convert a run noise baseline amplitude in g to dB, or return None."""
    if run_noise_baseline_g is None:
        return None
    result: float = compute_db(
        max(MEMS_NOISE_FLOOR_G, run_noise_baseline_g),
        MEMS_NOISE_FLOOR_G,
    )
    return result


def build_data_quality_dict(
    samples: Sequence[JsonObject],
    speed_values: list[float],
    speed_stats: SpeedProfileSummary,
    speed_non_null_pct: float,
    accel_stats: AccelStatisticsLike,
    amp_metric_values: list[float],
) -> DataQualityPayload:
    """Build the ``data_quality`` sub-dict for the persisted run summary."""
    sample_rows = list(samples)
    return {
        "required_missing_pct": {
            "t_s": _percent_missing(sample_rows, "t_s"),
            "speed_kmh": _percent_missing(sample_rows, "speed_kmh"),
            "accel_x": _percent_missing(sample_rows, "accel_x_g"),
            "accel_y": _percent_missing(sample_rows, "accel_y_g"),
            "accel_z": _percent_missing(sample_rows, "accel_z_g"),
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
            "x_mean": _as_float(accel_stats.get("x_mean")),
            "x_variance": _as_float(accel_stats.get("x_var")),
            "y_mean": _as_float(accel_stats.get("y_mean")),
            "y_variance": _as_float(accel_stats.get("y_var")),
            "z_mean": _as_float(accel_stats.get("z_mean")),
            "z_variance": _as_float(accel_stats.get("z_var")),
            "sensor_limit": _as_float(accel_stats.get("sensor_limit")),
            "saturation_count": _int_value(accel_stats, "sat_count"),
        },
        "outliers": {
            "accel_magnitude": cast(
                OutlierSummaryPayload,
                _json_outlier_summary(_float_list(accel_stats, "accel_mag_vals")),
            ),
            "amplitude_metric": cast(
                OutlierSummaryPayload,
                _json_outlier_summary(amp_metric_values),
            ),
        },
    }


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


def build_summary_payload(
    *,
    file_name: str,
    run_id: str,
    samples: list[JsonObject],
    duration_s: float,
    language: str,
    metadata: JsonObject,
    raw_sample_rate_hz: float | None,
    speed_breakdown: Sequence[SpeedBreakdownRowLike],
    phase_speed_breakdown: Sequence[PhaseSpeedBreakdownRowLike],
    phase_segments: Sequence[PhaseSegmentLike],
    run_noise_baseline_g: float | None,
    speed_breakdown_skipped_reason: JsonObject | None,
    findings: tuple[DomainFinding, ...],
    top_causes: tuple[DomainFinding, ...],
    most_likely_origin: VibrationOrigin | None,
    test_plan: list[TestPlanStepPayload],
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
    accel_stats: AccelStatisticsLike,
    amp_metric_values: list[float],
) -> AnalysisSummary:
    """Assemble the final summary payload from already-computed artifacts."""
    phase_timeline_payload: list[PhaseTimelineEntryPayload] = [
        {
            "phase": entry.phase.value,
            "start_t_s": entry.start_t_s,
            "end_t_s": entry.end_t_s,
            "speed_min_kmh": entry.speed_min_kmh,
            "speed_max_kmh": entry.speed_max_kmh,
            "has_fault_evidence": entry.has_fault_evidence,
        }
        for entry in phase_timeline
    ]
    return {
        "file_name": file_name,
        "run_id": run_id,
        "rows": len(samples),
        "duration_s": duration_s,
        "record_length": format_duration_mm_ss(duration_s),
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
        "speed_breakdown": serialize_speed_breakdown(speed_breakdown),
        "phase_speed_breakdown": serialize_phase_speed_breakdown(phase_speed_breakdown),
        "phase_segments": serialize_phase_segments(phase_segments),
        "run_noise_baseline_db": noise_baseline_db(run_noise_baseline_g),
        "speed_breakdown_skipped_reason": speed_breakdown_skipped_reason,
        "findings": serialize_findings(findings),
        "top_causes": serialize_findings(top_causes),
        "most_likely_origin": serialize_origin_summary(most_likely_origin),
        "test_plan": test_plan,
        "phase_timeline": phase_timeline_payload,
        "speed_stats": cast(SpeedStatsPayload, speed_stats.to_dict()),
        "speed_stats_by_phase": {
            k: cast(SpeedStatsPayload, v.to_dict()) for k, v in speed_stats_by_phase.items()
        },
        "phase_info": cast(PhaseInfoPayload, phase_info.to_dict()),
        "sensor_locations": sensor_locations,
        "sensor_locations_connected_throughout": sorted(connected_locations),
        "sensor_count_used": len(sensor_locations),
        "sensor_intensity_by_location": [
            cast(LocationIntensitySummaryPayload, asdict(row))
            for row in sensor_intensity_by_location
        ],
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
