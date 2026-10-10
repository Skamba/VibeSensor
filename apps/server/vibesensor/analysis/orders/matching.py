"""Order-tracking sample matching and accumulated match contracts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field, replace
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
from vibesensor.analysis.math_utils import _corr_abs_clamped, _ramp
from vibesensor.analysis.orders.fixed_tones import RingingTone
from vibesensor.analysis.orders.physics import OrderHypothesis
from vibesensor.analysis.orders.settings import ORDER_CONFIDENCE_SETTINGS
from vibesensor.analysis.orders.tracking import (
    TrackedCells,
    line_half_width_hz,
    window_duration_s,
)
from vibesensor.analysis.speed_profile_helpers import _phase_to_str
from vibesensor.domain.driving_segment import DrivingPhase
from vibesensor.domain.finding import speed_bin_label
from vibesensor.domain.order_match import OrderMatchObservation, SensorOrderLevel
from vibesensor.dsp.constants import FFT_N, SAMPLE_RATE_HZ
from vibesensor.dsp.order_bands import order_peak_tolerance_hz
from vibesensor.dsp.window_spectrum import line_reach_hz, peak_scale_g
from vibesensor.recording.run_schema import RunMetadata

BRAKING_PHASE = DrivingPhase.BRAKING.value
GUIDED_COAST_PHASE = "guided_coast_down"
# The cells of the rest of the drive.
DRIVING_PHASE = ""
ACCELERATION_PHASE = DrivingPhase.ACCELERATION.value
# A window's control reads sit this many of its line read's reaches either
# side of the line: clear of the line's band and flanks, close enough to read
# the same stretch of floor.
_CONTROL_REACHES = 2.0


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
    # How many sensors hear the order, graded (``_corroboration``).
    corroboration: float = 0.0
    matched_sample_indices: tuple[int, ...] = ()
    # The samples the order could be looked for in, with their sensor location.
    possible_samples: tuple[tuple[int, str], ...] = ()
    # The order's own level at each sensor whose spectra were kept, at the
    # speeds it is heard (``TrackedCells.sensor_levels``).
    sensor_levels: tuple[SensorOrderLevel, ...] = ()
    # The same over the braking windows only, for a finding put down to the brakes.
    braking_sensor_levels: tuple[SensorOrderLevel, ...] = ()
    # The heard sensors' match rate over the driving phases the order is
    # heard in, where it is not heard driving (``_phase_heard_rate``).
    phase_heard_rate: float | None = None
    # The phase labels whose match rate may rescue the order's
    # (``_compute_effective_match_rate``): those of the driving phases its
    # tracked reads hear it in.
    rescue_phases: frozenset[str] = frozenset()

    @property
    def matched(self) -> int:
        return len(self.matched_points)

    @property
    def match_rate(self) -> float:
        """Global match rate (matched / possible)."""
        return self.matched / max(1, self.possible)

    @property
    def heard_match_rate(self) -> float:
        """Match rate over the sensors that hear the order (global when none does).

        Where it is not heard driving, the rate over the driving phases it is
        heard in (``phase_heard_rate``) where that is higher: an order heard
        only while braking is absent between the stops, while a wheel order
        near the floor, clear in a braking cell alone, still matches between
        them.
        """
        if not self.heard_locations:
            return self.match_rate
        possible = self._at_heard_locations(self.possible_by_location)
        rate = self._at_heard_locations(self.matched_by_location) / max(1, possible)
        return max(rate, self.phase_heard_rate or 0.0)

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
        """The sensors that hear the order; every sensor that matched it when none does.

        A sensor matching the order far below the one that hears it best (a
        fault's leak to the other end of its axle) does not compete for its
        location.
        """
        if self.heard_locations:
            return {location.strip() for location in self.heard_locations}
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


def _clear_shares(
    possible_by_location: dict[str, int], clear_by_location: dict[str, int]
) -> dict[str, float]:
    """Each sensor's clear rate as a share of the clearest sensor's (empty when none is clear)."""
    rates = {
        location: clear_by_location.get(location, 0) / possible
        for location, possible in possible_by_location.items()
        if possible > 0
    }
    best = max(rates.values(), default=0.0)
    if best <= 0:
        return {}
    return {location: rate / best for location, rate in rates.items()}


def _sensors_that_hear(shares: dict[str, float]) -> frozenset[str]:
    """The sensors where the order is clear at least half as often as where it is clearest.

    A vibration fades with distance from its source, so the far sensors see it
    rarely or never.
    """
    min_share = ORDER_CONFIDENCE_SETTINGS.heard_location_min_share
    return frozenset(location for location, share in shares.items() if share >= min_share)


def _corroboration(shares: dict[str, float]) -> float:
    """How many sensors hear the order, graded by how clearly (0 when none does).

    The clearest sensor counts 1. Another counts in full from
    ``corroboration_ramp`` over the heard bar (``_sensors_that_hear``) and a
    little just over it, so a share a hair either side of the bar moves the
    count, and the scores built on it, only a little.
    """
    settings = ORDER_CONFIDENCE_SETTINGS
    low = settings.heard_location_min_share
    return sum(_ramp(share, low, low + settings.corroboration_ramp) for share in shares.values())


def _line_half_width_hz(frequency_hz: float, bin_hz: float) -> float:
    return max(ORDER_LINE_WIDTH_REL * frequency_hz, ORDER_LINE_WIDTH_MIN_BINS * bin_hz)


def is_harmonic_of(peak_hz: float, fundamental_hz: float, multiple: int, bin_hz: float) -> bool:
    """Whether a peak is the *multiple*-th harmonic of a fundamental's peak in the same spectrum.

    Read off one spectrum, the two differ from an exact harmonic only by where
    each sits on its line: the fundamental's error *multiple* times over plus
    the harmonic's own.
    """
    tolerance_hz = (multiple + 1) * _line_half_width_hz(fundamental_hz, bin_hz)
    return abs(peak_hz - multiple * fundamental_hz) <= tolerance_hz


@dataclass(frozen=True, slots=True)
class _LinePoint:
    """A clear match: the predicted frequency, the matched peak's, and whether under a pull."""

    predicted_hz: float
    matched_hz: float
    pulling: bool = False


def _off_the_line(points: Sequence[_LinePoint], bin_hz: float, compliance: float) -> list[bool]:
    """Which of a group of clear matches are off the order's spectral line.

    An order is a line: its peak sits on the prediction times one constant
    factor (a slightly-off tyre size or ratio) to within the speed reading's
    error. A hard pull moves it: the drive torque makes the driven wheels slip
    a few percent faster than the road (and a lagging speed reading lags the
    prediction the same way), so the matches under a pull have a line of
    their own when there are enough of them to place it. Broadband content
    filling the tolerance window, such as a road-excited resonance hump, puts a
    local-maximum peak somewhere in the window in most windows, scattered
    across it. A group with under ``ORDER_LINE_MIN_SHARE`` on its lines has no
    line: every match is off it.

    A line is placed on the matches where the tolerance window is wide enough
    to tell scatter from a line (``ORDER_LINE_MIN_TOLERANCE_WIDTHS``); with too
    few of them the group is not judged. Once placed, it holds every match: a
    window too narrow to place it in (a wheel order under about 8 Hz) still
    shows a peak off it, such as road noise that the overlapping spectra hold
    at one frequency while the prediction sweeps past. An order's peak is on
    its line in any window.
    """
    judged = [
        point
        for point in points
        if order_peak_tolerance_hz(predicted_hz=point.predicted_hz, path_compliance=compliance)
        >= ORDER_LINE_MIN_TOLERANCE_WIDTHS * _line_half_width_hz(point.predicted_hz, bin_hz)
    ]
    if len(judged) < ORDER_LINE_MIN_POINTS:
        return [False] * len(points)
    scale = {pulling: _line_scale(judged, pulling) for pulling in (False, True)}
    off = [
        abs(point.matched_hz - scale[point.pulling] * point.predicted_hz)
        > _line_half_width_hz(point.predicted_hz, bin_hz)
        for point in points
    ]
    if len(points) - sum(off) < ORDER_LINE_MIN_SHARE * len(points):
        return [True] * len(points)
    return off


def _line_scale(judged: Sequence[_LinePoint], pulling: bool) -> float:
    """The line's factor over the prediction under a pull or not (the group's if too few)."""
    own = [point for point in judged if point.pulling is pulling]
    placed_on = own if len(own) >= ORDER_LINE_MIN_POINTS else judged
    return median(point.matched_hz / point.predicted_hz for point in placed_on)


def fft_bin_hz(context: RunMetadata) -> float:
    sample_rate_hz = context.raw_sample_rate_hz or SAMPLE_RATE_HZ
    fft_n = context.fft_window_size_samples or FFT_N
    return sample_rate_hz / fft_n


def _masked(windows: Sequence[_Window], bin_hz: float, compliance: float) -> set[int]:
    """The windows whose clear match is off the order's line (see ``_off_the_line``).

    Groups are per sensor and split by braking: a
    brake order is a line only while braking, and firm braking smears every
    line. The sensors with too few clear matches to judge on their own are
    judged together: an order's line is at the same frequency at every sensor.
    """
    groups: dict[tuple[str, bool], list[tuple[int, _LinePoint]]] = defaultdict(list)
    for index, window in enumerate(windows):
        if window.match is not None and window.clear:
            braking = window.match.phase == BRAKING_PHASE
            point = _LinePoint(
                window.predicted_hz,
                window.match.matched_hz,
                pulling=window.match.phase == ACCELERATION_PHASE,
            )
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


@dataclass(frozen=True, slots=True)
class _Window:
    """One spectrum the order could be looked for in, and its match if any."""

    sample_idx: int
    location: str
    predicted_hz: float
    speed_bin: str | None
    phase_key: str | None
    match: OrderMatchObservation | None = None
    clear: bool = False
    floor: float = 0.0


def match_samples_for_hypothesis(
    samples: Sequence[Sample],
    cached_peaks: list[list[tuple[float, float]]],
    tones: Sequence[Sequence[RingingTone]],
    hypothesis: OrderHypothesis,
    context: RunMetadata,
    tire_circumference_m: float | None,
    per_sample_phases: PhaseLabels | None,
    lang: str,
    speed_rates: Sequence[float],
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
        if not peaks and sample.spectrum is None:
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
        floor_amp = _estimate_strength_floor_amp_g(sample)
        window = replace(window, floor=max(0.0, floor_amp if floor_amp is not None else 0.0))
        peak_match = best_order_peak_match(
            peaks,
            predicted_hz=predicted_hz,
            path_compliance=compliance,
        )
        if peak_match is None:
            windows.append(window)
            continue
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
                >= ORDER_CONFIDENCE_SETTINGS.heard_peak_over_floor * window.floor,
            )
        )

    bin_hz = fft_bin_hz(context)
    masked = _masked(windows, bin_hz, compliance)
    reads = _line_reads(
        samples,
        windows,
        masked,
        _LineReadContext(
            context,
            tones,
            speed_rates,
            bin_hz,
            compliance,
            # Brake judder shakes at the wheel's order, only while braking.
            braking_alone=hypothesis.order_label_base == "wheel",
        ),
    )
    cells = reads.cells
    heard_cells = cells.heard_cells()
    hearing = cells.heard_phases()
    windows = _tracked(samples, windows, masked, reads, heard_cells, hearing, bin_hz)

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

    shares = _clear_shares(possible_by_location, clear_by_location)
    heard_locations = _sensors_that_hear(shares)
    matched_windows = [window for window in windows if window.match is not None]
    heard_windows = [
        window
        for window in matched_windows
        if window.clear and window.location in heard_locations and window.speed_bin is not None
    ]
    heard_speeds = {window.speed_bin for window in heard_windows if window.speed_bin is not None}
    heard_cell_phases = {phase for _location, _speed, phase in heard_cells}
    braking_speeds = {
        window.speed_bin
        for window in heard_windows
        if window.speed_bin is not None and window.phase_key == BRAKING_PHASE
    }
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
        corroboration=_corroboration(shares),
        matched_sample_indices=tuple(window.sample_idx for window in matched_windows),
        possible_samples=tuple((window.sample_idx, window.location) for window in windows),
        # The guided coast-down in neutral is a test, with the engine idling.
        sensor_levels=cells.sensor_levels(heard_speeds, (DRIVING_PHASE, BRAKING_PHASE)),
        braking_sensor_levels=cells.sensor_levels(braking_speeds, (BRAKING_PHASE,)),
        phase_heard_rate=_phase_heard_rate(windows, heard_cells, heard_locations),
        rescue_phases=frozenset(
            key for key in possible_by_phase if _drive_phase(key) in heard_cell_phases
        ),
    )


