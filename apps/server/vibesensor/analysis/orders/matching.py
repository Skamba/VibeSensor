"""Order-tracking sample matching and accumulated match contracts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from statistics import median
from typing import NamedTuple, cast

import numpy as np
import numpy.typing as npt

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
from vibesensor.analysis.orders.physics import OrderHypothesis
from vibesensor.analysis.orders.settings import ORDER_CONFIDENCE_SETTINGS
from vibesensor.analysis.orders.tracking import (
    TrackedCells,
    speed_rates_kmh_per_s,
    window_duration_s,
)
from vibesensor.analysis.speed_profile_helpers import _phase_to_str
from vibesensor.domain.driving_segment import DrivingPhase
from vibesensor.domain.finding import speed_bin_label
from vibesensor.domain.order_match import OrderMatchObservation, SensorOrderLevel
from vibesensor.dsp.constants import FFT_N, SAMPLE_RATE_HZ
from vibesensor.dsp.fixed_tones import RingingTone
from vibesensor.dsp.line_significance import CONTROL_REACHES
from vibesensor.dsp.order_bands import order_peak_tolerance_hz, order_peak_tolerances_hz
from vibesensor.dsp.window_spectrum import (
    SpectraByRows,
    line_reach_hz,
    line_reads,
    peak_scale_g,
    spectra_by_rows,
)
from vibesensor.recording.run_schema import RunMetadata

BRAKING_PHASE = DrivingPhase.BRAKING.value
GUIDED_COAST_PHASE = "guided_coast_down"
# The cells of the rest of the drive.
DRIVING_PHASE = ""
ACCELERATION_PHASE = DrivingPhase.ACCELERATION.value


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


@dataclass(frozen=True, slots=True)
class PeakTable:
    """A drive's ranked peaks by sample, as rows padded with infinite frequencies.

    Built once per drive, so each hypothesis finds every sample's nearest
    peak in one array operation rather than one sample at a time.
    """

    hz: npt.NDArray[np.float64]
    amp: npt.NDArray[np.float64]
    # Whether each sample has a peak.
    any: npt.NDArray[np.bool_]


def peak_table(peaks: Sequence[Sequence[tuple[float, float]]]) -> PeakTable:
    """The rows of *peaks*, one per sample, padded to the longest with infinite frequencies."""
    width = max(1, max((len(sample_peaks) for sample_peaks in peaks), default=0))
    hz = np.full((len(peaks), width), np.inf)
    amp = np.zeros((len(peaks), width))
    for row, sample_peaks in enumerate(peaks):
        if sample_peaks:
            hz[row, : len(sample_peaks)], amp[row, : len(sample_peaks)] = zip(
                *sample_peaks, strict=True
            )
    return PeakTable(hz, amp, np.array([bool(sample_peaks) for sample_peaks in peaks]))


@dataclass(frozen=True, slots=True)
class ReferenceColumns:
    """Each sample's ``reference_hz`` for the orders of one rotation, as columns.

    Its frequency (NaN where there is none), whether it has one, and its
    source (an index into *source_names*).
    """

    hz: npt.NDArray[np.float64]
    known: npt.NDArray[np.bool_]
    source: npt.NDArray[np.intp]
    source_names: Sequence[str]


def reference_columns(references: Sequence[tuple[float | None, str]]) -> ReferenceColumns:
    """*references* (``reference_hz`` by sample) as ``ReferenceColumns``."""
    names: dict[str, int] = {}
    return ReferenceColumns(
        hz=np.array(
            [hz if hz is not None else float("nan") for hz, _source in references],
            dtype=np.float64,
        ),
        known=np.array([hz is not None for hz, _source in references], dtype=np.bool_),
        source=np.array(
            [names.setdefault(source, len(names)) for _hz, source in references], dtype=np.intp
        ),
        source_names=list(names),
    )


def _nearest_peaks(
    table: PeakTable,
    rows: npt.NDArray[np.intp],
    predicted_hz: npt.NDArray[np.float64],
    compliance: float,
) -> tuple[
    npt.NDArray[np.bool_], npt.NDArray[np.float64], npt.NDArray[np.float64], npt.NDArray[np.float64]
]:
    """Each sample's peak closest to its predicted frequency, within the order's tolerance.

    Whether the sample has one, its frequency, amplitude and error relative
    to the prediction, for the samples *rows* at *predicted_hz*: the first
    closest where two are as close. A sample without peaks has none.
    """
    distances = np.abs(table.hz[rows] - predicted_hz[:, None])
    nearest = distances.argmin(axis=1)
    picked = np.arange(rows.size), nearest
    delta_hz = distances[picked]
    within = ~(delta_hz > order_peak_tolerances_hz(predicted_hz, path_compliance=compliance))
    return (
        within,
        table.hz[rows, nearest],
        table.amp[rows, nearest],
        delta_hz / np.maximum(1e-9, predicted_hz),
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


def _masked(windows: _Windows, drive: DriveFacts, bin_hz: float, compliance: float) -> set[int]:
    """The windows whose clear match is off the order's line (see ``_off_the_line``).

    Groups are per sensor and split by braking: a
    brake order is a line only while braking, and firm braking smears every
    line. The sensors with too few clear matches to judge on their own are
    judged together: an order's line is at the same frequency at every sensor.
    """
    groups: dict[tuple[int, bool], list[tuple[int, _LinePoint]]] = defaultdict(list)
    clear = np.flatnonzero(windows.clear)
    for index, location, phase, predicted_hz, matched_hz in zip(
        clear.tolist(),
        windows.location[clear].tolist(),
        windows.phase[clear].tolist(),
        windows.predicted_hz[clear].tolist(),
        windows.matched_hz[clear].tolist(),
        strict=True,
    ):
        phase_key = drive.phases[phase]
        point = _LinePoint(predicted_hz, matched_hz, pulling=phase_key == ACCELERATION_PHASE)
        groups[(location, phase_key == BRAKING_PHASE)].append((index, point))
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
class SampleFacts:
    """What every hypothesis reads of one sample the same way, worked out once per drive."""

    location: str
    speed_bin: str | None
    phase_key: str | None
    floor: float
    # The cell its line read is filed in: its sensor, speed bin and the
    # driving phase it is grouped by (``_cell_phase``).
    cell: tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class DriveFacts:
    """Each of a drive's samples' ``SampleFacts``, as columns, and the columns its line reads take.

    Worked out once per drive: every hypothesis reads them the same way.
    """

    # Each sample's location, speed bin and phase label, as an index into the
    # drive's own (``locations``, ``speed_bins``, ``phases``), and its floor.
    location_of: npt.NDArray[np.intp]
    locations: Sequence[str]
    speed_bin_of: npt.NDArray[np.intp]
    speed_bins: Sequence[str | None]
    phase_of: npt.NDArray[np.intp]
    phases: Sequence[str | None]
    floor: npt.NDArray[np.float64]
    # The drive's cells (``SampleFacts.cell``), and each sample's among them.
    cells: Sequence[tuple[str, str, str]]
    cell_of: npt.NDArray[np.intp]
    # Each sample's speed (0 where unknown) and its rate of change (km/h per s).
    speed_kmh: npt.NDArray[np.float64]
    speed_rate: npt.NDArray[np.float64]
    # Whether the sample has a spectrum the replay rebuilt, and the spectra.
    spectral: npt.NDArray[np.bool_]
    spectra: SpectraByRows
    # Each sample's time (NaN where unknown), and whether it is known.
    t_s: npt.NDArray[np.float64]
    timed: npt.NDArray[np.bool_]


def drive_facts(
    samples: Sequence[Sample],
    context: RunMetadata,
    per_sample_phases: PhaseLabels | None,
    lang: str,
) -> DriveFacts:
    """The drive's ``DriveFacts``."""
    facts = _sample_facts(samples, context, per_sample_phases, lang)
    location_of, locations = _coded([sample.location for sample in facts])
    speed_bin_of, speed_bins = _coded([sample.speed_bin for sample in facts])
    phase_of, phases = _coded([sample.phase_key for sample in facts])
    cell_of, cells = _coded([sample.cell for sample in facts])
    return DriveFacts(
        location_of=location_of,
        locations=locations,
        speed_bin_of=speed_bin_of,
        speed_bins=speed_bins,
        phase_of=phase_of,
        phases=phases,
        floor=np.array([sample.floor for sample in facts], dtype=np.float64),
        cell_of=cell_of,
        cells=cells,
        speed_kmh=np.array([sample.speed_kmh or 0.0 for sample in samples], dtype=np.float64),
        speed_rate=np.array(speed_rates_kmh_per_s(samples), dtype=np.float64),
        spectral=np.array([sample.spectrum is not None for sample in samples], dtype=np.bool_),
        spectra=spectra_by_rows([sample.spectrum for sample in samples]),
        t_s=np.array(
            [sample.t_s if sample.t_s is not None else float("nan") for sample in samples],
            dtype=np.float64,
        ),
        timed=np.array([sample.t_s is not None for sample in samples], dtype=np.bool_),
    )


