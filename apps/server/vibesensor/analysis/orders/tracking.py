"""Order-tracked reads: an order's level at its own line in every window, at every sensor.

A window's ranked peaks show an order only where it stands out of that one
spectrum, and only at the sensors where it does. Read at the frequency the
order predicts in every window, whatever louder content the window holds
elsewhere, the middle of the band's power over the floor beside it, over
the windows of one sensor at one speed in one driving phase, is the order's
own level there, compared between sensors by the order rather than by which
window's peaks it ranked in. Where the order is absent the reads scatter
about zero, so a sensor hears the order only where their middle stands out
of that scatter, and these levels decide where an order is heard. See
"Order-tracked reads" in docs/order_tracking.md.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from math import sqrt
from statistics import median

from vibesensor.analysis._types import Sample
from vibesensor.domain.driving_segment import DrivingPhase
from vibesensor.domain.order_match import SensorOrderLevel
from vibesensor.dsp.constants import FFT_N, SAMPLE_RATE_HZ
from vibesensor.dsp.line_significance import (
    MIN_INDEPENDENT_READS,
    MIN_SCATTER_READS,
    SENSOR_STANDARD_ERRORS,
    clear,
    deviations,
    independent_share,
    normalized,
    scatter,
    stands_out,
)
from vibesensor.dsp.window_spectrum import LineRead
from vibesensor.recording.run_schema import RunMetadata

__all__ = [
    "TrackedCells",
    "speed_rates_kmh_per_s",
    "window_duration_s",
]

# Speeds read further apart than this do not place the speed's rate of change.
_MAX_RATE_SPAN_S = 2.0
# A driving phase is judged on its own only to tell where a peak near the line
# is the order's (``heard_phases``), and a phase holds a few of the drive's
# windows: two standard errors (one-sided 2.3 %).
_PHASE_STANDARD_ERRORS = 2.0
# An intermittent order is placed over the stretches it is there: each cell's
# reads are judged in blocks of this many window lengths (5.1 s at 2.56 s).
_PRESENCE_BLOCK_WINDOWS = 2.0
_BRAKING_PHASE = DrivingPhase.BRAKING.value


def window_duration_s(context: RunMetadata) -> float:
    sample_rate_hz = context.raw_sample_rate_hz or SAMPLE_RATE_HZ
    return (context.fft_window_size_samples or FFT_N) / sample_rate_hz


def speed_rates_kmh_per_s(samples: Sequence[Sample]) -> list[float]:
    """Each sample's rate of speed change (km/h per s) from its sensor's neighbouring samples."""
    by_sensor: dict[str, list[int]] = defaultdict(list)
    for index, sample in enumerate(samples):
        if sample.t_s is not None and sample.speed_kmh is not None:
            by_sensor[sample.client_id].append(index)
    rates = [0.0] * len(samples)
    for indices in by_sensor.values():
        indices.sort(key=lambda index: samples[index].t_s or 0.0)
        for position, index in enumerate(indices):
            before = samples[indices[max(0, position - 1)]]
            after = samples[indices[min(len(indices) - 1, position + 1)]]
            span = (after.t_s or 0.0) - (before.t_s or 0.0)
            if 0 < span <= _MAX_RATE_SPAN_S:
                rates[index] = ((after.speed_kmh or 0.0) - (before.speed_kmh or 0.0)) / span
    return rates


@dataclass(slots=True)
class _Cell:
    """One sensor's reads at one speed in one driving phase.

    Its level and floor are the middle of its reads, not their mean: a
    pothole's few wild windows shift a mean far more than the order does.
    Its control reads are taken the same way beside the order's line, where
    the order is not (``add_control``).
    """

    excess: list[float] = field(default_factory=list)
    flanks: list[float] = field(default_factory=list)
    t: list[float] = field(default_factory=list)
    control_excess: list[float] = field(default_factory=list)
    control_flanks: list[float] = field(default_factory=list)

    @property
    def windows(self) -> int:
        return len(self.excess)

    def normalized(self) -> list[float]:
        """Each read's excess over the cell's floor beside the line.

        One floor for the cell, not each read's own: a read whose flanks dip
        by chance would weigh more, and the reads would stand over zero where
        the order is absent.
        """
        return normalized(self.excess, self.flanks)

    def control_normalized(self) -> list[float]:
        """Each control read's excess over the controls' floor."""
        return normalized(self.control_excess, self.control_flanks)

    def clear(self) -> bool:
        """Whether the line stands ``HEARD_OVER_FLOOR`` (6 dB) over the floor beside it.

        As a ranked peak must stand over its window's floor.
        """
        return clear(self.excess, self.flanks)

    def present(self, block_s: float) -> tuple[float, int]:
        """The middle read where the order is there, and how many reads place it.

        The cell's reads are split into blocks *block_s* long; a block where
        the line stands clear (``clear``) is a stretch the order is there.
        The middle read over those blocks, weighed by their reads; the whole
        cell's middle read where no block is clear. An order there for half the
        drive (a misfire that comes and goes) reads its level while there, not
        half of it.
        """
        whole = (median(self.excess), self.windows)
        if block_s <= 0:
            return whole
        blocks: dict[int, list[int]] = defaultdict(list)
        for index, t_s in enumerate(self.t):
            if t_s == t_s:
                blocks[int(t_s // block_s)].append(index)
        there = [
            (median(excess), len(indices))
            for indices in blocks.values()
            if len(indices) >= MIN_SCATTER_READS
            for excess in ([self.excess[index] for index in indices],)
            if clear(excess, [self.flanks[index] for index in indices])
        ]
        if not there:
            return whole
        reads = sum(count for _middle, count in there)
        return sum(middle * count for middle, count in there) / reads, reads


@dataclass(frozen=True, slots=True)
class _Judge:
    """What a sensor's reads are judged by: one read's scatter, the share of independent reads."""

    scatter: float
    independent_share: float

    def stands_out(self, cells: Sequence[_Cell], standard_errors: float) -> bool:
        """Whether the middle of the cells' reads stands *standard_errors* over zero."""
        reads = [read for cell in cells for read in cell.normalized()]
        return stands_out(reads, self.scatter, self.independent_share, standard_errors)


