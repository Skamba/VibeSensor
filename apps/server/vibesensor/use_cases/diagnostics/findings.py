"""Findings orchestration and compatibility re-exports for diagnostics helpers."""

from __future__ import annotations

from collections.abc import Sequence

from vibesensor.domain import Finding as DomainFinding
from vibesensor.domain.finding import (
    FindingKind,
    VibrationSource,
)
from vibesensor.shared.constants import ORDER_SUPPRESS_PERSISTENT_MIN_CONF, SPEED_COVERAGE_MIN_PCT
from vibesensor.shared.types.json_types import JsonObject
from vibesensor.use_cases.diagnostics._types import (
    PhaseLabels,
    Sample,
)
from vibesensor.use_cases.diagnostics.helpers import (
    _effective_engine_rpm,
    _locations_connected_throughout_run,
    _run_noise_baseline_g,
    _tire_reference_from_metadata,
)
from vibesensor.use_cases.diagnostics.order_pipeline import _build_order_findings
from vibesensor.use_cases.diagnostics.peak_binning import (
    PERSISTENT_PEAK_MAX_FINDINGS,
    PeakBin,
    _accumulate_peak_bin_stats,
    _classify_peak_type,  # noqa: F401
    _PeakBinStats,
)
from vibesensor.use_cases.diagnostics.phase_segmentation import (
    DrivingPhase,
    diagnostic_sample_mask,
    segment_run_phases,
)
from vibesensor.use_cases.diagnostics.signal_aggregation import (
    _phase_speed_breakdown,  # noqa: F401
    _sensor_intensity_by_location,  # noqa: F401
    _speed_breakdown,  # noqa: F401
)
from vibesensor.use_cases.diagnostics.speed_profile_helpers import (
    _phase_to_str,  # noqa: F401
    _speed_profile_from_points,  # noqa: F401
)

__all__ = [
    "PeakBin",
    "PeakFindingAnalyzer",
    "build_reference_findings",
    "collect_order_frequencies",
    "engine_reference_coverage_pct",
    "finalize_findings",
    "has_engine_reference",
    "prepare_analysis_samples",
]

# ---------------------------------------------------------------------------
# Finding finalization
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Builder support helpers
# ---------------------------------------------------------------------------


_MIN_DIAGNOSTIC_SAMPLES = 5


def _reference_missing_finding(
    *,
    finding_id: str,
    suspected_source: VibrationSource,
    kind: FindingKind = FindingKind.REFERENCE,
) -> DomainFinding:
    return DomainFinding(
        finding_id=finding_id,
        suspected_source=suspected_source,
        confidence=None,
        kind=kind,
    )


def build_reference_findings(
    *,
    metadata: JsonObject,
    samples: list[Sample],
    speed_sufficient: bool,
    tire_circumference_m: float | None,
    raw_sample_rate_hz: float | None,
) -> tuple[list[DomainFinding], bool]:
    """Build reference-missing findings and return engine reference sufficiency."""
    findings: list[DomainFinding] = []
    if not speed_sufficient:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_SPEED",
                suspected_source=VibrationSource.UNKNOWN,
            ),
        )

    if speed_sufficient and not (tire_circumference_m and tire_circumference_m > 0):
        findings.append(
            _reference_missing_finding(
                finding_id="REF_WHEEL",
                suspected_source=VibrationSource.WHEEL_TIRE,
            ),
        )

    engine_ref_sufficient = has_engine_reference(
        samples,
        metadata=metadata,
        tire_circumference_m=tire_circumference_m,
    )
    if not engine_ref_sufficient:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_ENGINE",
                suspected_source=VibrationSource.ENGINE,
            ),
        )

    if raw_sample_rate_hz is None or raw_sample_rate_hz <= 0:
        findings.append(
            _reference_missing_finding(
                finding_id="REF_SAMPLE_RATE",
                suspected_source=VibrationSource.UNKNOWN,
            ),
        )
    return findings, engine_ref_sufficient


def engine_reference_coverage_pct(
    samples: list[Sample],
    *,
    metadata: JsonObject,
    tire_circumference_m: float | None,
) -> float:
    """Compute engine reference coverage percentage from samples and metadata."""
    engine_ref_count = sum(
        1
        for sample in samples
        if ((_effective_engine_rpm(sample, metadata, tire_circumference_m))[0] or 0) > 0
    )
    return (engine_ref_count / len(samples) * 100.0) if samples else 0.0


