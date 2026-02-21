# ruff: noqa: E501
"""Output / aggregation: summaries, confidence labels, plot data, and public entry points."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from math import sqrt
from pathlib import Path
from typing import Any

from ..analysis_settings import tire_circumference_m_from_spec
from ..constants import WEAK_SPATIAL_DOMINANCE_THRESHOLD
from ..report_i18n import normalize_lang
from ..report_i18n import tr as _tr
from ..runlog import as_float_or_none as _as_float
from ..runlog import parse_iso8601
from .findings import (
    _build_findings,
    _sensor_intensity_by_location,
    _speed_breakdown,
)
from .helpers import (
    ORDER_MIN_CONFIDENCE,
    SPEED_COVERAGE_MIN_PCT,
    SPEED_MIN_POINTS,
    _format_duration,
    _load_run,
    _location_label,
    _locations_connected_throughout_run,
    _mean_variance,
    _outlier_summary,
    _percent_missing,
    _primary_vibration_strength_db,
    _sensor_limit_g,
    _speed_stats,
    _validate_required_strength_metrics,
)
from .phase_segmentation import (
    phase_summary as _phase_summary,
)
from .phase_segmentation import (
    segment_run_phases as _segment_run_phases,
)
from .plot_data import _plot_data
from .test_plan import _merge_test_plan

# ---------------------------------------------------------------------------
# Confidence label helper
# ---------------------------------------------------------------------------


def confidence_label(conf_0_to_1: float) -> tuple[str, str, str]:
    """Return (label_key, tone, pct_text) for a 0-1 confidence value.

    * label_key: i18n key  – CONFIDENCE_HIGH / CONFIDENCE_MEDIUM / CONFIDENCE_LOW
    * tone: card/pill tone  – 'success' / 'warn' / 'neutral'
    * pct_text: e.g. '82%'
    """
    pct = max(0.0, min(100.0, conf_0_to_1 * 100.0))
    pct_text = f"{pct:.0f}%"
    if conf_0_to_1 >= 0.70:
        return "CONFIDENCE_HIGH", "success", pct_text
    if conf_0_to_1 >= 0.40:
        return "CONFIDENCE_MEDIUM", "warn", pct_text
    return "CONFIDENCE_LOW", "neutral", pct_text


# ---------------------------------------------------------------------------
# Top-cause selection with drop-off rule and source grouping
# ---------------------------------------------------------------------------


def select_top_causes(
    findings: list[dict[str, object]],
    *,
    drop_off_points: float = 15.0,
    max_causes: int = 3,
) -> list[dict[str, object]]:
    """Group findings by suspected_source, keep best per group, apply drop-off."""
    # Only consider non-reference findings that meet the hard confidence floor
    diag_findings = [
        f
        for f in findings
        if isinstance(f, dict)
        and not str(f.get("finding_id", "")).startswith("REF_")
        and float(f.get("confidence_0_to_1") or 0) >= ORDER_MIN_CONFIDENCE
    ]
    if not diag_findings:
        transient_candidates = [
            f
            for f in findings
            if isinstance(f, dict)
            and not str(f.get("finding_id", "")).startswith("REF_")
            and (
                str(f.get("suspected_source") or "").strip().lower() == "transient_impact"
                or str(f.get("peak_classification") or "").strip().lower() == "transient"
            )
        ]
        if not transient_candidates:
            return []
        diag_findings = [
            max(transient_candidates, key=lambda f: float(f.get("confidence_0_to_1") or 0.0))
        ]

    # Group by suspected_source
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for f in diag_findings:
        src = str(f.get("suspected_source") or "unknown").strip().lower()
        groups[src].append(f)

    # For each group, pick the highest-confidence finding as representative
    group_reps: list[dict[str, object]] = []
    for members in groups.values():
        members_sorted = sorted(
            members,
            key=lambda m: float(m.get("confidence_0_to_1") or 0),
            reverse=True,
        )
        representative = dict(members_sorted[0])
        # Collect all signatures (frequency_hz_or_order) in this group
        signatures = []
        for m in members_sorted:
            sig = str(m.get("frequency_hz_or_order") or "").strip()
            if sig and sig not in signatures:
                signatures.append(sig)
        representative["signatures_observed"] = signatures
        representative["grouped_count"] = len(members_sorted)
        group_reps.append(representative)

    # Sort groups by best confidence descending
    group_reps.sort(
        key=lambda g: float(g.get("confidence_0_to_1") or 0),
        reverse=True,
    )

    # Apply drop-off rule: include causes within drop_off_points of the best
    best_conf_pct = float(group_reps[0].get("confidence_0_to_1") or 0) * 100.0
    threshold_pct = best_conf_pct - drop_off_points
    selected: list[dict[str, object]] = []
    for rep in group_reps:
        conf_pct = float(rep.get("confidence_0_to_1") or 0) * 100.0
        if conf_pct >= threshold_pct or not selected:
            selected.append(rep)
        if len(selected) >= max_causes:
            break

    # Build output in the format expected by the PDF
    result: list[dict[str, object]] = []
    for rep in selected:
        label_key, tone, pct_text = confidence_label(float(rep.get("confidence_0_to_1") or 0))
        result.append(
            {
                "finding_id": rep.get("finding_id"),
                "source": rep.get("suspected_source"),
                "confidence": rep.get("confidence_0_to_1"),
                "confidence_label_key": label_key,
                "confidence_tone": tone,
                "confidence_pct": pct_text,
                "order": rep.get("frequency_hz_or_order"),
                "signatures_observed": rep.get("signatures_observed", []),
                "grouped_count": rep.get("grouped_count", 1),
                "strongest_location": rep.get("strongest_location"),
                "dominance_ratio": rep.get("dominance_ratio"),
                "strongest_speed_band": rep.get("strongest_speed_band"),
                "weak_spatial_separation": rep.get("weak_spatial_separation"),
            }
        )
    return result


def _most_likely_origin_summary(
    findings: list[dict[str, object]], lang: object
) -> dict[str, object]:
    if not findings:
        return {
            "location": _tr(lang, "UNKNOWN"),
            "source": _tr(lang, "UNKNOWN"),
            "dominance_ratio": None,
            "weak_spatial_separation": True,
            "explanation": _tr(lang, "ORIGIN_NO_RANKED_FINDING_AVAILABLE"),
        }
    top = findings[0]
    location = str(top.get("strongest_location") or "").strip() or _tr(lang, "UNKNOWN")
    source = str(top.get("suspected_source") or "unknown")
    _source_i18n_map = {
        "wheel/tire": "SOURCE_WHEEL_TIRE",
        "driveline": "SOURCE_DRIVELINE",
        "engine": "SOURCE_ENGINE",
        "unknown": "UNKNOWN",
    }
    source_i18n_key = _source_i18n_map.get(source)
    source_human = (
        _tr(lang, source_i18n_key) if source_i18n_key else source.replace("_", " ").title()
    )
    dominance = _as_float(top.get("dominance_ratio"))
    weak = bool(top.get("weak_spatial_separation")) or (
        dominance is not None and dominance < WEAK_SPATIAL_DOMINANCE_THRESHOLD
    )

    # Spatial disambiguation: check if second-ranked finding disagrees on
    # location with similar confidence — strengthens the "weak" flag.
    spatial_disagreement = False
    if len(findings) >= 2:
        second = findings[1]
        second_loc = str(second.get("strongest_location") or "").strip()
        second_conf = _as_float(second.get("confidence_0_to_1")) or 0.0
        top_conf = _as_float(top.get("confidence_0_to_1")) or 0.0
        if (
            second_loc
            and location
            and second_loc != location
            and top_conf > 0
            and second_conf / top_conf >= 0.7  # within 30% confidence
        ):
            spatial_disagreement = True
            weak = True

    speed_band = str(top.get("strongest_speed_band") or _tr(lang, "UNKNOWN_SPEED_BAND"))
    explanation = _tr(
        lang,
        "ORIGIN_EXPLANATION_FINDING_1",
        source=source_human,
        speed_band=speed_band,
        location=location,
        dominance=(
            f"{dominance:.2f}x" if dominance is not None else _tr(lang, "NOT_APPLICABLE_SHORT")
        ),
    )
    if weak:
        explanation += " " + _tr(lang, "WEAK_SPATIAL_SEPARATION_INSPECT_NEARBY")
    return {
        "location": location,
        "source": source,
        "source_human": source_human,
        "dominance_ratio": dominance,
        "weak_spatial_separation": weak,
        "spatial_disagreement": spatial_disagreement,
        "speed_band": speed_band,
        "explanation": explanation,
    }


def build_findings_for_samples(
    *,
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    lang: str | None = None,
) -> list[dict[str, object]]:
    language = normalize_lang(lang)
    rows = list(samples) if isinstance(samples, list) else []
    _validate_required_strength_metrics(rows)
    speed_values = [
        speed
        for speed in (_as_float(sample.get("speed_kmh")) for sample in rows)
        if speed is not None and speed > 0
    ]
    speed_stats = _speed_stats(speed_values)
    speed_non_null_pct = (len(speed_values) / len(rows) * 100.0) if rows else 0.0
    speed_sufficient = (
        speed_non_null_pct >= SPEED_COVERAGE_MIN_PCT and len(speed_values) >= SPEED_MIN_POINTS
    )
    raw_sample_rate_hz = _as_float(metadata.get("raw_sample_rate_hz"))
    return _build_findings(
        metadata=dict(metadata),
        samples=rows,
        speed_sufficient=speed_sufficient,
        steady_speed=bool(speed_stats.get("steady_speed")),
        speed_stddev_kmh=_as_float(speed_stats.get("stddev_kmh")),
        speed_non_null_pct=speed_non_null_pct,
        raw_sample_rate_hz=raw_sample_rate_hz,
        lang=language,
    )


def summarize_run_data(
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    lang: str | None = None,
    file_name: str = "run",
    include_samples: bool = True,
) -> dict[str, object]:
    """Analyse pre-loaded run data and return the full summary dict.

    This is the single computation path used by both the History UI and the
    PDF report — callers must never re-derive metrics independently.
    """
    language = normalize_lang(lang)
    _validate_required_strength_metrics(samples)

    run_id = str(metadata.get("run_id") or f"run-{file_name}")
    start_ts = parse_iso8601(metadata.get("start_time_utc"))
    end_ts = parse_iso8601(metadata.get("end_time_utc"))

    if end_ts is None and samples:
        sample_max_t = max((_as_float(sample.get("t_s")) or 0.0) for sample in samples)
        if start_ts is not None:
            end_ts = start_ts.fromtimestamp(start_ts.timestamp() + sample_max_t, tz=UTC)
    duration_s = 0.0
    if start_ts is not None and end_ts is not None:
        duration_s = max(0.0, (end_ts - start_ts).total_seconds())
    elif samples:
        duration_s = max((_as_float(sample.get("t_s")) or 0.0) for sample in samples)

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

    # Phase segmentation
    _per_sample_phases, phase_segments = _segment_run_phases(samples)
    phase_info = _phase_summary(phase_segments)

    sensor_model = metadata.get("sensor_model")
    sensor_limit = _sensor_limit_g(sensor_model)
    accel_x_vals = [
        value
        for value in (_as_float(sample.get("accel_x_g")) for sample in samples)
        if value is not None
    ]
    accel_y_vals = [
        value
        for value in (_as_float(sample.get("accel_y_g")) for sample in samples)
        if value is not None
    ]
    accel_z_vals = [
        value
        for value in (_as_float(sample.get("accel_z_g")) for sample in samples)
        if value is not None
    ]
    accel_mag_vals = [
        sqrt((sample["x"] ** 2) + (sample["y"] ** 2) + (sample["z"] ** 2))
        for sample in (
            {
                "x": _as_float(row.get("accel_x_g")),
                "y": _as_float(row.get("accel_y_g")),
                "z": _as_float(row.get("accel_z_g")),
            }
            for row in samples
        )
        if sample["x"] is not None and sample["y"] is not None and sample["z"] is not None
    ]
    amp_metric_values = [
        value for value in (_primary_vibration_strength_db(sample) for sample in samples) if value
    ]

    sat_count = 0
    if sensor_limit is not None:
        sat_threshold = sensor_limit * 0.98
        sat_count = sum(
            1
            for sample in samples
            if any(
                abs(val) >= sat_threshold
                for val in (
                    _as_float(sample.get("accel_x_g")) or 0.0,
                    _as_float(sample.get("accel_y_g")) or 0.0,
                    _as_float(sample.get("accel_z_g")) or 0.0,
                )
            )
        )

    x_mean, x_var = _mean_variance(accel_x_vals)
    y_mean, y_var = _mean_variance(accel_y_vals)
    z_mean, z_var = _mean_variance(accel_z_vals)

    raw_sample_rate_hz = _as_float(metadata.get("raw_sample_rate_hz"))
    speed_breakdown = _speed_breakdown(samples) if speed_sufficient else []
    speed_breakdown_skipped_reason = None
    if not speed_sufficient:
        speed_breakdown_skipped_reason = _tr(
            language, "SPEED_DATA_MISSING_OR_INSUFFICIENT_SPEED_BINNED_AND"
        )

    findings = _build_findings(
        metadata=metadata,
        samples=samples,
        speed_sufficient=speed_sufficient,
        steady_speed=bool(speed_stats.get("steady_speed")),
        speed_stddev_kmh=_as_float(speed_stats.get("stddev_kmh")),
        speed_non_null_pct=speed_non_null_pct,
        raw_sample_rate_hz=raw_sample_rate_hz,
        lang=language,
    )
    most_likely_origin = _most_likely_origin_summary(findings, language)
    test_plan = _merge_test_plan(findings, language)

    metadata_dict = metadata if isinstance(metadata, dict) else {}
    reference_complete = bool(
        _as_float(metadata_dict.get("raw_sample_rate_hz"))
        and (
            _as_float(metadata_dict.get("tire_circumference_m"))
            or tire_circumference_m_from_spec(
                _as_float(metadata_dict.get("tire_width_mm")),
                _as_float(metadata_dict.get("tire_aspect_pct")),
                _as_float(metadata_dict.get("rim_in")),
            )
        )
        and (
            _as_float(metadata_dict.get("engine_rpm"))
            or (
                _as_float(metadata_dict.get("final_drive_ratio"))
                and _as_float(metadata_dict.get("current_gear_ratio"))
            )
        )
    )
    steady_speed = bool(speed_stats.get("steady_speed"))
    sensor_ids = {
        str(s.get("client_id") or "") for s in samples if isinstance(s, dict) and s.get("client_id")
    }
    sensor_count_sufficient = len(sensor_ids) >= 3
    run_suitability = [
        {
            "check": _tr(language, "SUITABILITY_CHECK_SPEED_VARIATION"),
            "state": "pass" if not steady_speed else "warn",
            "explanation": (
                _tr(language, "SUITABILITY_SPEED_VARIATION_PASS")
                if not steady_speed
                else _tr(language, "SUITABILITY_SPEED_VARIATION_WARN")
            ),
        },
        {
            "check": _tr(language, "SUITABILITY_CHECK_SENSOR_COVERAGE"),
            "state": "pass" if sensor_count_sufficient else "warn",
            "explanation": (
                _tr(language, "SUITABILITY_SENSOR_COVERAGE_PASS")
                if sensor_count_sufficient
                else _tr(language, "SUITABILITY_SENSOR_COVERAGE_WARN")
            ),
        },
        {
            "check": _tr(language, "SUITABILITY_CHECK_REFERENCE_COMPLETENESS"),
            "state": "pass" if reference_complete else "warn",
            "explanation": (
                _tr(language, "SUITABILITY_REFERENCE_COMPLETENESS_PASS")
                if reference_complete
                else _tr(language, "SUITABILITY_REFERENCE_COMPLETENESS_WARN")
            ),
        },
        {
            "check": _tr(language, "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS"),
            "state": "pass" if sat_count == 0 else "warn",
            "explanation": (
                _tr(language, "SUITABILITY_SATURATION_PASS")
                if sat_count == 0
                else _tr(language, "SUITABILITY_SATURATION_WARN", sat_count=sat_count)
            ),
        },
    ]

    # Aggregate dropped frames / queue overflow across all samples
    all_dropped = [
        _as_float(s.get("frames_dropped_total"))
        for s in samples
        if isinstance(s, dict) and _as_float(s.get("frames_dropped_total")) is not None
    ]
    all_overflow = [
        _as_float(s.get("queue_overflow_drops"))
        for s in samples
        if isinstance(s, dict) and _as_float(s.get("queue_overflow_drops")) is not None
    ]
    total_dropped = int(max(all_dropped) - min(all_dropped)) if len(all_dropped) >= 2 else 0
    total_overflow = int(max(all_overflow) - min(all_overflow)) if len(all_overflow) >= 2 else 0
    frame_issues = total_dropped + total_overflow
    run_suitability.append(
        {
            "check": _tr(language, "SUITABILITY_CHECK_FRAME_INTEGRITY"),
            "state": "pass" if frame_issues == 0 else "warn",
            "explanation": (
                _tr(language, "SUITABILITY_FRAME_INTEGRITY_PASS")
                if frame_issues == 0
                else _tr(
                    language,
                    "SUITABILITY_FRAME_INTEGRITY_WARN",
                    total_dropped=total_dropped,
                    total_overflow=total_overflow,
                )
            ),
        }
    )

    top_causes = select_top_causes(findings)

    sensor_locations = sorted(
        {
            _location_label(sample, lang=language)
            for sample in samples
            if isinstance(sample, dict) and _location_label(sample, lang=language)
        }
    )
    # Only include locations that were connected throughout the run for
    # intensity aggregation, so intermittent sensors don't skew results.
    connected_locations = _locations_connected_throughout_run(samples, lang=language)
    sensor_intensity_by_location = _sensor_intensity_by_location(
        samples,
        include_locations=set(sensor_locations),
        lang=language,
    )

    summary: dict[str, Any] = {
        "file_name": file_name,
        "run_id": run_id,
        "rows": len(samples),
        "duration_s": duration_s,
        "record_length": _format_duration(duration_s),
        "lang": language,
        "report_date": datetime.now(UTC).isoformat(),
        "start_time_utc": metadata.get("start_time_utc"),
        "end_time_utc": metadata.get("end_time_utc"),
        "sensor_model": metadata.get("sensor_model"),
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
        "speed_breakdown_skipped_reason": speed_breakdown_skipped_reason,
        "findings": findings,
        "top_causes": top_causes,
        "most_likely_origin": most_likely_origin,
        "test_plan": test_plan,
        "speed_stats": speed_stats,
        "phase_info": phase_info,
        "sensor_locations": sensor_locations,
        "sensor_locations_connected_throughout": sorted(connected_locations),
        "sensor_count_used": len(sensor_locations),
        "sensor_intensity_by_location": sensor_intensity_by_location,
        "sensor_statistics_by_location": sensor_intensity_by_location,
        "run_suitability": run_suitability,
        "samples": samples,
        "data_quality": {
            "required_missing_pct": {
                "t_s": _percent_missing(samples, "t_s"),
                "speed_kmh": _percent_missing(samples, "speed_kmh"),
                "accel_x_g": _percent_missing(samples, "accel_x_g"),
                "accel_y_g": _percent_missing(samples, "accel_y_g"),
                "accel_z_g": _percent_missing(samples, "accel_z_g"),
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
                "x_mean_g": x_mean,
                "x_variance_g2": x_var,
                "y_mean_g": y_mean,
                "y_variance_g2": y_var,
                "z_mean_g": z_mean,
                "z_variance_g2": z_var,
                "sensor_limit_g": sensor_limit,
                "saturation_count": sat_count,
            },
            "outliers": {
                "accel_magnitude_g": _outlier_summary(accel_mag_vals),
                "amplitude_metric": _outlier_summary(amp_metric_values),
            },
        },
    }
    summary["plots"] = _plot_data(summary)
    if not include_samples:
        summary.pop("samples", None)
    return summary


def summarize_log(
    log_path: Path, lang: str | None = None, include_samples: bool = True
) -> dict[str, object]:
    """Backward-compatible wrapper: reads a JSONL run file and analyses it."""
    metadata, samples, _warnings = _load_run(log_path)
    return summarize_run_data(
        metadata,
        samples,
        lang=lang,
        file_name=log_path.name,
        include_samples=include_samples,
    )