def _level(
    location: str, cells: Sequence[_Cell], *, heard: bool, block_s: float
) -> SensorOrderLevel:
    """The order's level over *cells* (0 unless *heard*): its power over the floor while there.

    Each cell's middle read while the order is there (``_Cell.present``),
    weighed by the reads that place it.
    """
    present = [cell.present(block_s) for cell in cells if cell.excess]
    reads = sum(count for _middle, count in present)
    excess = sum(middle * count for middle, count in present) / reads if reads else 0.0
    return SensorOrderLevel(
        location=location,
        level_g=sqrt(excess) if heard and excess > 0 else 0.0,
        floor_g=sqrt(median(read for cell in cells for read in cell.flanks)),
        windows=sum(cell.windows for cell in cells),
        read_g=sqrt(excess) if excess > 0 else 0.0,
    )


@dataclass(slots=True)
class TrackedCells:
    """One order's line reads by sensor, speed bin and driving phase.

    ``window_s`` is the analysis window's length; ``times`` the times (s) of
    each sensor's reads, which place how far apart its windows are. An order
    that can be there only while braking (``braking_alone``: a wheel order,
    as brake judder is) is also heard over the braking windows alone.
    """

    window_s: float
    braking_alone: bool = False
    cells: dict[tuple[str, str, str], _Cell] = field(default_factory=dict)
    times: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def _cell(self, key: tuple[str, str, str]) -> _Cell:
        cell = self.cells.get(key)
        if cell is None:
            cell = self.cells[key] = _Cell()
        return cell

    def add(self, key: tuple[str, str, str], read: LineRead, t_s: float | None) -> None:
        cell = self._cell(key)
        cell.excess.append(read.excess)
        cell.flanks.append(read.flanks)
        cell.t.append(t_s if t_s is not None else float("nan"))
        if t_s is not None:
            self.times[key[0]].append(t_s)

    def add_control(self, key: tuple[str, str, str], read: LineRead) -> None:
        """A read beside the order's line in the same window, where the order is not."""
        cell = self._cell(key)
        cell.control_excess.append(read.excess)
        cell.control_flanks.append(read.flanks)

    def _independent_share(self, location: str) -> float:
        """The share of a sensor's windows that count as independent reads."""
        return independent_share(self.times.get(location, ()), self.window_s)

    @property
    def _block_s(self) -> float:
        return _PRESENCE_BLOCK_WINDOWS * self.window_s

    def heard_cells(self) -> dict[tuple[str, str, str], SensorOrderLevel]:
        """The order's own level, over the floor beside its line, in each cell where it is heard.

        A sensor hears the order where the middle of all its reads stands out
        of their scatter (``heard_sensors``): a speed bin's few windows
        cannot tell a strong order from the scatter its own beat with the
        floor adds, the drive's can. In each of its cells where the line then
        stands ``heard_peak_over_floor`` clear of the floor beside it
        (``_Cell.clear``), as a ranked peak must, the cell hears the order:
        at that sensor, at that speed, in that driving phase, whether or not it ever
        ranked among a window's peaks.
        """
        heard = self.heard_sensors()
        phases = self.heard_phases()
        return {
            key: _level(key[0], (cell,), heard=True, block_s=self._block_s)
            for key, cell in self.cells.items()
            if key[0] in heard and (key[0], key[2]) in phases and cell.clear()
        }

    def heard_sensors(self) -> set[str]:
        """The sensors where the middle of the order's reads stands out of their scatter.

        Over the whole drive, three standard errors over zero. An order that
        can be there only while braking (``braking_alone``) is absent from
        the rest of the drive: it is also heard where the braking windows'
        reads stand out of their own scatter and the line stands clear of the
        floor in one of their cells.
        """
        judges = self._judges()
        heard = {
            location
            for location, cells in self._by_location().items()
            if judges[location].stands_out(cells, SENSOR_STANDARD_ERRORS)
        }
        if self.braking_alone:
            braking = self._judges(_BRAKING_PHASE)
            heard |= {
                location
                for location, cells in self._by_location(phases=(_BRAKING_PHASE,)).items()
                if any(cell.clear() for cell in cells)
                and braking[location].stands_out(cells, SENSOR_STANDARD_ERRORS)
            }
        return heard

    def heard_phases(self) -> set[tuple[str, str]]:
        """The (sensor, driving phase) pairs where the middle of the phase's reads stands out.

        A clear ranked peak near the line counts for the order only there: in
        the guided coast-down in neutral the engine idles, and a body mode the
        swept line passes is no part of the engine's order.
        """
        return {
            (location, phase)
            for phase in {phase for _location, _speed_bin, phase in self.cells}
            for judges in (self._judges(phase),)
            for location, cells in self._by_location(phases=(phase,)).items()
            if judges[location].stands_out(cells, _PHASE_STANDARD_ERRORS)
        }

    def _by_location(
        self, speeds: Collection[str] = (), phases: Collection[str] = ()
    ) -> dict[str, list[_Cell]]:
        by_location: dict[str, list[_Cell]] = defaultdict(list)
        for (location, speed_bin, phase), cell in self.cells.items():
            if (not speeds or speed_bin in speeds) and (not phases or phase in phases):
                by_location[location].append(cell)
        return by_location

    def _judges(self, phase: str | None = None) -> dict[str, _Judge]:
        """Each sensor's read scatter and independent share, which its reads are judged by.

        The scatter is that of the control reads beside the line, where the
        order is not: the median distance of a control read from its own
        cell's middle (scaled to a standard deviation, ``scatter``), over
        the cells of a few control reads or more, else from the middle of all
        the sensor's control reads. A strong order's own beat with the floor
        does not widen it, so a faint order beside a strong one is judged by
        the floor's scatter alone. Without control reads (the line runs near
        the spectrum's edge), the reads' own distance from their cell's middle
        over the cells of a few windows or more: the order's level changing
        with speed is not scatter, and a pothole's few wild reads do not widen
        it. Over the cells of driving phase *phase* when given: a stop's
        windows scatter more than a cruise's.
        """
        judges = {}
        for location, cells in self._by_location(phases=() if phase is None else (phase,)).items():
            distances = deviations(
                [cell.control_normalized() for cell in cells], MIN_SCATTER_READS
            ) or deviations([cell.normalized() for cell in cells], 1)
            judges[location] = _Judge(
                scatter=scatter(distances or [0.0]),
                independent_share=self._independent_share(location),
            )
        return judges

    def sensor_levels(
        self, speeds: Collection[str], phases: Collection[str] = ()
    ) -> tuple[SensorOrderLevel, ...]:
        """The order's own level at each sensor over the cells at speed bins *speeds*.

        Every speed bin when *speeds* is empty; only the cells of the driving
        phases *phases* when given (brake judder is there only while braking,
        and the windows between stops would dilute it). The middle of the windows'
        power over the floor is taken before its root: where the order is
        absent it is as often below zero as above. A sensor whose reads do not
        stand out of their scatter (``_Judge.stands_out``) reads 0; a sensor
        with too few reads over the drive to place a level
        (``_MIN_INDEPENDENT_READS``) has none. Strongest first.
        """
        judges = self._judges(next(iter(phases)) if len(phases) == 1 else None)
        drive = self._by_location()
        levels = [
            _level(
                location,
                cells,
                heard=judges[location].stands_out(cells, SENSOR_STANDARD_ERRORS),
                block_s=self._block_s,
            )
            for location, cells in self._by_location(speeds, phases).items()
            if sum(cell.windows for cell in drive[location]) * judges[location].independent_share
            >= MIN_INDEPENDENT_READS
        ]
        return tuple(sorted(levels, key=lambda level: (-level.level_g, level.location)))