def has_engine_reference(
    samples: list[Sample],
    *,
    metadata: JsonObject,
    tire_circumference_m: float | None,
) -> bool:
    """Return whether the engine reference coverage is sufficient."""
    pct: float = engine_reference_coverage_pct(
        samples,
        metadata=metadata,
        tire_circumference_m=tire_circumference_m,
    )
    return bool(pct >= SPEED_COVERAGE_MIN_PCT)


def prepare_analysis_samples(
    samples: list[Sample],
    *,
    per_sample_phases: PhaseLabels | None,
) -> tuple[list[Sample], Sequence[DrivingPhase], list[DrivingPhase], bool]:
    """Prepare filtered samples and aligned phase labels for findings analysis."""
    if per_sample_phases is not None and len(per_sample_phases) == len(samples):
        resolved_phases: list[DrivingPhase] = [
            phase if isinstance(phase, DrivingPhase) else DrivingPhase(str(phase))
            for phase in per_sample_phases
        ]
    else:
        resolved_phases, _ = segment_run_phases(samples)

    diagnostic_mask = diagnostic_sample_mask(resolved_phases)
    diagnostic_samples = [
        sample for sample, keep in zip(samples, diagnostic_mask, strict=True) if keep
    ]
    use_filtered_samples = len(diagnostic_samples) >= _MIN_DIAGNOSTIC_SAMPLES
    analysis_samples = diagnostic_samples if use_filtered_samples else samples
    if analysis_samples is diagnostic_samples:
        analysis_phases: Sequence[DrivingPhase] = [
            phase for phase, keep in zip(resolved_phases, diagnostic_mask, strict=True) if keep
        ]
    else:
        analysis_phases = list(resolved_phases)
    return analysis_samples, analysis_phases, resolved_phases, use_filtered_samples


def collect_order_frequencies(order_findings: list[DomainFinding]) -> set[float]:
    """Collect matched order frequencies used to suppress duplicate persistent findings."""
    order_freqs: set[float] = set()
    for order_finding in order_findings:
        conf = order_finding.effective_confidence
        if conf < ORDER_SUPPRESS_PERSISTENT_MIN_CONF:
            continue
        for point in order_finding.matched_points:
            matched_hz = point.matched_hz
            if matched_hz is not None and matched_hz > 0:
                order_freqs.add(matched_hz)
    return order_freqs


def _build_persistent_peak_findings(
    *,
    samples: list[Sample],
    order_finding_freqs: set[float],
    lang: str,
    freq_bin_hz: float = 2.0,
    per_sample_phases: PhaseLabels | None = None,
    run_noise_baseline_g: float | None = None,
) -> list[DomainFinding]:
    """Build findings for non-order persistent frequency peaks.

    Uses the same confidence-style scoring as order findings (presence_ratio,
    error/SNR) so the report is consistent.  Peaks already claimed by order
    findings are excluded.  Transient peaks are returned separately.

    When ``per_sample_phases`` is provided, each finding records
    phase-aware cruise context through ``Finding.cruise_fraction``.
    """
    analyzer = PeakFindingAnalyzer(
        samples=samples,
        order_finding_freqs=order_finding_freqs,
        lang=lang,
        freq_bin_hz=freq_bin_hz,
        per_sample_phases=per_sample_phases,
        run_noise_baseline_g=run_noise_baseline_g,
    )
    return analyzer.analyze()


# ---------------------------------------------------------------------------
# PeakFindingAnalyzer – coordinates accumulation and per-bin scoring
# ---------------------------------------------------------------------------


