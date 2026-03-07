"""Output / aggregation: summaries, confidence labels, plot data, and public entry points."""

from __future__ import annotations

__all__ = [
    "build_findings_for_samples",
    "confidence_label",
    "select_top_causes",
    "summarize_log",
    "summarize_run_data",
]

import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median as _median
from typing import Any

from ..runlog import as_float_or_none as _as_float
from ..runlog import utc_now_iso
from .diagnosis_candidates import non_reference_findings
from .findings.builder import _build_findings
from .findings.intensity import (
    _phase_speed_breakdown,
    _speed_breakdown,
)
from .helpers import (
    ORDER_MIN_CONFIDENCE,
    _load_run,
    _run_noise_baseline_g,
    _speed_stats_by_phase,
    _validate_required_strength_metrics,
)
from .order_analysis import _i18n_ref
from .phase_segmentation import (
    DrivingPhase,
    PhaseSegment,
)
from .phase_segmentation import (
    phase_summary as _phase_summary,
)
from .plot_data import _plot_data
from .strength_labels import (
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
)
from .strength_labels import (
    strength_label as _strength_label,
)
from .summary_pipeline import (
    build_data_quality_dict as _build_data_quality_dict_impl,
)
from .summary_pipeline import (
    build_phase_timeline as _build_phase_timeline_impl,
)
from .summary_pipeline import (
    build_run_suitability_checks as _build_run_suitability_checks_impl,
)
from .summary_pipeline import (
    build_sensor_analysis,
    build_summary_payload,
)
from .summary_pipeline import (
    compute_accel_statistics as _compute_accel_statistics_impl,
)
from .summary_pipeline import (
    compute_frame_integrity_counts as _compute_frame_integrity_counts_impl,
)
from .summary_pipeline import (
    compute_reference_completeness as _compute_reference_completeness_impl,
)
from .summary_pipeline import (
    compute_run_timing as _compute_run_timing_impl,
)
from .summary_pipeline import (
    noise_baseline_db as _noise_baseline_db_impl,
)
from .summary_pipeline import (
    prepare_speed_and_phases as _prepare_speed_and_phases_impl,
)
from .summary_pipeline import (
    serialize_phase_segments as _serialize_phase_segments_impl,
)
from .summary_pipeline import (
    summarize_origin as _summarize_origin_impl,
)
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
            v
            for pt in matched_pts
            if isinstance(pt, dict) and (v := _as_float(pt.get("matched_hz"))) is not None
        ]
        if not matched_freqs:
            continue
        median_hz = _median(matched_freqs)
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
    conf_0_to_1: float | None,
    *,
    strength_band_key: str | None = None,
) -> tuple[str, str, str]:
    """Return (label_key, tone, pct_text) for a 0-1 confidence value.

    * label_key: i18n key  – CONFIDENCE_HIGH / CONFIDENCE_MEDIUM / CONFIDENCE_LOW
    * tone: card/pill tone  – 'success' / 'warn' / 'neutral'
    * pct_text: e.g. '82%'

    Parameters
    ----------
    conf_0_to_1:
        Confidence value in [0, 1].  ``None`` is treated as ``0.0``.
    strength_band_key:
        Optional vibration-strength band key.  When set to ``"negligible"``,
        high confidence is capped to medium as a defensive label guard —
        mirrors the guard in :func:`certainty_label`.

    """
    conf = float(conf_0_to_1) if conf_0_to_1 is not None else 0.0
    # Guard non-finite values before pct arithmetic: float('nan') * 100 can
    # produce 100.0 via min(100.0, nan) (CPython behavior), giving pct_text
    # "100%" while nan comparisons force the label to "CONFIDENCE_LOW" —
    # an obviously inconsistent output. float('inf') silently returns
    # "CONFIDENCE_HIGH" for garbage input. Clamp both to 0.0 here.
    if not math.isfinite(conf):
        conf = 0.0
    pct = max(0.0, min(100.0, conf * 100.0))
    pct_text = f"{pct:.0f}%"
    if conf >= CONFIDENCE_HIGH_THRESHOLD:
        label_key, tone = "CONFIDENCE_HIGH", "success"
    elif conf >= CONFIDENCE_MEDIUM_THRESHOLD:
        label_key, tone = "CONFIDENCE_MEDIUM", "warn"
    else:
        label_key, tone = "CONFIDENCE_LOW", "neutral"
    if (strength_band_key or "").strip().lower() == "negligible" and label_key == "CONFIDENCE_HIGH":
        label_key, tone = "CONFIDENCE_MEDIUM", "warn"
    return label_key, tone, pct_text


