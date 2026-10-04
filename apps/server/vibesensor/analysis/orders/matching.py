"""Order-tracking sample matching and accumulated match contracts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from vibesensor.analysis._sample_metrics import (
    _estimate_strength_floor_amp_g,
)
from vibesensor.analysis._sensor_locations import (
    _location_label,
)
from vibesensor.analysis._types import (
    PhaseLabels,
    Sample,
)
from vibesensor.analysis.constants import (
    ORDER_MIN_COVERAGE_DURATION_S,
    ORDER_MIN_COVERAGE_POINTS,
    ORDER_MIN_MATCH_DURATION_S,
    ORDER_MIN_MATCH_POINTS,
    ORDER_VARIABLE_MIN_CORRELATION,
    ORDER_VARIABLE_MIN_MATCHED_SPEED_BINS,
    SPEED_BIN_WIDTH_KMH,
)
from vibesensor.analysis.math_utils import _corr_abs_clamped
from vibesensor.analysis.orders.physics import OrderHypothesis
from vibesensor.analysis.speed_profile_helpers import _phase_to_str
from vibesensor.domain.finding import speed_bin_label
from vibesensor.domain.order_match import OrderMatchObservation
from vibesensor.dsp.order_bands import order_peak_tolerance_hz
from vibesensor.recording.run_schema import RunMetadata


@dataclass(frozen=True)
class OrderMatchAccumulator:
    """Accumulated statistics from matching one hypothesis across samples."""

    possible: int
    matched: int
    matched_amp: list[float]
    matched_floor: list[float]
    rel_errors: list[float]
    predicted_vals: list[float]
    measured_vals: list[float]
    matched_points: list[OrderMatchObservation]
    ref_sources: set[str]
    possible_by_speed_bin: dict[str, int]
    matched_by_speed_bin: dict[str, int]
    possible_by_phase: dict[str, int]
    matched_by_phase: dict[str, int]
    possible_by_location: dict[str, int]
    matched_by_location: dict[str, int]
    has_phases: bool
    compliance: float
    matched_sample_indices: tuple[int, ...] = ()

    @property
    def match_rate(self) -> float:
        """Global match rate (matched / possible)."""
        return self.matched / max(1, self.possible)

    @property
    def unique_match_locations(self) -> set[str]:
        """Set of distinct sensor locations that produced matches."""
        return {(point.location or "").strip() for point in self.matched_points if point.location}

    def is_eligible(
        self,
        *,
        feature_interval_s: float | None = None,
        steady_speed: bool = False,
        min_coverage: int = ORDER_MIN_COVERAGE_POINTS,
        min_matched: int = ORDER_MIN_MATCH_POINTS,
    ) -> bool:
        """Whether this match has enough data to produce a finding."""
        if self.possible < min_coverage or self.matched < min_matched:
            return False
        if feature_interval_s is None or feature_interval_s <= 0:
            return True

        possible_duration_s = self.possible * feature_interval_s
        matched_duration_s = self.matched * feature_interval_s
        if (
            possible_duration_s < ORDER_MIN_COVERAGE_DURATION_S
            or matched_duration_s < ORDER_MIN_MATCH_DURATION_S
        ):
            return False
        if steady_speed:
            return True

        matched_speed_bins = sum(1 for count in self.matched_by_speed_bin.values() if count > 0)
        if matched_speed_bins >= ORDER_VARIABLE_MIN_MATCHED_SPEED_BINS:
            return True
        corr = _corr_abs_clamped(self.predicted_vals, self.measured_vals)
        return corr is not None and corr >= ORDER_VARIABLE_MIN_CORRELATION

    @property
    def matched_peaks(self) -> frozenset[tuple[int, float]]:
        """The spectral peaks this hypothesis matched, as ``(sample index, peak Hz)``."""
        return frozenset(zip(self.matched_sample_indices, self.measured_vals, strict=True))


@dataclass(frozen=True)
class OrderPeakMatch:
    """Best matching spectral peak for one predicted order frequency."""

    peak_index: int
    matched_hz: float
    amplitude_g: float
    relative_error: float


def best_order_peak_match(
    peaks: Sequence[tuple[float, float]],
    *,
    predicted_hz: float,
    path_compliance: float,
) -> OrderPeakMatch | None:
    """Return the closest peak within the hypothesis tolerance window."""

    if predicted_hz <= 0 or not peaks:
        return None
    tolerance_hz = order_peak_tolerance_hz(
        predicted_hz=predicted_hz,
        path_compliance=path_compliance,
    )
    peak_index, (best_hz, best_amp) = min(
        enumerate(peaks),
        key=lambda item: abs(item[1][0] - predicted_hz),
    )
    delta_hz = abs(best_hz - predicted_hz)
    if delta_hz > tolerance_hz:
        return None
    return OrderPeakMatch(
        peak_index=peak_index,
        matched_hz=best_hz,
        amplitude_g=best_amp,
        relative_error=delta_hz / max(1e-9, predicted_hz),
    )


def match_samples_for_hypothesis(
    samples: Sequence[Sample],
    cached_peaks: list[list[tuple[float, float]]],
    hypothesis: OrderHypothesis,
    context: RunMetadata,
    tire_circumference_m: float | None,
    per_sample_phases: PhaseLabels | None,
    lang: str,
) -> OrderMatchAccumulator:
    """Match one hypothesis against all samples and accumulate evidence."""
    possible = 0
    matched = 0
    matched_amp: list[float] = []
    matched_floor: list[float] = []
    rel_errors: list[float] = []
    predicted_vals: list[float] = []
    measured_vals: list[float] = []
    matched_points: list[OrderMatchObservation] = []
    matched_sample_indices: list[int] = []
    ref_sources: set[str] = set()
    possible_by_speed_bin: dict[str, int] = defaultdict(int)
    matched_by_speed_bin: dict[str, int] = defaultdict(int)
    possible_by_phase: dict[str, int] = defaultdict(int)
    matched_by_phase: dict[str, int] = defaultdict(int)
    possible_by_location: dict[str, int] = defaultdict(int)
    matched_by_location: dict[str, int] = defaultdict(int)
    has_phases = per_sample_phases is not None and len(per_sample_phases) == len(samples)
    compliance = getattr(hypothesis, "path_compliance", 1.0)

    for sample_idx, sample in enumerate(samples):
        peaks = cached_peaks[sample_idx]
        if not peaks:
            continue
        predicted_hz, ref_source = hypothesis.predicted_hz(sample, context, tire_circumference_m)
        if predicted_hz is None or predicted_hz <= 0:
            continue
        possible += 1
        ref_sources.add(ref_source)

        sample_location = _location_label(sample, lang=lang)
        if sample_location:
            possible_by_location[sample_location] += 1
        sample_speed = sample.speed_kmh
        sample_speed_bin = (
            speed_bin_label(sample_speed, bin_width=SPEED_BIN_WIDTH_KMH)
            if sample_speed is not None and sample_speed > 0
            else None
        )
        if sample_speed_bin is not None:
            possible_by_speed_bin[sample_speed_bin] += 1

        phase_key: str | None = None
        if has_phases:
            assert per_sample_phases is not None
            phase = per_sample_phases[sample_idx]
            phase_key = str(phase.value if hasattr(phase, "value") else phase)
            possible_by_phase[phase_key] += 1

        peak_match = best_order_peak_match(
            peaks,
            predicted_hz=predicted_hz,
            path_compliance=compliance,
        )
        if peak_match is None:
            continue

        matched += 1
        matched_sample_indices.append(sample_idx)
        if sample_location:
            matched_by_location[sample_location] += 1
        if sample_speed_bin is not None:
            matched_by_speed_bin[sample_speed_bin] += 1
        if has_phases and phase_key is not None:
            matched_by_phase[phase_key] += 1

        rel_errors.append(peak_match.relative_error)
        matched_amp.append(peak_match.amplitude_g)
        floor_amp = _estimate_strength_floor_amp_g(sample)
        matched_floor.append(max(0.0, floor_amp if floor_amp is not None else 0.0))
        predicted_vals.append(predicted_hz)
        measured_vals.append(peak_match.matched_hz)
        matched_points.append(
            OrderMatchObservation(
                t_s=sample.t_s,
                speed_kmh=sample.speed_kmh,
                predicted_hz=predicted_hz,
                matched_hz=peak_match.matched_hz,
                rel_error=peak_match.relative_error,
                amp=peak_match.amplitude_g,
                location=sample_location,
                phase=(
                    _phase_to_str(per_sample_phases[sample_idx])
                    if has_phases and per_sample_phases is not None
                    else None
                ),
            ),
        )

    return OrderMatchAccumulator(
        possible=possible,
        matched=matched,
        matched_amp=matched_amp,
        matched_floor=matched_floor,
        rel_errors=rel_errors,
        predicted_vals=predicted_vals,
        measured_vals=measured_vals,
        matched_points=matched_points,
        ref_sources=ref_sources,
        possible_by_speed_bin=dict(possible_by_speed_bin),
        matched_by_speed_bin=dict(matched_by_speed_bin),
        possible_by_phase=dict(possible_by_phase),
        matched_by_phase=dict(matched_by_phase),
        possible_by_location=dict(possible_by_location),
        matched_by_location=dict(matched_by_location),
        has_phases=has_phases,
        compliance=compliance,
        matched_sample_indices=tuple(matched_sample_indices),
    )
