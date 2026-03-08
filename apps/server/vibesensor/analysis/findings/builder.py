"""Main findings orchestrator – coordinates order, persistent-peak, and reference findings."""

from __future__ import annotations

from typing import Any

from .._types import PhaseLabels
from ..helpers import (
    _locations_connected_throughout_run,
    _tire_reference_from_metadata,
)
from ..phase_segmentation import segment_run_phases
from .builder_support import (
    build_reference_findings,
    collect_order_frequencies,
    finalize_findings,
    prepare_analysis_samples,
)
from .order_findings import _build_order_findings
from .persistent_findings import _build_persistent_peak_findings


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
    tire_circumference_m, _ = _tire_reference_from_metadata(metadata)
    findings, engine_ref_sufficient = build_reference_findings(
        metadata=metadata,
        samples=samples,
        speed_sufficient=speed_sufficient,
        speed_non_null_pct=speed_non_null_pct,
        tire_circumference_m=tire_circumference_m,
        raw_sample_rate_hz=raw_sample_rate_hz,
    )
    analysis_samples, analysis_phases, _per_sample_phases, use_filtered_samples = (
        prepare_analysis_samples(
            samples,
            per_sample_phases=per_sample_phases,
            phase_segmenter=segment_run_phases,
        )
    )

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
    order_freqs = collect_order_frequencies(order_findings)
    findings.extend(
        _build_persistent_peak_findings(
            samples=analysis_samples,  # IDLE-filtered; issue #191
            order_finding_freqs=order_freqs,
            lang=lang,
            per_sample_phases=analysis_phases,
            run_noise_baseline_g=(run_noise_baseline_g if not use_filtered_samples else None),
        )
    )
    return finalize_findings(findings)
