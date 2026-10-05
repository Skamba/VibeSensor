"""Order-tracking sample matching and accumulated match contracts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace

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
from vibesensor.analysis.orders.settings import ORDER_CONFIDENCE_SETTINGS
from vibesensor.analysis.speed_profile_helpers import _phase_to_str
from vibesensor.domain.finding import speed_bin_label
from vibesensor.domain.order_match import OrderMatchObservation
from vibesensor.dsp.order_bands import order_peak_tolerance_hz
from vibesensor.recording.run_schema import RunMetadata


@dataclass(frozen=True)
class OrderMatchAccumulator:
    """Accumulated statistics from matching one hypothesis across samples.

    Every match is classified once, while matching, as heard or not
    (``OrderMatchObservation.heard``), and the sensors that hear the order
    (``heard_locations``) are derived once from those verdicts. Every metric
    that weighs the order's evidence reads them; none re-filters the raw
    matches. See "Heard matches" in ``docs/order_tracking.md``.
    """

    possible: int
    matched_points: list[OrderMatchObservation]
    # The floor of each match's window, parallel to ``matched_points``.
    matched_floor: list[float]
    ref_sources: set[str]
    possible_by_speed_bin: dict[str, int]
    matched_by_speed_bin: dict[str, int]
    possible_by_phase: dict[str, int]
    matched_by_phase: dict[str, int]
    possible_by_location: dict[str, int]
    matched_by_location: dict[str, int]
    has_phases: bool
    compliance: float
    heard_locations: frozenset[str] = frozenset()
    matched_sample_indices: tuple[int, ...] = ()

    @property
    def matched(self) -> int:
        return len(self.matched_points)

    @property
    def match_rate(self) -> float:
        """Global match rate (matched / possible)."""
        return self.matched / max(1, self.possible)

    @property
    def heard_match_rate(self) -> float:
        """Match rate over the sensors that hear the order (global when none does)."""
        if not self.heard_locations:
            return self.match_rate
        possible = self._at_heard_locations(self.possible_by_location)
        return self._at_heard_locations(self.matched_by_location) / max(1, possible)

    @property
    def heard_share(self) -> float:
        """Share of the matches at the sensors that hear the order that are heard."""
        matched = self._at_heard_locations(self.matched_by_location)
        heard = sum(1 for point in self.matched_points if point.heard)
        return heard / matched if matched else 0.0

    def _at_heard_locations(self, counts: dict[str, int]) -> int:
        return sum(counts.get(location, 0) for location in self.heard_locations)

    @property
    def evidence(self) -> list[tuple[OrderMatchObservation, float]]:
        """The heard matches with their window floors; all matches when none is heard.

        The order's level, frequency error and tracking, and sample count come
        from these: floor-level matches say nothing about how strong an order is
        or how closely it follows its prediction. An order heard nowhere has
        nothing better than its floor-level matches.
        """
        pairs = list(zip(self.matched_points, self.matched_floor, strict=True))
        return [(point, floor) for point, floor in pairs if point.heard] or pairs

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
        corr = _corr_abs_clamped(
            [point.predicted_hz for point in self.matched_points],
            [point.matched_hz for point in self.matched_points],
        )
        return corr is not None and corr >= ORDER_VARIABLE_MIN_CORRELATION

    @property
    def matched_peaks(self) -> frozenset[tuple[int, float]]:
        """The spectral peaks this hypothesis matched, as ``(sample index, peak Hz)``."""
        return frozenset(
            zip(
                self.matched_sample_indices,
                (point.matched_hz for point in self.matched_points),
                strict=True,
            )
        )


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


def _sensors_that_hear(
    possible_by_location: dict[str, int], clear_by_location: dict[str, int]
) -> frozenset[str]:
    """The sensors where the order is clear at least half as often as where it is clearest.

    A vibration fades with distance from its source, so the far sensors see it
    rarely or never.
    """
    rates = {
        location: clear_by_location.get(location, 0) / possible
        for location, possible in possible_by_location.items()
        if possible > 0
    }
    best = max(rates.values(), default=0.0)
    if best <= 0:
        return frozenset()
    min_rate = ORDER_CONFIDENCE_SETTINGS.heard_location_min_share * best
    return frozenset(location for location, rate in rates.items() if rate >= min_rate)


def match_samples_for_hypothesis(
    samples: Sequence[Sample],
    cached_peaks: list[list[tuple[float, float]]],
    hypothesis: OrderHypothesis,
    context: RunMetadata,
    tire_circumference_m: float | None,
    per_sample_phases: PhaseLabels | None,
    lang: str,
) -> OrderMatchAccumulator:
    """Match one hypothesis against all samples, then classify each match as heard or not.

    A match is heard when its peak stands at least ``heard_peak_over_floor``
    (6 dB) over its own window's floor at a sensor that hears the order (see
    ``_sensors_that_hear``). The matcher takes the nearest peak in the tolerance
    band whatever its level, so it also lands on floor-level road noise near
    the predicted frequency at every sensor; such a match is not heard.
    """
    possible = 0
    matches: list[tuple[OrderMatchObservation, bool]] = []
    matched_floor: list[float] = []
    matched_sample_indices: list[int] = []
    ref_sources: set[str] = set()
    possible_by_speed_bin: dict[str, int] = defaultdict(int)
    matched_by_speed_bin: dict[str, int] = defaultdict(int)
    possible_by_phase: dict[str, int] = defaultdict(int)
    matched_by_phase: dict[str, int] = defaultdict(int)
    possible_by_location: dict[str, int] = defaultdict(int)
    matched_by_location: dict[str, int] = defaultdict(int)
    clear_by_location: dict[str, int] = defaultdict(int)
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

        matched_sample_indices.append(sample_idx)
        if sample_location:
            matched_by_location[sample_location] += 1
        if sample_speed_bin is not None:
            matched_by_speed_bin[sample_speed_bin] += 1
        if has_phases and phase_key is not None:
            matched_by_phase[phase_key] += 1

        floor_amp = _estimate_strength_floor_amp_g(sample)
        matched_floor.append(max(0.0, floor_amp if floor_amp is not None else 0.0))
        clear = bool(sample_location) and (
            peak_match.amplitude_g
            >= ORDER_CONFIDENCE_SETTINGS.heard_peak_over_floor * matched_floor[-1]
        )
        if clear:
            clear_by_location[sample_location] += 1
        matches.append(
            (
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
                clear,
            )
        )

    heard_locations = _sensors_that_hear(possible_by_location, clear_by_location)
    return OrderMatchAccumulator(
        possible=possible,
        matched_points=[
            replace(point, heard=True) if clear and point.location in heard_locations else point
            for point, clear in matches
        ],
        matched_floor=matched_floor,
        ref_sources=ref_sources,
        possible_by_speed_bin=dict(possible_by_speed_bin),
        matched_by_speed_bin=dict(matched_by_speed_bin),
        possible_by_phase=dict(possible_by_phase),
        matched_by_phase=dict(matched_by_phase),
        possible_by_location=dict(possible_by_location),
        matched_by_location=dict(matched_by_location),
        has_phases=has_phases,
        compliance=compliance,
        heard_locations=heard_locations,
        matched_sample_indices=tuple(matched_sample_indices),
    )