def _drive_phase(phase_key: str | None) -> str:
    """The driving phase a phase label is tracked in: braking, or the rest of the drive."""
    return BRAKING_PHASE if phase_key == BRAKING_PHASE else DRIVING_PHASE


def _phase_heard_rate(
    windows: Sequence[_Window],
    heard_cells: Collection[tuple[str, str, str]],
    heard_locations: frozenset[str],
) -> float | None:
    """The match rate over the driving phases the order is heard in, where it is not heard driving.

    An order heard only while braking (brake judder) is absent from the
    windows between stops; its heard sensors' match rate is taken over their
    braking windows alone. ``None`` where the order is heard driving, or by
    no sensor.
    """
    if not heard_locations:
        return None
    heard_in = {phase for location, _speed, phase in heard_cells if location in heard_locations}
    if not heard_in or DRIVING_PHASE in heard_in:
        return None
    in_phase = [
        window
        for window in windows
        if window.location in heard_locations and _drive_phase(window.phase_key) in heard_in
    ]
    if not in_phase:
        return None
    return sum(window.match is not None for window in in_phase) / len(in_phase)


@dataclass(frozen=True, slots=True)
class _LineReadContext:
    context: RunMetadata
    tones: Sequence[Sequence[RingingTone]]
    speed_rates: Sequence[float]
    bin_hz: float
    compliance: float
    # Whether the order can be there only while braking (``TrackedCells``).
    braking_alone: bool


