"""Persistent-peak finding helpers for diagnostics orchestration."""

from __future__ import annotations

from collections.abc import Sequence

from vibesensor.domain import Finding as DomainFinding
from vibesensor.shared.constants import ORDER_SUPPRESS_PERSISTENT_MIN_CONF

from ._types import PhaseLabels, Sample
from .helpers import _run_noise_baseline_g
from .peak_accumulation import PeakBinStats, accumulate_peak_bin_stats
from .peak_finding_builder import assemble_peak_finding
from .peak_scoring import PeakBin
from .phase_segmentation import DrivingPhase, diagnostic_sample_mask, segment_run_phases

PERSISTENT_PEAK_MAX_FINDINGS = 3

__all__ = [
    "PeakFindingAnalyzer",
    "_build_persistent_peak_findings",
    "collect_order_frequencies",
    "prepare_analysis_samples",
]

_MIN_DIAGNOSTIC_SAMPLES = 5


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
    """Collect order-match frequencies used to suppress duplicate peak findings."""
    order_freqs: set[float] = set()
    for order_finding in order_findings:
        if order_finding.effective_confidence < ORDER_SUPPRESS_PERSISTENT_MIN_CONF:
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
    """Build findings for non-order persistent frequency peaks."""
    analyzer = PeakFindingAnalyzer(
        samples=samples,
        order_finding_freqs=order_finding_freqs,
        lang=lang,
        freq_bin_hz=freq_bin_hz,
        per_sample_phases=per_sample_phases,
        run_noise_baseline_g=run_noise_baseline_g,
    )
    return analyzer.analyze()


class PeakFindingAnalyzer:
    """Coordinate frequency-bin accumulation from samples and score findings."""

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
        self._freq_bin_hz = max(freq_bin_hz, 0.01)
        self._per_sample_phases = per_sample_phases
        self._run_noise_baseline_g = run_noise_baseline_g

    def analyze(self) -> list[DomainFinding]:
        """Run the full peak-finding analysis and return ordered findings."""
        freq_bin_hz = self._freq_bin_hz
        has_phases = self._per_sample_phases is not None and len(self._per_sample_phases) == len(
            self._samples
        )
        stats = accumulate_peak_bin_stats(
            self._samples,
            freq_bin_hz=freq_bin_hz,
            freq_bin_hz_half=freq_bin_hz * 0.5,
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
            stats,
            run_noise_baseline_g=run_noise_baseline_g,
        )
        return self._select_top_findings(bins, n_samples=stats.n_samples)

    def _score_bins(
        self,
        stats: PeakBinStats,
        *,
        run_noise_baseline_g: float | None,
    ) -> list[PeakBin]:
        bins: list[PeakBin] = []
        for bin_center, amps in stats.bin_amps.items():
            if any(abs(bin_center - of) < self._freq_bin_hz for of in self._order_finding_freqs):
                continue
            bins.append(
                PeakBin(
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
                ),
            )
        return bins

    @staticmethod
    def _select_top_findings(bins: list[PeakBin], *, n_samples: int) -> list[DomainFinding]:
        del n_samples
        persistent: list[tuple[float, PeakBin]] = []
        transient: list[tuple[float, PeakBin]] = []
        for peak_bin in bins:
            bucket = transient if peak_bin.is_transient else persistent
            bucket.append((peak_bin.ranking_score, peak_bin))

        persistent.sort(key=lambda item: item[0], reverse=True)
        transient.sort(key=lambda item: item[0], reverse=True)

        results: list[DomainFinding] = []
        for _, peak_bin in persistent[:PERSISTENT_PEAK_MAX_FINDINGS]:
            results.append(assemble_peak_finding(peak_bin))
        for _, peak_bin in transient[:PERSISTENT_PEAK_MAX_FINDINGS]:
            results.append(assemble_peak_finding(peak_bin))
        return results