def _coded[T](values: Sequence[T]) -> tuple[npt.NDArray[np.intp], list[T]]:
    """Each of *values* as an index into the distinct values, which come in first-seen order."""
    names: dict[T, int] = {}
    codes = np.array([names.setdefault(value, len(names)) for value in values], dtype=np.intp)
    return codes, list(names)


def _sample_facts(
    samples: Sequence[Sample],
    context: RunMetadata,
    per_sample_phases: PhaseLabels | None,
    lang: str,
) -> list[SampleFacts]:
    """Each sample's ``SampleFacts``."""
    has_phases = per_sample_phases is not None and len(per_sample_phases) == len(samples)
    coasts = [
        (step.start_t_s, step.end_t_s if step.end_t_s is not None else float("inf"))
        for step in context.guided_phases
        if step.phase == "coast_down"
    ]
    facts = []
    for sample_idx, sample in enumerate(samples):
        sample_speed = sample.speed_kmh
        phase_key = (
            _phase_to_str(per_sample_phases[sample_idx])
            if has_phases and per_sample_phases is not None
            else None
        )
        floor_amp = _estimate_strength_floor_amp_g(sample)
        location = _location_label(sample, lang=lang)
        speed_bin = (
            speed_bin_label(sample_speed, bin_width=SPEED_BIN_WIDTH_KMH)
            if sample_speed is not None and sample_speed > 0
            else None
        )
        facts.append(
            SampleFacts(
                location=location,
                speed_bin=speed_bin,
                phase_key=phase_key,
                floor=max(0.0, floor_amp if floor_amp is not None else 0.0),
                cell=(location, speed_bin or "", _cell_phase(phase_key, sample, coasts)),
            )
        )
    return facts