type _CellKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class _Line:
    """Where one window was read: its cell, the order's line and how far it swept."""

    cell: _CellKey
    hz: float
    half_width_hz: float


@dataclass(slots=True)
class _LineReads:
    """Every window's read at the order's line, and the windows whose line could not be read."""

    cells: TrackedCells
    # Where each window was read, by window index.
    lines: dict[int, _Line] = field(default_factory=dict)
    # Windows whose line lies on, or within the leak of, a ringing tone.
    on_tone: set[int] = field(default_factory=set)
    # Windows whose line's band or flanks run off the spectrum's edge.
    off_edge: set[int] = field(default_factory=set)


def _line_reads(
    samples: Sequence[Sample],
    windows: Sequence[_Window],
    masked: set[int],
    read: _LineReadContext,
) -> _LineReads:
    """Every window read at the order's line, grouped by sensor, speed bin and driving phase.

    Every window whose spectrum the post-stop analysis rebuilt from the raw
    capture is read at the order's line, whatever louder content the window
    holds elsewhere: at the frequency the clear matches place the line
    (``_tracked_line_scale``, from the windows whose line held still), over
    the band the line swept while the speed changed
    (``line_half_width_hz``). A window whose read reaches one of its sensor's
    ringing tones or that tone's leak (*tones*, see ``ringing_tones``) is not
    read: the tone's level is no part of the order's. Each read comes with two
    control reads ``_CONTROL_REACHES`` of its reach either side of the line,
    where the order is not, which place the floor's scatter
    (``TrackedCells``). See "Order-tracked reads" in docs/order_tracking.md.
    """
    window_s = window_duration_s(read.context)
    reads = _LineReads(TrackedCells(window_s=window_s, braking_alone=read.braking_alone))
    if not any(samples[window.sample_idx].spectrum is not None for window in windows):
        return reads
    # A window's peak lands anywhere on the stretch its line swept, so only the
    # windows whose line held still within a peak's width place the line.
    swept = {
        index
        for index, window in enumerate(windows)
        if line_half_width_hz(
            window.predicted_hz,
            samples[window.sample_idx].speed_kmh,
            read.speed_rates[window.sample_idx],
            window_s,
        )
        > _line_half_width_hz(window.predicted_hz, read.bin_hz)
    }
    scale = _tracked_line_scale(windows, masked | swept, read.bin_hz, read.compliance)
    coasts = [
        (step.start_t_s, step.end_t_s if step.end_t_s is not None else float("inf"))
        for step in read.context.guided_phases
        if step.phase == "coast_down"
    ]
    for index, window in enumerate(windows):
        sample = samples[window.sample_idx]
        spectrum = sample.spectrum
        if spectrum is None:
            continue
        line_hz = scale * window.predicted_hz
        half_width_hz = line_half_width_hz(
            line_hz, sample.speed_kmh, read.speed_rates[window.sample_idx], window_s
        )
        reach_hz = line_reach_hz(half_width_hz, read.bin_hz)
        tones = read.tones[window.sample_idx]
        if any(tone.takes_in(line_hz, reach_hz) for tone in tones):
            reads.on_tone.add(index)
            continue
        line = spectrum.line_read(line_hz, half_width_hz)
        if line is None:
            reads.off_edge.add(index)
            continue
        cell = (window.location, window.speed_bin or "", _cell_phase(window, sample, coasts))
        reads.cells.add(cell, line, sample.t_s)
        reads.lines[index] = _Line(cell, line_hz, half_width_hz)
        offset = _CONTROL_REACHES * reach_hz
        for control_hz in (line_hz - offset, line_hz + offset):
            if control_hz < MIN_ANALYSIS_FREQ_HZ or any(
                tone.takes_in(control_hz, reach_hz) for tone in tones
            ):
                continue
            control = spectrum.line_read(control_hz, half_width_hz)
            if control is not None:
                reads.cells.add_control(cell, control)
    return reads


