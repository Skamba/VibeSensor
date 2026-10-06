"""Order-tracking sample matching and accumulated match contracts."""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from statistics import median

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
    MIN_ANALYSIS_FREQ_HZ,
    ORDER_LINE_MIN_POINTS,
    ORDER_LINE_MIN_SHARE,
    ORDER_LINE_MIN_TOLERANCE_WIDTHS,
    ORDER_LINE_WIDTH_MIN_BINS,
    ORDER_LINE_WIDTH_REL,
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
from vibesensor.domain.driving_segment import DrivingPhase
from vibesensor.domain.finding import speed_bin_label
from vibesensor.domain.order_match import OrderMatchObservation
from vibesensor.dsp.constants import FFT_N, SAMPLE_RATE_HZ
from vibesensor.dsp.order_bands import order_peak_tolerance_hz
from vibesensor.recording.run_schema import RunMetadata

BRAKING_PHASE = DrivingPhase.BRAKING.value


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
    # The samples the order could be looked for in, with their sensor location.
    possible_samples: tuple[tuple[int, str], ...] = ()

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
        """Whether this match has enough data to produce a finding.

        Its matches count as its evidence does (``evidence``): an order heard
        somewhere is matched where it is heard, not where road noise sat near
        its frequency.
        """
        evidence = len(self.evidence)
        if self.possible < min_coverage or evidence < min_matched:
            return False
        if feature_interval_s is None or feature_interval_s <= 0:
            return True

        possible_duration_s = self.possible * feature_interval_s
        matched_duration_s = evidence * feature_interval_s
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


def _line_half_width_hz(frequency_hz: float, bin_hz: float) -> float:
    return max(ORDER_LINE_WIDTH_REL * frequency_hz, ORDER_LINE_WIDTH_MIN_BINS * bin_hz)


@dataclass(frozen=True, slots=True)
class _LinePoint:
    """A clear match; *timed* unless its sensor lost frames over its spectrum's span."""

    predicted_hz: float
    matched_hz: float
    timed: bool


def _off_the_line(points: Sequence[_LinePoint], bin_hz: float, compliance: float) -> list[bool]:
    """Which of a group of clear matches are off the order's spectral line.

    An order is a line: its peak sits on the prediction times one constant
    factor (a slightly-off tyre size or ratio) to within the speed reading's
    error. Broadband content filling the tolerance window, such as a
    road-excited resonance hump, puts a local-maximum peak somewhere in the
    window in most windows, scattered across it. A group with under
    ``ORDER_LINE_MIN_SHARE`` on one line has no line: every match is off it.

    The line is judged on the timed matches where the tolerance window is wide
    enough to tell scatter from a line (``ORDER_LINE_MIN_TOLERANCE_WIDTHS``);
    with too few of them the group is not judged. A spectrum over a lost frame
    reaches further back than its stated span, so while the speed changes its
    peak lags the prediction: such a match is not judged on its own either.
    """
    judged = [
        point.timed
        and order_peak_tolerance_hz(predicted_hz=point.predicted_hz, path_compliance=compliance)
        >= ORDER_LINE_MIN_TOLERANCE_WIDTHS * _line_half_width_hz(point.predicted_hz, bin_hz)
        for point in points
    ]
    judged_points = [point for point, is_judged in zip(points, judged, strict=True) if is_judged]
    if len(judged_points) < ORDER_LINE_MIN_POINTS:
        return [False] * len(points)
    scale = median(point.matched_hz / point.predicted_hz for point in judged_points)
    off = [
        is_judged
        and abs(point.matched_hz - scale * point.predicted_hz)
        > _line_half_width_hz(point.predicted_hz, bin_hz)
        for point, is_judged in zip(points, judged, strict=True)
    ]
    if len(judged_points) - sum(off) < ORDER_LINE_MIN_SHARE * len(judged_points):
        return [True] * len(points)
    return off


def _fft_bin_hz(context: RunMetadata) -> float:
    sample_rate_hz = context.raw_sample_rate_hz or SAMPLE_RATE_HZ
    fft_n = context.fft_window_size_samples or FFT_N
    return sample_rate_hz / fft_n


