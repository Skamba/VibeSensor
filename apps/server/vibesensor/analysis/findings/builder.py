"""Main findings orchestrator – coordinates order, persistent-peak, and reference findings."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ...runlog import as_float_or_none as _as_float
from .._types import PhaseLabels
from ..helpers import (
    SPEED_COVERAGE_MIN_PCT,
    _effective_engine_rpm,
    _locations_connected_throughout_run,
    _tire_reference_from_metadata,
)
from ..order_analysis import _i18n_ref
from ..phase_segmentation import DrivingPhase, diagnostic_sample_mask, segment_run_phases
from ._constants import _ORDER_SUPPRESS_PERSISTENT_MIN_CONF
from .order_findings import _build_order_findings
from .persistent_findings import _build_persistent_peak_findings
from .reference_checks import _reference_missing_finding

_QUANTISE_STEP = 0.02
_QUANTISE_INV = 1.0 / _QUANTISE_STEP  # avoid division in hot path
_MIN_DIAGNOSTIC_SAMPLES = 5
"""Minimum number of diagnostic (non-IDLE) samples required to use phase-filtered
analysis.  Falls back to all samples when fewer than this remain after filtering."""


def _finding_sort_key(item: dict[str, Any]) -> tuple[float, float]:
    """Sort key: (quantised confidence, ranking_score) for deterministic ordering.

    Confidence is quantised to 0.02 steps so that findings whose
    confidence differs only due to noise/timing jitter are treated as
    equal, allowing the ranking_score (which properly incorporates
    signal amplitude) to break the tie.
    """
    conf = float(item.get("confidence_0_to_1", 0.0))
    quantised = round(conf * _QUANTISE_INV) * _QUANTISE_STEP
    rank = float(item.get("_ranking_score", 0.0))
    return (quantised, rank)


def _build_findings(
    *,
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    speed_sufficient: bool,
    steady_speed: bool,
    speed_stddev_kmh: float | None,
    speed_non_null_pct: float,
    raw_sample_rate_hz: float | None,
    lang: str = "en",
    per_sample_phases: PhaseLabels | None = None,
    run_noise_baseline_g: float | None = None,
) -> list[dict[str, Any]]:
    """Build and rank all findings for a completed run.

    Coordinates reference checks (speed, wheel, engine, sample-rate), order
    analysis, and persistent-peak detection.  Results are partitioned into
    reference / diagnostic / informational buckets and sorted so the most
    confident diagnostic finding appears first.

    Args:
        metadata: Run metadata dict (car settings, units, sample rate, etc.).
        samples: Per-metric-tick sample dicts for the run.
        speed_sufficient: Whether enough speed data was present for order analysis.
        steady_speed: Whether the speed was steady enough for reliable analysis.
        speed_stddev_kmh: Standard deviation of speed in km/h, or None.
        speed_non_null_pct: Percentage of samples with non-null speed (0-100).
        raw_sample_rate_hz: Accelerometer sample rate, or None if unknown.
        lang: ISO 639-1 language code for human-readable text (default "en").
        per_sample_phases: Optional pre-computed per-sample phase labels;
            recomputed from ``samples`` when not provided.
        run_noise_baseline_g: Optional ambient noise floor in g for this run.

    Returns:
        Ordered list of finding dicts: references first, then diagnostics sorted
        by (quantised confidence, ranking_score) descending, then informational.

    """
    findings: list[dict[str, Any]] = []
    tire_circumference_m, _ = _tire_reference_from_metadata(metadata)

    if not speed_sufficient:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_SPEED",
                suspected_source="unknown",
                evidence_summary=_i18n_ref(
                    "VEHICLE_SPEED_COVERAGE_IS_SPEED_NON_NULL_PCT",
                    speed_non_null_pct=speed_non_null_pct,
                    threshold=SPEED_COVERAGE_MIN_PCT,
                ),
                quick_checks=[
                    _i18n_ref("RECORD_VEHICLE_SPEED_FOR_MOST_SAMPLES_GPS_OR"),
                    _i18n_ref("VERIFY_TIMESTAMP_ALIGNMENT_BETWEEN_SPEED_AND_ACCELERATION_STREAM"),
                ],
            )
        )

    if speed_sufficient and not (tire_circumference_m and tire_circumference_m > 0):
        findings.append(
            _reference_missing_finding(
                finding_id="REF_WHEEL",
                suspected_source="wheel/tire",
                evidence_summary=_i18n_ref(
                    "VEHICLE_SPEED_IS_AVAILABLE_BUT_TIRE_CIRCUMFERENCE_REFERENCE",
                ),
                quick_checks=[
                    _i18n_ref("PROVIDE_TIRE_CIRCUMFERENCE_OR_TIRE_SIZE_WIDTH_ASPECT"),
                    _i18n_ref("RE_RUN_WITH_MEASURED_LOADED_TIRE_CIRCUMFERENCE"),
                ],
            )
        )

    _eff_rpm = _effective_engine_rpm  # local bind – called per sample
    engine_ref_count = sum(
        1 for s in samples if ((_eff_rpm(s, metadata, tire_circumference_m))[0] or 0) > 0
    )
    engine_rpm_non_null_pct = (engine_ref_count / len(samples) * 100.0) if samples else 0.0
    engine_ref_sufficient = engine_rpm_non_null_pct >= SPEED_COVERAGE_MIN_PCT
    if not engine_ref_sufficient:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_ENGINE",
                suspected_source="engine",
                evidence_summary=_i18n_ref(
                    "ENGINE_SPEED_REFERENCE_COVERAGE_IS_ENGINE_RPM_NON",
                    engine_rpm_non_null_pct=engine_rpm_non_null_pct,
                ),
                quick_checks=[
                    _i18n_ref("LOG_ENGINE_RPM_FROM_CAN_OBD_FOR_THE"),
                    _i18n_ref("KEEP_TIMESTAMP_BASE_SHARED_WITH_ACCELEROMETER_AND_SPEED"),
                ],
            )
        )

    if raw_sample_rate_hz is None or raw_sample_rate_hz <= 0:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_SAMPLE_RATE",
                suspected_source="unknown",
                evidence_summary=_i18n_ref("RAW_ACCELEROMETER_SAMPLE_RATE_IS_MISSING_SO_DOMINANT"),
                quick_checks=[_i18n_ref("RECORD_THE_TRUE_ACCELEROMETER_SAMPLE_RATE_IN_RUN")],
            )
        )

    # Phase-filter: exclude IDLE samples from order and persistent-peak analysis.
    # IDLE samples (engine-off / stationary) add broadband noise that dilutes
    # order-tracking evidence and inflates persistent-peak presence ratios.
    # Issues #190 and #191.
    # Use caller-supplied phases when available to avoid redundant recomputation.
    if per_sample_phases is not None and len(per_sample_phases) == len(samples):
        _per_sample_phases: list[DrivingPhase] = [
            phase if isinstance(phase, DrivingPhase) else DrivingPhase(str(phase))
            for phase in per_sample_phases
        ]
    else:
        _per_sample_phases, _ = segment_run_phases(samples)
    _diagnostic_mask = diagnostic_sample_mask(_per_sample_phases)
    diagnostic_samples = [s for s, keep in zip(samples, _diagnostic_mask, strict=True) if keep]
    # Fall back to all samples if phase filtering removes too many
    # (fewer than _MIN_DIAGNOSTIC_SAMPLES remaining)
    use_filtered_samples = len(diagnostic_samples) >= _MIN_DIAGNOSTIC_SAMPLES
    analysis_samples = diagnostic_samples if use_filtered_samples else samples
    # Compute per-sample phases aligned with analysis_samples for phase-evidence tracking.
    if analysis_samples is diagnostic_samples:
        analysis_phases: Sequence[DrivingPhase] = [
            p for p, keep in zip(_per_sample_phases, _diagnostic_mask, strict=True) if keep
        ]
    else:
        analysis_phases = list(_per_sample_phases)

    order_findings = _build_order_findings(
        metadata=metadata,
        samples=analysis_samples,
        speed_sufficient=speed_sufficient,
        steady_speed=steady_speed,
        speed_stddev_kmh=speed_stddev_kmh,
        tire_circumference_m=tire_circumference_m if speed_sufficient else None,
        engine_ref_sufficient=engine_ref_sufficient,
        raw_sample_rate_hz=raw_sample_rate_hz,
        connected_locations=_locations_connected_throughout_run(analysis_samples, lang=lang),
        lang=lang,
        per_sample_phases=list(analysis_phases),
    )
    findings.extend(order_findings)

    # Collect frequencies claimed by order findings to avoid duplicate
    # persistent-peak findings.  Only suppress persistent peaks when the
    # order finding has moderate confidence — a marginal order match
    # (e.g. single-sensor constant-speed with conf ≈ 0.27) should not
    # mask a more confident persistent-peak interpretation.
    order_freqs: set[float] = set()
    for of in order_findings:
        if float(of.get("confidence_0_to_1", 0)) < _ORDER_SUPPRESS_PERSISTENT_MIN_CONF:
            continue
        pts = of.get("matched_points")
        if isinstance(pts, list):
            for pt in pts:
                if isinstance(pt, dict):
                    mhz = _as_float(pt.get("matched_hz"))
                    if mhz is not None and mhz > 0:
                        order_freqs.add(mhz)

    findings.extend(
        _build_persistent_peak_findings(
            samples=analysis_samples,  # IDLE-filtered; issue #191
            order_finding_freqs=order_freqs,
            lang=lang,
            per_sample_phases=analysis_phases,
            run_noise_baseline_g=(run_noise_baseline_g if not use_filtered_samples else None),
        )
    )

    # Single-pass classification: reference → diagnostic → informational
    reference_findings: list[dict[str, Any]] = []
    diagnostic_findings: list[dict[str, Any]] = []
    informational_findings: list[dict[str, Any]] = []
    for item in findings:
        fid = str(item.get("finding_id", ""))
        if fid.startswith("REF_"):
            reference_findings.append(item)
        elif str(item.get("severity") or "").strip().lower() == "info":
            informational_findings.append(item)
        else:
            diagnostic_findings.append(item)

    diagnostic_findings.sort(key=_finding_sort_key, reverse=True)
    informational_findings.sort(key=_finding_sort_key, reverse=True)
    findings = reference_findings + diagnostic_findings + informational_findings
    diag_counter = 0
    for finding in findings:
        fid = str(finding.get("finding_id", "")).strip()
        if not fid.startswith("REF_"):
            diag_counter += 1
            finding["finding_id"] = f"F{diag_counter:03d}"
    return findings