def _cell_phase(window: _Window, sample: Sample, coasts: Sequence[tuple[float, float]]) -> str:
    """The driving phase a window's read is grouped by.

    The guided test's coast-down in neutral is its own: the engine drops to
    idle there while the road speed carries on, which is how the test tells an
    engine order from a road-speed one at the same line.
    """
    t_s = sample.t_s
    if t_s is not None and any(start <= t_s < end for start, end in coasts):
        return GUIDED_COAST_PHASE
    return _drive_phase(window.phase_key)


def _tracked(
    samples: Sequence[Sample],
    windows: Sequence[_Window],
    masked: set[int],
    reads: _LineReads,
    heard: dict[tuple[str, str, str], SensorOrderLevel],
    hearing: Collection[tuple[str, str]],
    bin_hz: float,
) -> list[_Window]:
    """Each window's verdict on the order: from its tracked read where it has one.

    A window read at the order's line matches, and hears, the order where its
    cell hears it (``TrackedCells.heard_cells``), at that cell's level on a
    ranked peak's scale over the window's floor (``peak_scale_g``), whether
    or not the order ranked among the window's peaks. Where its cell
    does not, its ranked peak near the line still matches where the order is
    heard in that driving phase at some sensor (*hearing*, ``TrackedCells.heard_phases``),
    and the window does not match where it is not. Its frequency is its ranked
    peak's where one sits within the line's tolerance and sweep, else the
    line's. A window whose line could not be read keeps its peak match: on a
    ringing tone (the tone hides the order from the read, not from the ranked
    peaks), at the spectrum's edge only at a sensor that hears the order in
    some phase (a floor-level peak at the spectrum's lowest bins is no
    evidence elsewhere), and in a summary-only run. A window off the order's
    line (``_masked``) keeps no peak match. A window in the guided
    coast-down is judged by its ranked peak alone, as the coast test judges
    it (``diagnosis._speed_dependence``): a cell there spans the shift into
    neutral, where an engine order still sounds for a window or two.
    """
    hearing_locations = {location for location, _phase in hearing}
    hearing_phases = {phase for _location, phase in hearing}
    tracked: list[_Window] = []
    for index, window in enumerate(windows):
        line = reads.lines.get(index)
        cell = (
            heard.get(line.cell)
            if line is not None and line.cell[2] != GUIDED_COAST_PHASE
            else None
        )
        if line is None or cell is None:
            unheard = (
                line.cell[2] not in hearing_phases
                if line is not None
                else index in reads.off_edge and window.location not in hearing_locations
            )
            if unheard:
                tracked.append(replace(window, match=None, clear=False))
            elif index not in masked:
                tracked.append(window)
            continue
        peak = window.match
        matched_hz = (
            peak.matched_hz
            if peak is not None
            and abs(peak.matched_hz - line.hz)
            <= _line_half_width_hz(line.hz, bin_hz) + line.half_width_hz
            else line.hz
        )
        sample = samples[window.sample_idx]
        tracked.append(
            replace(
                window,
                match=OrderMatchObservation(
                    t_s=sample.t_s,
                    speed_kmh=sample.speed_kmh,
                    predicted_hz=window.predicted_hz,
                    matched_hz=matched_hz,
                    rel_error=abs(matched_hz - window.predicted_hz) / window.predicted_hz,
                    amp=peak_scale_g(cell.level_g, window.floor),
                    location=window.location,
                    phase=window.phase_key,
                ),
                clear=bool(window.location),
            )
        )
    return tracked


def _tracked_line_scale(
    windows: Sequence[_Window], masked: set[int], bin_hz: float, compliance: float
) -> float:
    """The order line's factor over its prediction where the clear matches place one, else 1."""
    points = [
        _LinePoint(window.predicted_hz, window.match.matched_hz)
        for index, window in enumerate(windows)
        if window.match is not None and window.clear and index not in masked
    ]
    judged = [
        point
        for point in points
        if order_peak_tolerance_hz(predicted_hz=point.predicted_hz, path_compliance=compliance)
        >= ORDER_LINE_MIN_TOLERANCE_WIDTHS * _line_half_width_hz(point.predicted_hz, bin_hz)
    ]
    if len(judged) < ORDER_LINE_MIN_POINTS:
        return 1.0
    return _line_scale(judged, pulling=False)


def _nonzero(counts: dict[str, int]) -> dict[str, int]:
    return {key: count for key, count in counts.items() if count}