def _timed(windows: Sequence[_Window]) -> list[bool]:
    """Whether each window's sensor lost no frames over the time its spectrum spans."""
    series: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for window in windows:
        if window.t_s is not None:
            series[window.location].append((window.t_s, window.frames_dropped))
    for located in series.values():
        located.sort()
    times = {location: [t_s for t_s, _ in located] for location, located in series.items()}
    timed: list[bool] = []
    for window in windows:
        if window.span_s is None or window.location not in times:
            timed.append(True)
            continue
        before = max(bisect_right(times[window.location], window.span_s[0]) - 1, 0)
        timed.append(series[window.location][before][1] >= window.frames_dropped)
    return timed


def _masked(windows: Sequence[_Window], bin_hz: float, compliance: float) -> set[int]:
    """The windows whose clear match is off the order's line (see ``_off_the_line``).

    Groups are per sensor and split by braking: a
    brake order is a line only while braking, and firm braking smears every
    line. The sensors with too few clear matches to judge on their own are
    judged together: an order's line is at the same frequency at every sensor.
    """
    timed = _timed(windows)
    groups: dict[tuple[str, bool], list[tuple[int, _LinePoint]]] = defaultdict(list)
    for index, window in enumerate(windows):
        if window.match is not None and window.clear:
            braking = window.match.phase == BRAKING_PHASE
            point = _LinePoint(window.predicted_hz, window.match.matched_hz, timed[index])
            groups[(window.location, braking)].append((index, point))
    judged: list[list[tuple[int, _LinePoint]]] = []
    pooled: dict[bool, list[tuple[int, _LinePoint]]] = defaultdict(list)
    for (_location, braking), group in groups.items():
        if len(group) >= ORDER_LINE_MIN_POINTS:
            judged.append(group)
        else:
            pooled[braking].extend(group)
    judged.extend(pooled.values())
    return {
        index
        for group in judged
        for (index, _), off in zip(
            group, _off_the_line([match for _, match in group], bin_hz, compliance), strict=True
        )
        if off
    }


def _spectrum_span_s(sample: Sample) -> tuple[float, float] | None:
    """The run time (s) the signal behind *sample*'s spectrum spans: its analysis
    window, else the FFT length up to the sample's time."""
    start_us = sample.analysis_window_start_us
    end_us = sample.analysis_window_end_us
    if start_us is not None and end_us is not None and end_us > start_us:
        return start_us / 1e6, end_us / 1e6
    if sample.t_s is None:
        return None
    return sample.t_s - FFT_N / SAMPLE_RATE_HZ, sample.t_s


