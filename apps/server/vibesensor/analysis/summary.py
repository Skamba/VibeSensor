"""Output / aggregation: summaries, confidence labels, plot data, and public entry points."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta
from math import sqrt
from pathlib import Path
from statistics import median as _median
from typing import Any

from vibesensor_core.vibration_strength import (
    vibration_strength_db_scalar as canonical_vibration_db,
)

from ..analysis_settings import tire_circumference_m_from_spec
from ..runlog import as_float_or_none as _as_float
from ..runlog import parse_iso8601, utc_now_iso
from .findings import (
    _build_findings,
    _phase_speed_breakdown,
    _sensor_intensity_by_location,
    _speed_breakdown,
)
from .helpers import (
    MEMS_NOISE_FLOOR_G,
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
    _run_noise_baseline_g,
    _sensor_limit_g,
    _speed_stats,
    _speed_stats_by_phase,
    _validate_required_strength_metrics,
    counter_delta,
    weak_spatial_dominance_threshold,
)
from .order_analysis import _i18n_ref
from .phase_segmentation import (
    phase_summary as _phase_summary,
)
from .phase_segmentation import (
    segment_run_phases as _segment_run_phases,
)
from .plot_data import _plot_data
from .strength_labels import strength_label as _strength_label
from .test_plan import _merge_test_plan


def _normalize_lang(lang: object) -> str:
    """Minimal language normalization without importing report_i18n."""
    raw = str(lang or "").strip().lower()
    return "nl" if raw.startswith("nl") else "en"


# Language-neutral placeholder for unknown/missing values in analysis output.
_UNKNOWN = "unknown"

# ---------------------------------------------------------------------------
# Peak-table order-label annotation
# ---------------------------------------------------------------------------


def _annotate_peaks_with_order_labels(summary: dict[str, Any]) -> None:
    """Back-fill ``order_label`` on peaks-table rows from order findings.

    The peaks table is built independently of findings, so order_label is
    always empty.  This post-processing step matches each order finding's
    median matched frequency to the closest peak row (within a tolerance)
    and copies the order label (e.g. "1x wheel order") into the peak row.
    """
    plots = summary.get("plots")
    if not isinstance(plots, dict):
        return
    peaks_table: list[dict[str, Any]] = plots.get("peaks_table", [])
    findings: list[dict[str, Any]] = summary.get("findings", [])
    if not peaks_table or not findings:
        return

    # Collect (median_matched_hz, order_label) from F_ORDER findings.
    order_annotations: list[tuple[float, str]] = []
    for f in findings:
        if f.get("finding_id") != "F_ORDER":
            continue
        label = str(f.get("frequency_hz_or_order") or "").strip()
        if not label:
            continue
        matched_pts = f.get("matched_points")
        if not isinstance(matched_pts, list) or not matched_pts:
            continue
        matched_freqs = [
            float(pt["matched_hz"])
            for pt in matched_pts
            if isinstance(pt, dict) and pt.get("matched_hz") is not None
        ]
        if not matched_freqs:
            continue
        matched_freqs.sort()
        n = len(matched_freqs)
        median_hz = (
            matched_freqs[n // 2]
            if n % 2 == 1
            else (matched_freqs[n // 2 - 1] + matched_freqs[n // 2]) / 2.0
        )
        order_annotations.append((median_hz, label))

    if not order_annotations:
        return

    # For each order annotation, find the closest peak row within tolerance.
    # Use 2 Hz tolerance (generous enough for freq_bin_hz=1.0 default).
    tolerance_hz = 2.0
    used_rows: set[int] = set()
    for median_hz, label in order_annotations:
        best_idx: int | None = None
        best_dist = tolerance_hz + 1.0
        for idx, row in enumerate(peaks_table):
            if idx in used_rows:
                continue
            try:
                freq = float(row.get("frequency_hz") or 0.0)
            except (ValueError, TypeError):
                continue
            dist = abs(freq - median_hz)
            if dist < best_dist:
                best_dist = dist
                best_idx = idx
        if best_idx is not None and best_dist <= tolerance_hz:
            peaks_table[best_idx]["order_label"] = label
            used_rows.add(best_idx)


# ---------------------------------------------------------------------------
# Confidence label helper
# ---------------------------------------------------------------------------


def confidence_label(
    conf_0_to_1: float,
    *,
    strength_band_key: str | None = None,
) -> tuple[str, str, str]:
    """Return (label_key, tone, pct_text) for a 0-1 confidence value.

    * label_key: i18n key  – CONFIDENCE_HIGH / CONFIDENCE_MEDIUM / CONFIDENCE_LOW
    * tone: card/pill tone  – 'success' / 'warn' / 'neutral'
    * pct_text: e.g. '82%'

    Parameters
    ----------
    strength_band_key:
        Optional vibration-strength band key.  When set to ``"negligible"``,
        high confidence is capped to medium as a defensive label guard —
        mirrors the guard in :func:`certainty_label`.
    """
    pct = max(0.0, min(100.0, (conf_0_to_1 or 0.0) * 100.0))
    pct_text = f"{pct:.0f}%"
    conf = conf_0_to_1 if conf_0_to_1 is not None else 0.0
    if conf >= 0.70:
        label_key, tone = "CONFIDENCE_HIGH", "success"
    elif conf >= 0.40:
        label_key, tone = "CONFIDENCE_MEDIUM", "warn"
    else:
        label_key, tone = "CONFIDENCE_LOW", "neutral"
    if (strength_band_key or "").strip().lower() == "negligible" and label_key == "CONFIDENCE_HIGH":
        label_key, tone = "CONFIDENCE_MEDIUM", "warn"
    return label_key, tone, pct_text


# ---------------------------------------------------------------------------
# Top-cause selection with drop-off rule and source grouping
# ---------------------------------------------------------------------------


def _phase_ranking_score(finding: dict[str, object]) -> float:
    """Compute phase-adjusted ranking score for top-cause selection.

    Boosts findings with strong CRUISE-phase evidence (steady driving provides
    the most reliable vibration signature) by up to 15%.  Findings without
    phase evidence receive a neutral multiplier (0.85) and are ranked purely
    by confidence.
    """
    conf = finding.get("confidence_0_to_1")
    confidence = float(conf if conf is not None else 0)
    phase_ev = finding.get("phase_evidence")
    cruise_fraction = (
        float(phase_ev.get("cruise_fraction", 0.0)) if isinstance(phase_ev, dict) else 0.0
    )
    return confidence * (0.85 + 0.15 * cruise_fraction)


def select_top_causes(
    findings: list[dict[str, object]],
    *,
    drop_off_points: float = 15.0,
    max_causes: int = 3,
    strength_band_key: str | None = None,
) -> list[dict[str, object]]:
    """Group findings by suspected_source, keep best per group, apply drop-off.

    Ranking uses a phase-adjusted score that boosts findings whose evidence
    comes predominantly from CRUISE phase (steady driving), where vibration
    signatures are most diagnostically reliable.
    """
    # Only consider non-reference findings that meet the hard confidence floor
    diag_findings = [
        f
        for f in findings
        if isinstance(f, dict)
        and not str(f.get("finding_id", "")).startswith("REF_")
        and str(f.get("severity") or "diagnostic").strip().lower() != "info"
        and (_as_float(f.get("confidence_0_to_1")) or 0) >= ORDER_MIN_CONFIDENCE
    ]
    if not diag_findings:
        return []

    # Group by suspected_source
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for f in diag_findings:
        src = str(f.get("suspected_source") or "unknown").strip().lower()
        groups[src].append(f)

    # For each group, pick the highest-phase-adjusted-score finding as representative
    group_reps: list[dict[str, object]] = []
    for members in groups.values():
        members_sorted = sorted(
            members,
            key=_phase_ranking_score,
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

    # Sort groups by phase-adjusted score descending
    group_reps.sort(key=_phase_ranking_score, reverse=True)

    # Apply drop-off rule using phase-adjusted scores
    best_score_pct = _phase_ranking_score(group_reps[0]) * 100.0
    threshold_pct = best_score_pct - drop_off_points
    selected: list[dict[str, object]] = []
    for rep in group_reps:
        score_pct = _phase_ranking_score(rep) * 100.0
        if score_pct >= threshold_pct or not selected:
            selected.append(rep)
        if len(selected) >= max_causes:
            break

    # Build output in the format expected by the PDF
    result: list[dict[str, object]] = []
    for rep in selected:
        label_key, tone, pct_text = confidence_label(
            _as_float(rep.get("confidence_0_to_1")) or 0,
            strength_band_key=strength_band_key,
        )
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
                "diffuse_excitation": rep.get("diffuse_excitation", False),
                "diagnostic_caveat": rep.get("diagnostic_caveat"),
                "phase_evidence": rep.get("phase_evidence"),
            }
        )
    return result


def _most_likely_origin_summary(
    findings: list[dict[str, object]], lang: object
) -> dict[str, object]:
    if not findings:
        return {
            "location": _UNKNOWN,
            "alternative_locations": [],
            "source": _UNKNOWN,
            "dominance_ratio": None,
            "weak_spatial_separation": True,
            "explanation": _i18n_ref("ORIGIN_NO_RANKED_FINDING_AVAILABLE"),
        }
    top = findings[0]
    primary_location = str(top.get("strongest_location") or "").strip() or _UNKNOWN
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

    source = str(top.get("suspected_source") or _UNKNOWN)
    dominance = _as_float(top.get("dominance_ratio"))
    location_hotspot = top.get("location_hotspot")
    location_count = _as_float(top.get("location_count"))
    if location_count is None and isinstance(location_hotspot, dict):
        location_count = _as_float(location_hotspot.get("location_count"))
    adaptive_weak_spatial_threshold = weak_spatial_dominance_threshold(
        int(location_count) if location_count else None
    )
    weak = bool(top.get("weak_spatial_separation")) or (
        dominance is not None and dominance < adaptive_weak_spatial_threshold
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
            and primary_location
            and second_loc != primary_location
            and top_conf > 0
            and second_conf / top_conf >= 0.7  # within 30% confidence
        ):
            spatial_disagreement = True
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
            speed_band=speed_band or _UNKNOWN,
            location=location,
            dominance=f"{dominance:.2f}x" if dominance is not None else "n/a",
        ),
    ]
    if weak:
        explanation_parts.append(_i18n_ref("WEAK_SPATIAL_SEPARATION_INSPECT_NEARBY"))
    dominant_phase = str(top.get("dominant_phase") or "").strip()
    _phase_i18n_map = {
        "acceleration": "DRIVING_PHASE_ACCELERATION",
        "deceleration": "DRIVING_PHASE_DECELERATION",
        "coast_down": "DRIVING_PHASE_COAST_DOWN",
    }
    if dominant_phase and dominant_phase in _phase_i18n_map:
        explanation_parts.append(_i18n_ref("ORIGIN_PHASE_ONSET_NOTE", phase=dominant_phase))
    # Store explanation as structured i18n parts for render-time resolution.
    explanation = explanation_parts[0] if len(explanation_parts) == 1 else explanation_parts
    return {
        "location": location,
        "alternative_locations": alternative_locations,
        "source": source,
        "dominance_ratio": dominance,
        "weak_spatial_separation": weak,
        "spatial_disagreement": spatial_disagreement,
        "speed_band": speed_band or None,
        "dominant_phase": dominant_phase or None,
        "explanation": explanation,
    }


def _build_phase_timeline(
    phase_segments: list,
    findings: list[dict[str, object]],
    lang: object,
) -> list[dict[str, object]]:
    """Build a simple timeline summary: what changed when.

    Returns a list of timeline entries with phase, time window, speed range,
    and whether fault evidence was detected in that segment.
    """
    if not phase_segments:
        return []

    # Determine which phases have strong finding evidence
    finding_phases: set[str] = set()
    for f in findings:
        if not isinstance(f, dict):
            continue
        if str(f.get("finding_id", "")).startswith("REF_"):
            continue
        conf = float(f.get("confidence_0_to_1") or 0)
        if conf < ORDER_MIN_CONFIDENCE:
            continue
        phase_ev = f.get("phase_evidence")
        if isinstance(phase_ev, dict):
            for p in phase_ev.get("phases_detected", []):
                finding_phases.add(str(p))

    entries: list[dict[str, object]] = []
    for seg in phase_segments:
        phase_val = seg.phase.value if hasattr(seg, "phase") else str(seg.get("phase", ""))
        start_t = seg.start_t_s if hasattr(seg, "start_t_s") else float(seg.get("start_t_s", 0))
        end_t = seg.end_t_s if hasattr(seg, "end_t_s") else float(seg.get("end_t_s", 0))
        # Convert NaN sentinels (unknown time) to None for JSON safety.
        if isinstance(start_t, float) and math.isnan(start_t):
            start_t = None
        if isinstance(end_t, float) and math.isnan(end_t):
            end_t = None
        speed_min = seg.speed_min_kmh if hasattr(seg, "speed_min_kmh") else seg.get("speed_min_kmh")
        speed_max = seg.speed_max_kmh if hasattr(seg, "speed_max_kmh") else seg.get("speed_max_kmh")
        has_fault_evidence = phase_val in finding_phases

        entries.append(
            {
                "phase": phase_val,
                "start_t_s": start_t,
                "end_t_s": end_t,
                "speed_min_kmh": speed_min,
                "speed_max_kmh": speed_max,
                "has_fault_evidence": has_fault_evidence,
            }
        )
    return entries


def _prepare_speed_and_phases(
    samples: list[dict[str, Any]],
) -> tuple[list[float], dict, float, bool, list, list]:
    """Compute speed stats and phase segmentation shared by multiple entry points.

    Returns ``(speed_values, speed_stats, speed_non_null_pct,
    speed_sufficient, per_sample_phases, phase_segments)``.
    """
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
    per_sample_phases, phase_segments = _segment_run_phases(samples)
    return (
        speed_values,
        speed_stats,
        speed_non_null_pct,
        speed_sufficient,
        per_sample_phases,
        phase_segments,
    )


def build_findings_for_samples(
    *,
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    lang: str | None = None,
) -> list[dict[str, object]]:
    language = _normalize_lang(lang)
    rows = list(samples) if isinstance(samples, list) else []
    _validate_required_strength_metrics(rows)
    _, speed_stats, speed_non_null_pct, speed_sufficient, _per_sample_phases, _ = (
        _prepare_speed_and_phases(rows)
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
        per_sample_phases=_per_sample_phases,
    )


def _compute_run_timing(
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


def _compute_accel_statistics(
    samples: list[dict[str, Any]],
    sensor_model: object,
) -> dict[str, Any]:
    """Compute per-axis accel lists, magnitude, amplitude metric, saturation and mean/variance."""
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
        value
        for value in (_primary_vibration_strength_db(sample) for sample in samples)
        if value is not None
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


def _build_run_suitability_checks(
    language: str,
    steady_speed: bool,
    speed_sufficient: bool,
    sensor_ids: set[str],
    reference_complete: bool,
    sat_count: int,
    samples: list[dict[str, Any]],
) -> list[dict[str, object]]:
    """Construct the run-suitability checklist (speed, sensors, reference, saturation, frames).

    Output is language-neutral: ``check`` stores the i18n key directly and
    ``explanation`` stores an i18n reference dict for render-time translation.
    """
    sensor_count_sufficient = len(sensor_ids) >= 3
    speed_variation_ok = speed_sufficient and not steady_speed
    run_suitability: list[dict[str, object]] = [
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

    # Aggregate dropped frames / queue overflow across all samples.
    # Compute per-sensor deltas (max - min per client) to avoid mixing
    # cumulative counters from different sensors.
    _per_client_dropped: dict[str, list[float]] = defaultdict(list)
    _per_client_overflow: dict[str, list[float]] = defaultdict(list)
    for s in samples:
        if not isinstance(s, dict):
            continue
        cid = str(s.get("client_id") or "")
        if not cid:
            continue
        d = _as_float(s.get("frames_dropped_total"))
        if d is not None:
            _per_client_dropped[cid].append(d)
        o = _as_float(s.get("queue_overflow_drops"))
        if o is not None:
            _per_client_overflow[cid].append(o)

    total_dropped = sum(counter_delta(vals) for vals in _per_client_dropped.values())
    total_overflow = sum(counter_delta(vals) for vals in _per_client_overflow.values())
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
    language = _normalize_lang(lang)
    _validate_required_strength_metrics(samples)

    # --- Timing ---
    run_id, start_ts, end_ts, duration_s = _compute_run_timing(metadata, samples, file_name)

    # --- Speed & phase (shared computation) ---
    (
        speed_values,
        speed_stats,
        speed_non_null_pct,
        speed_sufficient,
        _per_sample_phases,
        phase_segments,
    ) = _prepare_speed_and_phases(samples)
    run_noise_baseline_g = _run_noise_baseline_g(samples)

    phase_info = _phase_summary(phase_segments)
    speed_stats_by_phase = _speed_stats_by_phase(samples, _per_sample_phases)

    # --- Acceleration statistics ---
    accel_stats = _compute_accel_statistics(samples, metadata.get("sensor_model"))

    raw_sample_rate_hz = _as_float(metadata.get("raw_sample_rate_hz"))
    # --- Speed breakdown ---
    speed_breakdown = _speed_breakdown(samples) if speed_sufficient else []
    speed_breakdown_skipped_reason: object = None
    if not speed_sufficient:
        speed_breakdown_skipped_reason = _i18n_ref(
            "SPEED_DATA_MISSING_OR_INSUFFICIENT_SPEED_BINNED_AND"
        )

    # Phase-grouped speed breakdown (issue #189)
    phase_speed_breakdown = _phase_speed_breakdown(samples, _per_sample_phases)

    # --- Findings ---
    findings = _build_findings(
        metadata=metadata,
        samples=samples,
        speed_sufficient=speed_sufficient,
        steady_speed=bool(speed_stats.get("steady_speed")),
        speed_stddev_kmh=_as_float(speed_stats.get("stddev_kmh")),
        speed_non_null_pct=speed_non_null_pct,
        raw_sample_rate_hz=raw_sample_rate_hz,
        lang=language,
        per_sample_phases=_per_sample_phases,
        run_noise_baseline_g=run_noise_baseline_g,
    )
    # Filter out REF_ reference-missing findings so origin summary is based
    # on actual diagnostic findings, not reference gaps (e.g. REF_ENGINE).
    _diagnostic_for_origin = [
        f for f in findings if not str(f.get("finding_id", "")).startswith("REF_")
    ]
    most_likely_origin = _most_likely_origin_summary(_diagnostic_for_origin, language)
    test_plan = _merge_test_plan(findings, language)
    phase_timeline = _build_phase_timeline(phase_segments, findings, language)

    # --- Reference completeness ---
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

    # --- Run suitability checks ---
    steady_speed = bool(speed_stats.get("steady_speed"))
    sensor_ids = {
        str(s.get("client_id") or "") for s in samples if isinstance(s, dict) and s.get("client_id")
    }
    run_suitability = _build_run_suitability_checks(
        language=language,
        steady_speed=steady_speed,
        speed_sufficient=speed_sufficient,
        sensor_ids=sensor_ids,
        reference_complete=reference_complete,
        sat_count=accel_stats["sat_count"],
        samples=samples,
    )

    # Derive overall run strength band for confidence-label guard
    amp_metric_values = accel_stats["amp_metric_values"]
    _median_db = _median(amp_metric_values) if amp_metric_values else None
    _overall_band_key = _strength_label(_median_db)[0] if _median_db is not None else None

    # --- Top-cause selection ---
    top_causes = select_top_causes(findings, strength_band_key=_overall_band_key)

    # --- Sensor analysis ---
    sensor_locations = sorted(
        {
            _location_label(sample, lang=language)
            for sample in samples
            if isinstance(sample, dict) and _location_label(sample, lang=language)
        }
    )
    # Mark and de-prioritize sensors not connected throughout the run,
    # so intermittent sensors don't skew strongest-location ranking.
    connected_locations = _locations_connected_throughout_run(samples, lang=language)
    sensor_intensity_by_location = _sensor_intensity_by_location(
        samples,
        include_locations=set(sensor_locations),
        lang=language,
        connected_locations=connected_locations,
        per_sample_phases=_per_sample_phases,  # phase context; issue #192
    )

    # --- Summary construction ---
    summary: dict[str, Any] = {
        "file_name": file_name,
        "run_id": run_id,
        "rows": len(samples),
        "duration_s": duration_s,
        "record_length": _format_duration(duration_s),
        "lang": language,
        "report_date": metadata.get("end_time_utc") or utc_now_iso(),
        "start_time_utc": metadata.get("start_time_utc"),
        "end_time_utc": metadata.get("end_time_utc"),
        "sensor_model": metadata.get("sensor_model"),
        "firmware_version": metadata.get("firmware_version"),
        "raw_sample_rate_hz": raw_sample_rate_hz,
        "feature_interval_s": _as_float(metadata.get("feature_interval_s")),
        "fft_window_size_samples": metadata.get("fft_window_size_samples"),
        "fft_window_type": metadata.get("fft_window_type"),
        "peak_picker_method": metadata.get("peak_picker_method"),
        "accel_scale_per_lsb": _as_float(metadata.get("accel_scale_g_per_lsb")),
        "incomplete_for_order_analysis": bool(metadata.get("incomplete_for_order_analysis")),
        "metadata": metadata,
        "warnings": [],
        "speed_breakdown": speed_breakdown,
        "phase_speed_breakdown": phase_speed_breakdown,
        "phase_segments": [
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
                    None
                    if isinstance(seg.end_t_s, float) and math.isnan(seg.end_t_s)
                    else seg.end_t_s
                ),
                "speed_min_kmh": seg.speed_min_kmh,
                "speed_max_kmh": seg.speed_max_kmh,
                "sample_count": seg.sample_count,
            }
            for seg in phase_segments
        ],
        "run_noise_baseline_db": (
            canonical_vibration_db(
                peak_band_rms_amp_g=max(MEMS_NOISE_FLOOR_G, run_noise_baseline_g),
                floor_amp_g=MEMS_NOISE_FLOOR_G,
            )
            if run_noise_baseline_g is not None
            else None
        ),
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
        "data_quality": {
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
        },
    }
    # --- Plot generation & peak annotation ---
    summary["plots"] = _plot_data(
        summary,
        run_noise_baseline_g=run_noise_baseline_g,
        per_sample_phases=_per_sample_phases,
        phase_segments=phase_segments,
    )
    _annotate_peaks_with_order_labels(summary)
    if not include_samples:
        summary.pop("samples", None)
    return summary


def summarize_log(
    log_path: Path, lang: str | None = None, include_samples: bool = True
) -> dict[str, object]:
    """Reads a JSONL run file and analyses it."""
    metadata, samples, _warnings = _load_run(log_path)
    return summarize_run_data(
        metadata,
        samples,
        lang=lang,
        file_name=log_path.name,
        include_samples=include_samples,
    )
