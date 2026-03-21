"""Findings orchestration and compatibility re-exports for diagnostics helpers."""

from __future__ import annotations

from vibesensor.domain import Finding as DomainFinding
from vibesensor.shared.types.json_types import JsonObject

from . import _reference_findings
from ._peak_findings import (
    PeakBin,
    PeakFindingAnalyzer,
    _build_persistent_peak_findings,
    collect_order_frequencies,
    prepare_analysis_samples,
)
from ._types import PhaseLabels, Sample
from .helpers import _locations_connected_throughout_run, _tire_reference_from_metadata
from .order_pipeline import _build_order_findings
from .peak_binning import _classify_peak_type  # noqa: F401
from .signal_aggregation import (
    _phase_speed_breakdown,  # noqa: F401
    _sensor_intensity_by_location,  # noqa: F401
    _speed_breakdown,  # noqa: F401
)
from .speed_profile_helpers import (
    _phase_to_str,  # noqa: F401
    _speed_profile_from_points,  # noqa: F401
)

__all__ = [
    "PeakBin",
    "PeakFindingAnalyzer",
    "collect_order_frequencies",
    "finalize_findings",
    "prepare_analysis_samples",
]


def finalize_findings(
    findings: list[DomainFinding],
) -> tuple[DomainFinding, ...]:
    """Partition, rank by confidence, and assign stable ``F###`` IDs.

    Returns domain ``Finding`` objects in canonical order: references first,
    then diagnostics sorted by confidence/score, then informational.
    """
    refs = [finding for finding in findings if finding.is_reference]
    diags = sorted(
        [finding for finding in findings if finding.is_diagnostic],
        key=lambda finding: finding.rank_key,
        reverse=True,
    )
    infos = sorted(
        [finding for finding in findings if finding.is_informational],
        key=lambda finding: finding.rank_key,
        reverse=True,
    )
    counter = 0
    result: list[DomainFinding] = []
    for finding in refs + diags + infos:
        if not finding.is_reference:
            counter += 1
            finding = finding.with_id(f"F{counter:03d}")
        result.append(finding)
    return tuple(result)


def _build_findings(
    *,
    metadata: JsonObject,
    samples: list[Sample],
    speed_sufficient: bool,
    steady_speed: bool,
    speed_stddev_kmh: float | None,
    speed_non_null_pct: float,
    raw_sample_rate_hz: float | None,
    lang: str = "en",
    per_sample_phases: PhaseLabels | None = None,
    run_noise_baseline_g: float | None = None,
) -> tuple[DomainFinding, ...]:
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
        Domain Finding objects: references first, then diagnostics sorted
        by (quantised confidence, ranking_score) descending, then informational.

    """
    tire_circumference_m, _ = _tire_reference_from_metadata(metadata)
    findings: list[DomainFinding]
    findings, engine_ref_sufficient = _reference_findings.build_reference_findings(
        metadata=metadata,
        samples=samples,
        speed_sufficient=speed_sufficient,
        tire_circumference_m=tire_circumference_m,
        raw_sample_rate_hz=raw_sample_rate_hz,
    )
    analysis_samples, analysis_phases, _per_sample_phases, use_filtered_samples = (
        prepare_analysis_samples(
            samples,
            per_sample_phases=per_sample_phases,
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
        ),
    )
    return finalize_findings(findings)