@dataclass(frozen=True, slots=True)
class _Window:
    """One spectrum the order could be looked for in, and its match if any."""

    sample_idx: int
    location: str
    t_s: float | None
    span_s: tuple[float, float] | None
    frames_dropped: int
    predicted_hz: float
    speed_bin: str | None
    phase_key: str | None
    match: OrderMatchObservation | None = None
    clear: bool = False
    floor: float = 0.0


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
    the predicted frequency at every sensor; such a match is not heard. A
    window whose clear match is off the order's line (``_off_the_line``) holds
    broadband content louder than the order could be seen through: it is not a
    chance to hear the order, like a window whose order lies under the analysis
    floor.
    """
    windows: list[_Window] = []
    ref_sources: set[str] = set()
    has_phases = per_sample_phases is not None and len(per_sample_phases) == len(samples)
    compliance = getattr(hypothesis, "path_compliance", 1.0)

    for sample_idx, sample in enumerate(samples):
        peaks = cached_peaks[sample_idx]
        if not peaks:
            continue
        predicted_hz, ref_source = hypothesis.predicted_hz(sample, context, tire_circumference_m)
        # Peaks under the analysis floor are dropped (``_sample_top_peaks``), so a
        # window whose order lies there could never show it: it is not a chance
        # to hear the order (a wheel order at town speeds, the end of a stop).
        if predicted_hz is None or predicted_hz < MIN_ANALYSIS_FREQ_HZ:
            continue
        ref_sources.add(ref_source)

        sample_location = _location_label(sample, lang=lang)
        sample_speed = sample.speed_kmh
        window = _Window(
            sample_idx=sample_idx,
            location=sample_location,
            t_s=sample.t_s,
            span_s=_spectrum_span_s(sample),
            frames_dropped=sample.frames_dropped_total,
            predicted_hz=predicted_hz,
            speed_bin=(
                speed_bin_label(sample_speed, bin_width=SPEED_BIN_WIDTH_KMH)
                if sample_speed is not None and sample_speed > 0
                else None
            ),
            phase_key=_phase_to_str(per_sample_phases[sample_idx])
            if has_phases and per_sample_phases is not None
            else None,
        )
        peak_match = best_order_peak_match(
            peaks,
            predicted_hz=predicted_hz,
            path_compliance=compliance,
        )
        if peak_match is None:
            windows.append(window)
            continue

        floor_amp = _estimate_strength_floor_amp_g(sample)
        floor = max(0.0, floor_amp if floor_amp is not None else 0.0)
        windows.append(
            replace(
                window,
                match=OrderMatchObservation(
                    t_s=sample.t_s,
                    speed_kmh=sample.speed_kmh,
                    predicted_hz=predicted_hz,
                    matched_hz=peak_match.matched_hz,
                    rel_error=peak_match.relative_error,
                    amp=peak_match.amplitude_g,
                    location=sample_location,
                    phase=window.phase_key,
                ),
                clear=bool(sample_location)
                and peak_match.amplitude_g
                >= ORDER_CONFIDENCE_SETTINGS.heard_peak_over_floor * floor,
                floor=floor,
            )
        )

    masked = _masked(windows, _fft_bin_hz(context), compliance)
    windows = [window for index, window in enumerate(windows) if index not in masked]

    possible_by_speed_bin: dict[str, int] = defaultdict(int)
    possible_by_phase: dict[str, int] = defaultdict(int)
    possible_by_location: dict[str, int] = defaultdict(int)
    matched_by_speed_bin: dict[str, int] = defaultdict(int)
    matched_by_phase: dict[str, int] = defaultdict(int)
    matched_by_location: dict[str, int] = defaultdict(int)
    clear_by_location: dict[str, int] = defaultdict(int)
    for window in windows:
        matched = window.match is not None
        if window.location:
            possible_by_location[window.location] += 1
            matched_by_location[window.location] += matched
            clear_by_location[window.location] += window.clear
        if window.speed_bin is not None:
            possible_by_speed_bin[window.speed_bin] += 1
            matched_by_speed_bin[window.speed_bin] += matched
        if window.phase_key is not None:
            possible_by_phase[window.phase_key] += 1
            matched_by_phase[window.phase_key] += matched

    heard_locations = _sensors_that_hear(possible_by_location, clear_by_location)
    matched_windows = [window for window in windows if window.match is not None]
    return OrderMatchAccumulator(
        possible=len(windows),
        matched_points=[
            replace(window.match, heard=True)
            if window.clear and window.location in heard_locations
            else window.match
            for window in matched_windows
            if window.match is not None
        ],
        matched_floor=[window.floor for window in matched_windows],
        ref_sources=ref_sources,
        possible_by_speed_bin=_nonzero(possible_by_speed_bin),
        matched_by_speed_bin=_nonzero(matched_by_speed_bin),
        possible_by_phase=_nonzero(possible_by_phase),
        matched_by_phase=_nonzero(matched_by_phase),
        possible_by_location=_nonzero(possible_by_location),
        matched_by_location=_nonzero(matched_by_location),
        has_phases=has_phases,
        compliance=compliance,
        heard_locations=heard_locations,
        matched_sample_indices=tuple(window.sample_idx for window in matched_windows),
        possible_samples=tuple((window.sample_idx, window.location) for window in windows),
    )


def _nonzero(counts: dict[str, int]) -> dict[str, int]:
    return {key: count for key, count in counts.items() if count}