# ---------------------------------------------------------------------------
# Top-cause selection with drop-off rule and source grouping
# ---------------------------------------------------------------------------


def _phase_ranking_score(finding: dict[str, Any]) -> float:
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


def _group_findings_by_source(
    diag_findings: list[dict[str, Any]],
) -> list[tuple[float, dict[str, Any]]]:
    """Group diagnostic findings by suspected source and return one representative per group.

    Each group representative is the finding with the highest phase-adjusted
    ranking score.  All unique order signatures observed in the group are
    collected into ``representative["signatures_observed"]`` so downstream
    callers can show the full set without re-grouping.

    Returns a list of ``(best_score, representative)`` pairs sorted by
    best_score descending.
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in diag_findings:
        src = str(f.get("suspected_source") or "unknown").strip().lower()
        groups[src].append(f)

    _rank = _phase_ranking_score
    group_reps: list[tuple[float, dict[str, Any]]] = []
    for members in groups.values():
        members_scored = sorted(
            ((_rank(m), m) for m in members),
            key=lambda t: t[0],
            reverse=True,
        )
        representative = dict(members_scored[0][1])
        signatures: list[str] = []
        seen_sigs: set[str] = set()
        for _score, m in members_scored:
            sig = str(m.get("frequency_hz_or_order") or "").strip()
            if sig and sig not in seen_sigs:
                signatures.append(sig)
                seen_sigs.add(sig)
        representative["signatures_observed"] = signatures
        representative["grouped_count"] = len(members_scored)
        group_reps.append((members_scored[0][0], representative))

    group_reps.sort(key=lambda t: t[0], reverse=True)
    return group_reps


def select_top_causes(
    findings: list[dict[str, Any]],
    *,
    drop_off_points: float = 15.0,
    max_causes: int = 3,
    strength_band_key: str | None = None,
) -> list[dict[str, Any]]:
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

    group_reps = _group_findings_by_source(diag_findings)

    # Apply drop-off rule using cached phase-adjusted scores
    best_score_pct = group_reps[0][0] * 100.0
    threshold_pct = best_score_pct - drop_off_points
    selected: list[dict[str, Any]] = []
    for score, rep in group_reps:
        score_pct = score * 100.0
        if score_pct >= threshold_pct or not selected:
            selected.append(rep)
        if len(selected) >= max_causes:
            break

    # Build output in the format expected by the PDF
    result: list[dict[str, Any]] = []
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


def _most_likely_origin_summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    return _summarize_origin_impl(findings)


def _build_phase_timeline(
    phase_segments: list[PhaseSegment],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _build_phase_timeline_impl(
        phase_segments,
        findings,
        min_confidence=ORDER_MIN_CONFIDENCE,
    )


def _serialize_phase_segments(
    phase_segments: list[PhaseSegment],
) -> list[dict[str, Any]]:
    return _serialize_phase_segments_impl(phase_segments)


def _noise_baseline_db(run_noise_baseline_g: float | None) -> float | None:
    return _noise_baseline_db_impl(run_noise_baseline_g)


def _prepare_speed_and_phases(
    samples: list[dict[str, Any]],
) -> tuple[list[float], dict[str, Any], float, bool, list[DrivingPhase], list[PhaseSegment]]:
    return _prepare_speed_and_phases_impl(samples)


def build_findings_for_samples(
    *,
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    lang: str | None = None,
) -> list[dict[str, Any]]:
    """Build the findings list from *samples* using the full analysis pipeline."""
    language = _normalize_lang(lang)
    rows = list(samples)
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
    return _compute_run_timing_impl(metadata, samples, file_name)


def _compute_accel_statistics(
    samples: list[dict[str, Any]],
    sensor_model: object,
) -> dict[str, Any]:
    return _compute_accel_statistics_impl(samples, sensor_model)


def _compute_frame_integrity_counts(
    samples: list[dict[str, Any]],
) -> tuple[int, int]:
    return _compute_frame_integrity_counts_impl(samples)


def _build_run_suitability_checks(
    steady_speed: bool,
    speed_sufficient: bool,
    sensor_ids: set[str],
    reference_complete: bool,
    sat_count: int,
    samples: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _build_run_suitability_checks_impl(
        steady_speed=steady_speed,
        speed_sufficient=speed_sufficient,
        sensor_ids=sensor_ids,
        reference_complete=reference_complete,
        sat_count=sat_count,
        samples=samples,
    )


def _compute_reference_completeness(metadata: dict[str, Any]) -> bool:
    return _compute_reference_completeness_impl(metadata)


def _build_data_quality_dict(
    samples: list[dict[str, Any]],
    speed_values: list[float],
    speed_stats: dict[str, Any],
    speed_non_null_pct: float,
    accel_stats: dict[str, Any],
    amp_metric_values: list[float],
) -> dict[str, Any]:
    return _build_data_quality_dict_impl(
        samples,
        speed_values,
        speed_stats,
        speed_non_null_pct,
        accel_stats,
        amp_metric_values,
    )


def summarize_run_data(
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    lang: str | None = None,
    file_name: str = "run",
    include_samples: bool = True,
) -> dict[str, Any]:
    """Analyse pre-loaded run data and return the full summary dict.

    This is the single computation path used by both the History UI and the
    PDF report — callers must never re-derive metrics independently.
    """
    language = _normalize_lang(lang)
    _validate_required_strength_metrics(samples)

    # --- Timing ---
    run_id, _start_ts, _end_ts, duration_s = _compute_run_timing(metadata, samples, file_name)

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
    _diagnostic_for_origin = non_reference_findings(findings)
    most_likely_origin = _most_likely_origin_summary(_diagnostic_for_origin)
    test_plan = _merge_test_plan(findings, language)
    phase_timeline = _build_phase_timeline(phase_segments, findings)

    # --- Reference completeness ---
    reference_complete = _compute_reference_completeness(metadata)

    # --- Run suitability checks ---
    steady_speed = bool(speed_stats.get("steady_speed"))
    sensor_ids = {str(cid) for s in samples if isinstance(s, dict) and (cid := s.get("client_id"))}
    run_suitability = _build_run_suitability_checks(
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
    sensor_locations, connected_locations, sensor_intensity_by_location = build_sensor_analysis(
        samples=samples,
        language=language,
        per_sample_phases=_per_sample_phases,
    )

    # --- Summary construction ---
    summary = build_summary_payload(
        file_name=file_name,
        run_id=run_id,
        samples=samples,
        duration_s=duration_s,
        language=language,
        metadata=metadata,
        raw_sample_rate_hz=raw_sample_rate_hz,
        speed_breakdown=speed_breakdown,
        phase_speed_breakdown=phase_speed_breakdown,
        phase_segments=phase_segments,
        run_noise_baseline_g=run_noise_baseline_g,
        speed_breakdown_skipped_reason=speed_breakdown_skipped_reason,
        findings=findings,
        top_causes=top_causes,
        most_likely_origin=most_likely_origin,
        test_plan=test_plan,
        phase_timeline=phase_timeline,
        speed_stats=speed_stats,
        speed_stats_by_phase=speed_stats_by_phase,
        phase_info=phase_info,
        sensor_locations=sensor_locations,
        connected_locations=connected_locations,
        sensor_intensity_by_location=sensor_intensity_by_location,
        run_suitability=run_suitability,
        speed_values=speed_values,
        speed_non_null_pct=speed_non_null_pct,
        accel_stats=accel_stats,
        amp_metric_values=amp_metric_values,
    )
    summary["report_date"] = metadata.get("end_time_utc") or utc_now_iso()
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
) -> dict[str, Any]:
    """Read a JSONL run file and analyse it."""
    metadata, samples, _warnings = _load_run(log_path)
    return summarize_run_data(
        metadata,
        samples,
        lang=lang,
        file_name=log_path.name,
        include_samples=include_samples,
    )