class PeakFindingAnalyzer:
    """Coordinates frequency-bin accumulation from samples and produces findings.

    Wraps :class:`_PeakBinStats` accumulation and per-bin :class:`PeakBin`
    scoring.  The ``analyze()`` method returns the final list of findings,
    sorted and capped by :data:`PERSISTENT_PEAK_MAX_FINDINGS`.
    """

    __slots__ = (
        "_samples",
        "_order_finding_freqs",
        "_lang",
        "_freq_bin_hz",
        "_per_sample_phases",
        "_run_noise_baseline_g",
    )

    def __init__(
        self,
        *,
        samples: list[Sample],
        order_finding_freqs: set[float],
        lang: str,
        freq_bin_hz: float = 2.0,
        per_sample_phases: PhaseLabels | None = None,
        run_noise_baseline_g: float | None = None,
    ) -> None:
        self._samples = samples
        self._order_finding_freqs = order_finding_freqs
        self._lang = lang
        self._freq_bin_hz = max(freq_bin_hz, 0.01)  # Guard against values < 0.01
        self._per_sample_phases = per_sample_phases
        self._run_noise_baseline_g = run_noise_baseline_g

    def analyze(self) -> list[DomainFinding]:
        """Run the full peak-finding analysis and return ordered findings."""
        freq_bin_hz = self._freq_bin_hz
        freq_bin_hz_half = freq_bin_hz * 0.5
        has_phases = self._per_sample_phases is not None and len(self._per_sample_phases) == len(
            self._samples
        )

        stats = _accumulate_peak_bin_stats(
            self._samples,
            freq_bin_hz=freq_bin_hz,
            freq_bin_hz_half=freq_bin_hz_half,
            lang=self._lang,
            per_sample_phases=self._per_sample_phases,
            has_phases=has_phases,
        )
        if stats.n_samples == 0:
            return []

        run_noise_baseline_g = self._run_noise_baseline_g
        if run_noise_baseline_g is None:
            run_noise_baseline_g = _run_noise_baseline_g(self._samples)

        bins = self._score_bins(
            stats, run_noise_baseline_g=run_noise_baseline_g, has_phases=has_phases
        )
        return self._select_top_findings(bins, n_samples=stats.n_samples)

    def _score_bins(
        self,
        stats: _PeakBinStats,
        *,
        run_noise_baseline_g: float | None,
        has_phases: bool,
    ) -> list[PeakBin]:
        """Build a PeakBin for each frequency bin not claimed by order findings."""
        freq_bin_hz = self._freq_bin_hz
        bins: list[PeakBin] = []
        for bin_center, amps in stats.bin_amps.items():
            if any(abs(bin_center - of) < freq_bin_hz for of in self._order_finding_freqs):
                continue
            peak_bin = PeakBin(
                bin_center=bin_center,
                amps=amps,
                floor_vals=stats.bin_floors.get(bin_center, []),
                speed_amp_pairs=stats.bin_speed_amp_pairs.get(bin_center, []),
                loc_counts_for_bin=stats.bin_location_counts.get(bin_center, {}),
                speed_bin_counts_for_bin=stats.bin_speed_bin_counts.get(bin_center, {}),
                phases_for_bin=stats.bin_phase_counts.get(bin_center, {}),
                n_samples=stats.n_samples,
                total_locations=stats.total_locations,
                total_location_sample_counts=stats.total_location_sample_counts,
                total_speed_bin_counts=stats.total_speed_bin_counts,
                run_noise_baseline_g=run_noise_baseline_g,
                has_phases=has_phases,
            )
            bins.append(peak_bin)
        return bins

    @staticmethod
    def _select_top_findings(bins: list[PeakBin], *, n_samples: int) -> list[DomainFinding]:
        """Sort bins by ranking score and return top findings."""
        persistent: list[tuple[float, PeakBin]] = []
        transient: list[tuple[float, PeakBin]] = []
        for peak_bin in bins:
            bucket = transient if peak_bin.is_transient else persistent
            bucket.append((peak_bin.ranking_score, peak_bin))

        persistent.sort(key=lambda item: item[0], reverse=True)
        transient.sort(key=lambda item: item[0], reverse=True)

        del n_samples
        results: list[DomainFinding] = []
        for _score, peak_bin in persistent[:PERSISTENT_PEAK_MAX_FINDINGS]:
            results.append(peak_bin.to_finding())
        for _score, peak_bin in transient[:PERSISTENT_PEAK_MAX_FINDINGS]:
            results.append(peak_bin.to_finding())
        return results


# ---------------------------------------------------------------------------
# Main findings orchestrator
# ---------------------------------------------------------------------------


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
    findings, engine_ref_sufficient = build_reference_findings(
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