@dataclass(frozen=True, slots=True)
class _Windows:
    """The spectra one hypothesis could be heard in, as columns, with each one's ranked-peak match.

    Columns, not an object per window: each hypothesis looks at every window.
    *location* and *phase* index ``DriveFacts.locations`` and ``DriveFacts.phases``.
    """

    sample: npt.NDArray[np.intp]
    predicted_hz: npt.NDArray[np.float64]
    location: npt.NDArray[np.intp]
    speed_bin: npt.NDArray[np.intp]
    phase: npt.NDArray[np.intp]
    floor: npt.NDArray[np.float64]
    # Whether a ranked peak matches the order, the nearest peak's frequency,
    # amplitude and relative error, and whether the match is clear of the floor.
    matched: npt.NDArray[np.bool_]
    matched_hz: npt.NDArray[np.float64]
    amp: npt.NDArray[np.float64]
    rel_error: npt.NDArray[np.float64]
    clear: npt.NDArray[np.bool_]


def match_samples_for_hypothesis(
    samples: Sequence[Sample],
    peaks: PeakTable,
    tones: Sequence[Sequence[RingingTone]],
    hypothesis: OrderHypothesis,
    context: RunMetadata,
    references: ReferenceColumns,
    drive: DriveFacts,
    has_phases: bool,
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
    compliance = getattr(hypothesis, "path_compliance", 1.0)
    windows, verdicts, cells, heard_cells = _match(
        samples, peaks, tones, hypothesis, context, references, drive, compliance
    )
    sources, first = np.unique(references.source[windows.sample], return_index=True)
    ref_sources = {
        references.source_names[source]
        for source in sources[np.argsort(first, kind="stable")].tolist()
    }
    kept = verdicts.kept
    kept_location = windows.location[kept]
    matched = verdicts.matched
    possible_by_location, matched_by_location = _tally(
        kept_location, [name or None for name in drive.locations], matched
    )
    clear_by_location = _tally(
        kept_location, [name or None for name in drive.locations], verdicts.clear
    )[1]
    possible_by_speed_bin, matched_by_speed_bin = _tally(
        windows.speed_bin[kept], drive.speed_bins, matched
    )
    possible_by_phase, matched_by_phase = _tally(windows.phase[kept], drive.phases, matched)

    shares = _clear_shares(possible_by_location, clear_by_location)
    heard_locations = _sensors_that_hear(shares)
    heard = (
        verdicts.clear
        & np.array([name in heard_locations for name in drive.locations], dtype=np.bool_)[
            kept_location
        ]
    )
    kept_speed_bin = windows.speed_bin[kept]
    has_speed_bin = np.array([name is not None for name in drive.speed_bins], dtype=np.bool_)
    heard_speed_bins = kept_speed_bin[heard & has_speed_bin[kept_speed_bin]]
    braking = np.array([name == BRAKING_PHASE for name in drive.phases], dtype=np.bool_)[
        windows.phase[kept]
    ]
    heard_speeds = {drive.speed_bins[code] for code in set(heard_speed_bins.tolist())}
    braking_speeds = {
        drive.speed_bins[code]
        for code in set(kept_speed_bin[heard & has_speed_bin[kept_speed_bin] & braking].tolist())
    }
    heard_cell_phases = {phase for _location, _speed, phase in heard_cells}
    matched_at = np.flatnonzero(matched)
    matched_samples = windows.sample[kept][matched_at].tolist()
    return OrderMatchAccumulator(
        possible=int(kept.size),
        matched_points=[
            OrderMatchObservation(
                t_s=samples[sample_idx].t_s,
                speed_kmh=samples[sample_idx].speed_kmh,
                predicted_hz=window_hz,
                matched_hz=peak_hz,
                rel_error=error,
                amp=amp,
                location=drive.locations[at],
                phase=drive.phases[phase_code],
                heard=is_heard,
            )
            for sample_idx, window_hz, peak_hz, error, amp, at, phase_code, is_heard in zip(
                matched_samples,
                windows.predicted_hz[kept][matched_at].tolist(),
                verdicts.matched_hz[matched_at].tolist(),
                verdicts.rel_error[matched_at].tolist(),
                verdicts.amp[matched_at].tolist(),
                kept_location[matched_at].tolist(),
                windows.phase[kept][matched_at].tolist(),
                heard[matched_at].tolist(),
                strict=True,
            )
        ],
        matched_floor=windows.floor[kept][matched_at].tolist(),
        ref_sources=ref_sources,
        possible_by_speed_bin=possible_by_speed_bin,
        matched_by_speed_bin=_nonzero(matched_by_speed_bin),
        possible_by_phase=possible_by_phase,
        matched_by_phase=_nonzero(matched_by_phase),
        possible_by_location=possible_by_location,
        matched_by_location=_nonzero(matched_by_location),
        has_phases=has_phases,
        compliance=compliance,
        heard_locations=heard_locations,
        corroboration=_corroboration(shares),
        matched_sample_indices=tuple(matched_samples),
        possible_samples=tuple(
            zip(
                windows.sample[kept].tolist(),
                [drive.locations[code] for code in kept_location.tolist()],
                strict=True,
            )
        ),
        # The guided coast-down in neutral is a test, with the engine idling.
        sensor_levels=cells.sensor_levels(heard_speeds, (DRIVING_PHASE, BRAKING_PHASE)),
        braking_sensor_levels=cells.sensor_levels(braking_speeds, (BRAKING_PHASE,)),
        phase_heard_rate=_phase_heard_rate(
            matched, braking, heard_cells, heard_locations, kept_location, drive
        ),
        rescue_phases=frozenset(
            key for key in possible_by_phase if _drive_phase(key) in heard_cell_phases
        ),
    )


def matched_peaks_for_hypothesis(
    samples: Sequence[Sample],
    peaks: PeakTable,
    tones: Sequence[Sequence[RingingTone]],
    hypothesis: OrderHypothesis,
    context: RunMetadata,
    references: ReferenceColumns,
    drive: DriveFacts,
) -> frozenset[tuple[int, float]]:
    """``match_samples_for_hypothesis(...).matched_peaks``, without the rest of the accumulator."""
    windows, verdicts, _cells, _heard_cells = _match(
        samples,
        peaks,
        tones,
        hypothesis,
        context,
        references,
        drive,
        getattr(hypothesis, "path_compliance", 1.0),
    )
    matched = verdicts.matched
    return frozenset(
        zip(
            windows.sample[verdicts.kept][matched].tolist(),
            verdicts.matched_hz[matched].tolist(),
            strict=True,
        )
    )


def _match(
    samples: Sequence[Sample],
    peaks: PeakTable,
    tones: Sequence[Sequence[RingingTone]],
    hypothesis: OrderHypothesis,
    context: RunMetadata,
    references: ReferenceColumns,
    drive: DriveFacts,
    compliance: float,
) -> tuple[_Windows, _Verdicts, TrackedCells, dict[_CellKey, SensorOrderLevel]]:
    """One hypothesis's windows, their verdicts (``_tracked``), its line reads and heard cells."""
    # Each window: a sample with peaks or a spectrum, whose order is placed.
    # Peaks under the analysis floor are dropped (``_sample_top_peaks``), so a
    # window whose order lies there could never show it: it is not a chance
    # to hear the order (a wheel order at town speeds, the end of a stop).
    predicted_hz = references.hz * hypothesis.order
    eligible = np.flatnonzero(
        (peaks.any | drive.spectral) & references.known & ~(predicted_hz < MIN_ANALYSIS_FREQ_HZ)
    )
    predicted = predicted_hz[eligible]
    within, matched_hz, amplitude_g, relative_error = _nearest_peaks(
        peaks, eligible, predicted, compliance
    )
    location = drive.location_of[eligible]
    floor = drive.floor[eligible]
    located = np.array([bool(name) for name in drive.locations], dtype=np.bool_)
    heard_over_floor = ORDER_CONFIDENCE_SETTINGS.heard_peak_over_floor
    windows = _Windows(
        sample=eligible,
        predicted_hz=predicted,
        location=location,
        speed_bin=drive.speed_bin_of[eligible],
        phase=drive.phase_of[eligible],
        floor=floor,
        matched=within,
        matched_hz=matched_hz,
        amp=amplitude_g,
        rel_error=relative_error,
        clear=within & located[location] & (amplitude_g >= heard_over_floor * floor),
    )

    bin_hz = fft_bin_hz(context)
    masked = _masked(windows, drive, bin_hz, compliance)
    reads = _line_reads(
        samples,
        windows,
        masked,
        _LineReadContext(
            context,
            drive,
            tones,
            bin_hz,
            compliance,
            # Brake judder shakes at the wheel's order, only while braking.
            braking_alone=hypothesis.order_label_base == "wheel",
        ),
    )
    cells = reads.cells
    heard_cells = cells.heard_cells()
    verdicts = _tracked(windows, drive, masked, reads, heard_cells, cells.heard_phases(), bin_hz)
    return windows, verdicts, cells, heard_cells


def _tally(
    codes: npt.NDArray[np.intp], names: Sequence[str | None], matched: npt.NDArray[np.bool_]
) -> tuple[dict[str, int], dict[str, int]]:
    """The windows and the *matched* windows by name, each name in the order it first comes.

    *codes* index *names*; a window whose name is ``None`` is not counted.
    A name with no matched window counts 0 among the matched.
    """
    seen, first = np.unique(codes, return_index=True)
    windows = np.bincount(codes, minlength=len(names)).tolist()
    hits = np.bincount(codes[matched], minlength=len(names)).tolist()
    possible: dict[str, int] = {}
    in_match: dict[str, int] = {}
    for code in seen[np.argsort(first, kind="stable")].tolist():
        name = names[code]
        if name is not None:
            possible[name] = windows[code]
            in_match[name] = hits[code]
    return possible, in_match


def _drive_phase(phase_key: str | None) -> str:
    """The driving phase a phase label is tracked in: braking, or the rest of the drive."""
    return BRAKING_PHASE if phase_key == BRAKING_PHASE else DRIVING_PHASE


def _phase_heard_rate(
    matched: npt.NDArray[np.bool_],
    braking: npt.NDArray[np.bool_],
    heard_cells: Collection[tuple[str, str, str]],
    heard_locations: frozenset[str],
    location: npt.NDArray[np.intp],
    drive: DriveFacts,
) -> float | None:
    """The match rate over the driving phases the order is heard in, where it is not heard driving.

    An order heard only while braking (brake judder) is absent from the
    windows between stops; its heard sensors' match rate is taken over their
    braking windows alone. ``None`` where the order is heard driving, or by
    no sensor. *matched*, *braking* and *location* are the windows'.
    """
    if not heard_locations:
        return None
    heard_in = {phase for location, _speed, phase in heard_cells if location in heard_locations}
    if not heard_in or DRIVING_PHASE in heard_in:
        return None
    # The only other phase a window is tracked in (``_drive_phase``).
    if BRAKING_PHASE not in heard_in:
        return None
    heard_at = np.array([name in heard_locations for name in drive.locations], dtype=np.bool_)
    in_phase = heard_at[location] & braking
    windows = int(np.count_nonzero(in_phase))
    if not windows:
        return None
    return int(np.count_nonzero(matched[in_phase])) / windows


@dataclass(frozen=True, slots=True)
class _LineReadContext:
    context: RunMetadata
    drive: DriveFacts
    tones: Sequence[Sequence[RingingTone]]
    bin_hz: float
    compliance: float
    # Whether the order can be there only while braking (``TrackedCells``).
    braking_alone: bool


type _CellKey = tuple[str, str, str]


@dataclass(slots=True)
class _LineReads:
    """Every window's read at the order's line, and the windows whose line could not be read."""

    cells: TrackedCells
    # Each window's line read (an index into the arrays below; -1 where it has none).
    read_at: npt.NDArray[np.intp]
    # Windows whose line's band or flanks run off the spectrum's edge.
    off_edge: npt.NDArray[np.bool_]
    # Each line read's cell (an index into ``cell_keys``), line and how far it swept.
    line_cell: npt.NDArray[np.intp] = field(default_factory=lambda: np.empty(0, dtype=np.intp))
    cell_keys: list[_CellKey] = field(default_factory=list)
    line_hz: npt.NDArray[np.float64] = field(default_factory=lambda: np.empty(0))
    line_half_width_hz: npt.NDArray[np.float64] = field(default_factory=lambda: np.empty(0))


def _line_reads(
    samples: Sequence[Sample],
    windows: _Windows,
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
    control reads ``CONTROL_REACHES`` of its reach either side of the line,
    where the order is not, which place the floor's scatter
    (``TrackedCells``). See "Order-tracked reads" in docs/order_tracking.md.

    The windows' lines are placed as arrays and every read is taken at once
    (``line_reads``), then filed in window order: the same values as one
    window at a time, at a fraction of the cost.
    """
    window_s = window_duration_s(read.context)
    drive = read.drive
    window_samples = windows.sample
    predicted_hz = windows.predicted_hz
    reads = _LineReads(
        TrackedCells(window_s=window_s, braking_alone=read.braking_alone),
        np.full(window_samples.size, -1, dtype=np.intp),
        np.zeros(window_samples.size, dtype=np.bool_),
    )
    spectral = np.flatnonzero(drive.spectral[window_samples])
    if not spectral.size:
        return reads
    speed_kmh = drive.speed_kmh[window_samples]
    rate = drive.speed_rate[window_samples]
    # A window's peak lands anywhere on the stretch its line swept, so only the
    # windows whose line held still within a peak's width place the line.
    held_width_hz = np.maximum(
        ORDER_LINE_WIDTH_REL * predicted_hz, ORDER_LINE_WIDTH_MIN_BINS * read.bin_hz
    )
    swept_by = _swept_half_widths(predicted_hz, speed_kmh, rate, window_s)
    swept = set(np.flatnonzero(swept_by > held_width_hz).tolist())
    scale = _tracked_line_scale(windows, masked | swept, read.bin_hz, read.compliance)
    line_hz = scale * predicted_hz[spectral]
    half_width_hz = _swept_half_widths(line_hz, speed_kmh[spectral], rate[spectral], window_s)
    reach_hz = line_reach_hz(half_width_hz, read.bin_hz)
    offset_hz = CONTROL_REACHES * reach_hz
    # Every read is planned as arrays and taken at once (``line_reads``), then
    # filed by cell in window order.
    lower_hz = line_hz - offset_hz
    upper_hz = line_hz + offset_hz
    sample_of = window_samples[spectral]
    planned = np.ones(spectral.size, dtype=np.bool_)
    with_controls = np.stack(
        (planned, ~(lower_hz < MIN_ANALYSIS_FREQ_HZ), ~(upper_hz < MIN_ANALYSIS_FREQ_HZ)), axis=1
    )
    for position, sample_idx in enumerate(sample_of.tolist()):
        tones = read.tones[sample_idx]
        if not tones:
            continue
        reach = float(reach_hz[position])
        if any(tone.takes_in(float(line_hz[position]), reach) for tone in tones):
            planned[position] = False
            continue
        for column, control_hz in ((1, lower_hz[position]), (2, upper_hz[position])):
            if any(tone.takes_in(float(control_hz), reach) for tone in tones):
                with_controls[position, column] = False
    entries = np.flatnonzero(planned)
    if not entries.size:
        return reads
    included = with_controls[entries]
    owner = np.broadcast_to(np.arange(entries.size)[:, None], included.shape)[included]
    column = np.broadcast_to(np.arange(3), included.shape)[included]
    entry_samples = sample_of[entries]
    excess, flanks, taken = line_reads(
        drive.spectra,
        entry_samples[owner],
        np.stack((line_hz, lower_hz, upper_hz), axis=1)[entries][included],
        half_width_hz[entries][owner],
    )
    # A window whose line could not be read is off the edge, with its controls.
    main = column == 0
    entry_taken = taken[main]
    window_of = spectral[entries]
    reads.off_edge[window_of[~entry_taken]] = True
    kept = np.flatnonzero(entry_taken)
    kept_samples = entry_samples[kept]
    # The cells in the order their first read comes, as one read at a time files them.
    drive_cell = drive.cell_of[kept_samples]
    cells_read, first_read = np.unique(drive_cell, return_index=True)
    cells_in_order = cells_read[np.argsort(first_read, kind="stable")]
    cell_number = np.empty(len(drive.cells), dtype=np.intp)
    cell_number[cells_in_order] = np.arange(cells_in_order.size)
    kept_cell = cell_number[drive_cell]
    entry_cell = np.full(entries.size, -1, dtype=np.intp)
    entry_cell[kept] = kept_cell
    control = ~main & taken & entry_taken[owner]
    by_cell = _cell_slices(kept_cell, cells_in_order.size)
    controls_by_cell = _cell_slices(entry_cell[owner[control]], cells_in_order.size)
    main_excess, main_flanks = excess[main][kept], flanks[main][kept]
    control_excess, control_flanks = excess[control], flanks[control]
    kept_t_s, kept_timed = drive.t_s[kept_samples], drive.timed[kept_samples]
    reads.cell_keys = [drive.cells[cell] for cell in cells_in_order.tolist()]
    for key, reads_at, controls_at in zip(reads.cell_keys, by_cell, controls_by_cell, strict=True):
        cell_t_s = kept_t_s[reads_at]
        reads.cells.add_reads(
            key,
            main_excess[reads_at].tolist(),
            main_flanks[reads_at].tolist(),
            cell_t_s.tolist(),
            cell_t_s[kept_timed[reads_at]].tolist(),
            control_excess[controls_at].tolist(),
            control_flanks[controls_at].tolist(),
        )
    positions = entries[kept]
    reads.read_at[window_of[kept]] = np.arange(kept.size)
    reads.line_cell = kept_cell
    reads.line_hz = line_hz[positions]
    reads.line_half_width_hz = half_width_hz[positions]
    return reads


def _cell_slices(cell_of: npt.NDArray[np.intp], cells: int) -> list[npt.NDArray[np.intp]]:
    """The positions in *cell_of* of each cell's entries, cell by cell, each in their order."""
    order = np.argsort(cell_of, kind="stable")
    bounds = np.searchsorted(cell_of[order], np.arange(cells + 1))
    return [order[start:stop] for start, stop in zip(bounds[:-1], bounds[1:], strict=True)]


def _swept_half_widths(
    hz: npt.NDArray[np.float64],
    speed_kmh: npt.NDArray[np.float64],
    rate_kmh_per_s: npt.NDArray[np.float64],
    window_s: float,
) -> npt.NDArray[np.float64]:
    """``line_half_width_hz`` of each line (0 where the speed is unknown or 0)."""
    half_width_hz = np.zeros_like(hz)
    moving = ~(speed_kmh <= 0)
    half_width_hz[moving] = (
        hz[moving] * np.abs(rate_kmh_per_s[moving]) * window_s / (2.0 * speed_kmh[moving])
    )
    return half_width_hz


def _cell_phase(
    phase_key: str | None, sample: Sample, coasts: Sequence[tuple[float, float]]
) -> str:
    """The driving phase a window's read is grouped by.

    The guided test's coast-down in neutral is its own: the engine drops to
    idle there while the road speed carries on, which is how the test tells an
    engine order from a road-speed one at the same line.
    """
    t_s = sample.t_s
    if t_s is not None and any(start <= t_s < end for start, end in coasts):
        return GUIDED_COAST_PHASE
    return _drive_phase(phase_key)


class _Verdicts(NamedTuple):
    """Each window's verdict on the order (``_tracked``), over the windows *kept* (in order)."""

    kept: npt.NDArray[np.intp]
    matched: npt.NDArray[np.bool_]
    clear: npt.NDArray[np.bool_]
    matched_hz: npt.NDArray[np.float64]
    rel_error: npt.NDArray[np.float64]
    amp: npt.NDArray[np.float64]


def _tracked(
    windows: _Windows,
    drive: DriveFacts,
    masked: set[int],
    reads: _LineReads,
    heard: dict[tuple[str, str, str], SensorOrderLevel],
    hearing: Collection[tuple[str, str]],
    bin_hz: float,
) -> _Verdicts:
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
    count = windows.sample.size
    # Each cell's verdict, with one more for the windows without a read (-1).
    levels = [heard.get(key) if key[2] != GUIDED_COAST_PHASE else None for key in reads.cell_keys]
    cell_tracked = np.array([level is not None for level in levels] + [False], dtype=np.bool_)
    cell_unheard = np.array(
        [key[2] not in hearing_phases for key in reads.cell_keys] + [False], dtype=np.bool_
    )
    read = reads.read_at >= 0
    cell = np.full(count, -1, dtype=np.intp)
    cell[read] = reads.line_cell[reads.read_at[read]]
    tracked = cell_tracked[cell]
    off_hearing = ~np.array(
        [name in hearing_locations for name in drive.locations], dtype=np.bool_
    )[windows.location]
    unheard = ~tracked & np.where(read, cell_unheard[cell], reads.off_edge & off_hearing)
    off_line = np.zeros(count, dtype=np.bool_)
    off_line[list(masked)] = True
    as_is = ~tracked & ~unheard & ~off_line
    matched_hz = windows.matched_hz.copy()
    rel_error = windows.rel_error.copy()
    amp = windows.amp.copy()
    at = np.flatnonzero(tracked)
    if at.size:
        lines = reads.read_at[at]
        line_hz = reads.line_hz[lines]
        predicted_hz = windows.predicted_hz[at]
        peak_hz = windows.matched_hz[at]
        on_line = windows.matched[at] & (
            np.abs(peak_hz - line_hz)
            <= np.maximum(ORDER_LINE_WIDTH_REL * line_hz, ORDER_LINE_WIDTH_MIN_BINS * bin_hz)
            + reads.line_half_width_hz[lines]
        )
        tracked_hz = np.where(on_line, peak_hz, line_hz)
        matched_hz[at] = tracked_hz
        rel_error[at] = np.abs(tracked_hz - predicted_hz) / predicted_hz
        amp[at] = [
            peak_scale_g(cast("SensorOrderLevel", levels[cell_index]).level_g, floor)
            for cell_index, floor in zip(cell[at].tolist(), windows.floor[at].tolist(), strict=True)
        ]
    kept = np.flatnonzero(tracked | unheard | as_is)
    located = np.array([bool(name) for name in drive.locations], dtype=np.bool_)
    return _Verdicts(
        kept=kept,
        matched=(tracked | (as_is & windows.matched))[kept],
        clear=((tracked & located[windows.location]) | (as_is & windows.clear))[kept],
        matched_hz=matched_hz[kept],
        rel_error=rel_error[kept],
        amp=amp[kept],
    )


def _tracked_line_scale(
    windows: _Windows, excluded: set[int], bin_hz: float, compliance: float
) -> float:
    """The order line's factor over its prediction where the clear matches place one, else 1."""
    clear = np.flatnonzero(windows.clear)
    points = [
        _LinePoint(predicted_hz, matched_hz)
        for index, predicted_hz, matched_hz in zip(
            clear.tolist(),
            windows.predicted_hz[clear].tolist(),
            windows.matched_hz[clear].tolist(),
            strict=True,
        )
        if index not in excluded
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
