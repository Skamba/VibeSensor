"""Structured orchestration for building analysis summaries from run samples."""

from __future__ import annotations

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
    _load_run,
    _run_noise_baseline_g,
    _speed_stats_by_phase,
    _validate_required_strength_metrics,
)
from .order_analysis import _i18n_ref
from .plot_data import _plot_data
from .strength_labels import strength_label as _strength_label
from .summary_models import (
    FindingsBundle,
    PreparedRunData,
    RunSuitabilityBundle,
    SensorAnalysisBundle,
    SummaryComputation,
)
from .summary_pipeline import (
    build_phase_timeline,
    build_run_suitability_checks,
    build_sensor_analysis,
    build_summary_payload,
    compute_accel_statistics,
    compute_reference_completeness,
    compute_run_timing,
    prepare_speed_and_phases,
    summarize_origin,
)
from .test_plan import _merge_test_plan
from .top_cause_selection import select_top_causes


def normalize_lang(lang: object) -> str:
    """Minimal language normalization without importing report_i18n."""
    raw = str(lang or "").strip().lower()
    return "nl" if raw.startswith("nl") else "en"


def annotate_peaks_with_order_labels(summary: dict[str, Any]) -> None:
    """Back-fill peak-table order labels by matching order findings to peak rows."""
    plots = summary.get("plots")
    if not isinstance(plots, dict):
        return
    peaks_table: list[dict[str, Any]] = plots.get("peaks_table", [])
    findings: list[dict[str, Any]] = summary.get("findings", [])
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
            try:
                freq = float(row.get("frequency_hz") or 0.0)
            except (TypeError, ValueError):
                continue
            dist = abs(freq - median_hz)
            if dist < best_dist:
                best_idx = idx
                best_dist = dist
        if best_idx is not None and best_dist <= tolerance_hz:
            peaks_table[best_idx]["order_label"] = label
            used_rows.add(best_idx)


def prepare_run_data(
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
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
    speed_breakdown_skipped_reason: object = None
    if not speed_sufficient:
        speed_breakdown_skipped_reason = _i18n_ref(
            "SPEED_DATA_MISSING_OR_INSUFFICIENT_SPEED_BINNED_AND"
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


def build_phase_summary(phase_segments: list[Any]) -> dict[str, Any]:
    """Small wrapper to keep summary-building imports localized."""
    from .phase_segmentation import phase_summary

    return phase_summary(phase_segments)


def build_findings_bundle(
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    *,
    language: str,
    prepared: PreparedRunData,
    overall_strength_band_key: str | None,
) -> FindingsBundle:
    """Build findings plus derived diagnosis narrative fields."""
    findings = _build_findings(
        metadata=metadata,
        samples=samples,
        speed_sufficient=prepared.speed_sufficient,
        steady_speed=bool(prepared.speed_stats.get("steady_speed")),
        speed_stddev_kmh=_as_float(prepared.speed_stats.get("stddev_kmh")),
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
    return FindingsBundle(
        findings=findings,
        most_likely_origin=most_likely_origin,
        test_plan=test_plan,
        phase_timeline=phase_timeline,
        top_causes=top_causes,
    )


def build_sensor_bundle(
    samples: list[dict[str, Any]],
    *,
    language: str,
    per_sample_phases: list[Any],
) -> SensorAnalysisBundle:
    """Build location-scoped sensor summaries used by analysis and reports."""
    sensor_locations, connected_locations, sensor_intensity_by_location = build_sensor_analysis(
        samples=samples,
        language=language,
        per_sample_phases=per_sample_phases,
    )
    return SensorAnalysisBundle(
        sensor_locations=sensor_locations,
        connected_locations=connected_locations,
        sensor_intensity_by_location=sensor_intensity_by_location,
    )


def build_run_suitability_bundle(
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    *,
    prepared: PreparedRunData,
    accel_stats: dict[str, Any],
) -> RunSuitabilityBundle:
    """Build run-suitability checks and related confidence context."""
    reference_complete = compute_reference_completeness(metadata)
    sensor_ids = {
        str(cid)
        for sample in samples
        if isinstance(sample, dict) and (cid := sample.get("client_id"))
    }
    run_suitability = build_run_suitability_checks(
        steady_speed=bool(prepared.speed_stats.get("steady_speed")),
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
    return RunSuitabilityBundle(
        reference_complete=reference_complete,
        run_suitability=run_suitability,
        overall_strength_band_key=overall_strength_band_key,
    )


def summarize_run_data(
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    lang: str | None = None,
    file_name: str = "run",
    include_samples: bool = True,
) -> dict[str, Any]:
    """Analyze pre-loaded run data and return the full summary dict."""
    language = normalize_lang(lang)
    _validate_required_strength_metrics(samples)

    prepared = prepare_run_data(metadata, samples, file_name=file_name)
    accel_stats = compute_accel_statistics(samples, metadata.get("sensor_model"))
    suitability = build_run_suitability_bundle(
        metadata,
        samples,
        prepared=prepared,
        accel_stats=accel_stats,
    )
    findings_bundle = build_findings_bundle(
        metadata,
        samples,
        language=language,
        prepared=prepared,
        overall_strength_band_key=suitability.overall_strength_band_key,
    )
    sensors = build_sensor_bundle(
        samples,
        language=language,
        per_sample_phases=prepared.per_sample_phases,
    )

    computation = SummaryComputation(
        prepared=prepared,
        accel_stats=accel_stats,
        findings=findings_bundle,
        sensors=sensors,
        suitability=suitability,
    )
    summary = build_summary_payload(
        file_name=file_name,
        run_id=computation.prepared.run_id,
        samples=samples,
        duration_s=computation.prepared.duration_s,
        language=language,
        metadata=metadata,
        raw_sample_rate_hz=computation.prepared.raw_sample_rate_hz,
        speed_breakdown=computation.prepared.speed_breakdown,
        phase_speed_breakdown=computation.prepared.phase_speed_breakdown,
        phase_segments=computation.prepared.phase_segments,
        run_noise_baseline_g=computation.prepared.run_noise_baseline_g,
        speed_breakdown_skipped_reason=computation.prepared.speed_breakdown_skipped_reason,
        findings=computation.findings.findings,
        top_causes=computation.findings.top_causes,
        most_likely_origin=computation.findings.most_likely_origin,
        test_plan=computation.findings.test_plan,
        phase_timeline=computation.findings.phase_timeline,
        speed_stats=computation.prepared.speed_stats,
        speed_stats_by_phase=computation.prepared.speed_stats_by_phase,
        phase_info=computation.prepared.phase_info,
        sensor_locations=computation.sensors.sensor_locations,
        connected_locations=computation.sensors.connected_locations,
        sensor_intensity_by_location=computation.sensors.sensor_intensity_by_location,
        run_suitability=computation.suitability.run_suitability,
        speed_values=computation.prepared.speed_values,
        speed_non_null_pct=computation.prepared.speed_non_null_pct,
        accel_stats=computation.accel_stats,
        amp_metric_values=computation.accel_stats["amp_metric_values"],
    )
    summary["report_date"] = metadata.get("end_time_utc") or utc_now_iso()
    summary["plots"] = _plot_data(
        summary,
        run_noise_baseline_g=computation.prepared.run_noise_baseline_g,
        per_sample_phases=computation.prepared.per_sample_phases,
        phase_segments=computation.prepared.phase_segments,
    )
    annotate_peaks_with_order_labels(summary)
    if not include_samples:
        summary.pop("samples", None)
    return summary


def build_findings_for_samples(
    *,
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    lang: str | None = None,
) -> list[dict[str, Any]]:
    """Build the findings list from *samples* using the full analysis pipeline."""
    language = normalize_lang(lang)
    rows = list(samples)
    _validate_required_strength_metrics(rows)
    prepared = prepare_run_data(metadata, rows, file_name="run")
    return _build_findings(
        metadata=dict(metadata),
        samples=rows,
        speed_sufficient=prepared.speed_sufficient,
        steady_speed=bool(prepared.speed_stats.get("steady_speed")),
        speed_stddev_kmh=_as_float(prepared.speed_stats.get("stddev_kmh")),
        speed_non_null_pct=prepared.speed_non_null_pct,
        raw_sample_rate_hz=prepared.raw_sample_rate_hz,
        lang=language,
        per_sample_phases=prepared.per_sample_phases,
    )


def summarize_log(
    log_path: Path,
    lang: str | None = None,
    include_samples: bool = True,
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
