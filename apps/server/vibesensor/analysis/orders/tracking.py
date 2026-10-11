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
from itertools import pairwise
from math import sqrt
from typing import TYPE_CHECKING, NamedTuple

import numpy as np
import numpy.typing as npt

from vibesensor.domain.driving_segment import DrivingPhase
from vibesensor.domain.order_match import SensorOrderLevel
from vibesensor.dsp.constants import FFT_N, SAMPLE_RATE_HZ
from vibesensor.dsp.line_significance import (
    MIN_INDEPENDENT_READS,
    SENSOR_STANDARD_ERRORS,
    clear_of,
    group_medians,
    independent_share,
    presence_block_s,
    present_levels,
    read_scatter,
    stands_out,
)
from vibesensor.recording.run_schema import RunMetadata

if TYPE_CHECKING:
    from vibesensor.analysis.drive_table import DriveTable

__all__ = [
    "CellKey",
    "CellReads",
    "TrackedCells",
    "frequency_tracking_slope",
    "speed_rates_kmh_per_s",
    "window_duration_s",
]

# Speeds read further apart than this do not place the speed's rate of change.
_MAX_RATE_SPAN_S = 2.0
# A driving phase is judged on its own only to tell where a peak near the line
# is the order's (``heard_phases``), and a phase holds a few of the drive's
# windows: two standard errors (one-sided 2.3 %).
_PHASE_STANDARD_ERRORS = 2.0
_BRAKING_PHASE = DrivingPhase.BRAKING.value
_NONE: npt.NDArray[np.float64] = np.empty(0)
_MIN_TRACKING_POINTS = 4
# Pairwise slopes grow quadratically; an evenly spaced subset keeps it cheap.
_MAX_TRACKING_POINTS = 200

# A cell: one sensor's reads at one speed bin in one driving phase.
type CellKey = tuple[str, str, str]


def window_duration_s(context: RunMetadata) -> float:
    sample_rate_hz = context.raw_sample_rate_hz or SAMPLE_RATE_HZ
    return (context.fft_window_size_samples or FFT_N) / sample_rate_hz


def speed_rates_kmh_per_s(table: DriveTable) -> npt.NDArray[np.float64]:
    """Each sample's rate of speed change (km/h per s) from its sensor's neighbouring samples.

    0 where those are further apart than ``_MAX_RATE_SPAN_S``; a sample without
    a time or speed has none.
    """
    rates = np.zeros(table.size)
    rated = table.timed & table.has_speed
    # A speed of 0 is 0, whatever its sign.
    speed_kmh = np.where(table.speed_kmh != 0, table.speed_kmh, 0.0)
    for client in range(len(table.clients)):
        indices = np.flatnonzero(rated & (table.client_of == client))
        if not indices.size:
            continue
        indices = indices[np.argsort(table.t_s[indices], kind="stable")]
        positions = np.arange(indices.size)
        before = indices[np.maximum(0, positions - 1)]
        after = indices[np.minimum(indices.size - 1, positions + 1)]
        span = table.t_s[after] - table.t_s[before]
        spanned = (span > 0) & (span <= _MAX_RATE_SPAN_S)
        rates[indices[spanned]] = (speed_kmh[after[spanned]] - speed_kmh[before[spanned]]) / span[
            spanned
        ]
    return rates


def frequency_tracking_slope(
    predicted_hz: npt.NDArray[np.float64], matched_hz: npt.NDArray[np.float64]
) -> float | None:
    """How the matched frequency moves with the predicted one (robust Theil-Sen slope).

    *predicted_hz* and *matched_hz* are the matches' frequencies, in order.
    An order's peaks follow its prediction (slope near 1); a fixed-frequency tone
    that the prediction sweeps past stays put (slope near 0). Only meaningful
    when the speed really changed over the windows judged (``trend_moves``): at a
    steady speed an order and a fixed tone look the same, and speed-reading noise
    flattens the slope. ``None`` with too few points.
    """
    if predicted_hz.size < _MIN_TRACKING_POINTS:
        return None
    step = -(-predicted_hz.size // _MAX_TRACKING_POINTS)
    predicted = predicted_hz[::step]
    matched = matched_hz[::step]
    # Every pair of the evenly spaced subset whose predictions differ.
    earlier, later = np.triu_indices(predicted.size, 1)
    run = predicted[later] - predicted[earlier]
    moved = run != 0
    if not moved.any():
        return None
    return float(np.median((matched[later] - matched[earlier])[moved] / run[moved]))


class CellReads(NamedTuple):
    """Line reads as columns: each read's cell (an index into the cells), excess and flanks.

    *t_s* is each read's time (NaN where unknown); control reads have none.
    """

    cell: npt.NDArray[np.intp]
    excess: npt.NDArray[np.float64]
    flanks: npt.NDArray[np.float64]
    t_s: npt.NDArray[np.float64] | None = None


class _Judge(NamedTuple):
    """What a sensor's reads are judged by: one read's scatter, the share of independent reads."""

    scatter: float
    independent_share: float


class TrackedCells:
    """One order's line reads by sensor, speed bin and driving phase, as columns.

    *keys* are the cells; *reads* the reads at the order's line and
    *controls* the control reads beside it in the same windows, where the
    order is not, each naming its cell, a cell's reads in the order they
    come. ``window_s`` is the analysis window's length: the times of a
    sensor's reads place how far apart its windows are. An order that can be
    there only while braking (``braking_alone``: a wheel order, as brake
    judder is) is also heard over the braking windows alone.

    A cell's level and floor are the middle of its reads, not their mean: a
    pothole's few wild windows shift a mean far more than the order does.
    Every cell's floor, middle and level while the order is there are worked
    out once, for all the cells together (``dsp/line_significance.py``'s
    column forms); a verdict on a sensor takes the middle of its cells'
    reads together.
    """

    __slots__ = (
        "_clear",
        "_control_normalized",
        "_flanks",
        "_hearing",
        "_judged",
        "_normalized",
        "_present",
        "_shares",
        "_windows",
        "braking_alone",
        "keys",
        "window_s",
    )

    def __init__(
        self,
        window_s: float,
        keys: Sequence[CellKey],
        reads: CellReads,
        controls: CellReads,
        *,
        braking_alone: bool = False,
    ) -> None:
        self.window_s = window_s
        self.braking_alone = braking_alone
        self.keys = list(keys)
        count = len(self.keys)
        order = np.argsort(reads.cell, kind="stable")
        cell = reads.cell[order]
        excess = reads.excess[order]
        flanks = reads.flanks[order]
        t_s = reads.t_s[order] if reads.t_s is not None else np.full(order.size, np.nan)
        windows = np.bincount(cell, minlength=count)
        floor, _sizes = group_medians(flanks, cell, count)
        middle, _sizes = group_medians(excess, cell, count)
        bounds = [0, *np.cumsum(windows).tolist()]
        self._windows: list[int] = windows.tolist()
        # Whether the line stands ``HEARD_OVER_FLOOR`` (6 dB) over the floor
        # beside it, as a ranked peak must stand over its window's floor.
        self._clear: list[bool] = clear_of(middle, floor).tolist()
        # The middle read where the order is there, and how many reads place it
        # (``present_level``).
        levels, level_reads = present_levels(
            excess, flanks, t_s, cell, count, presence_block_s(window_s)
        )
        self._present = list(zip(levels, level_reads, strict=True))
        self._flanks = [flanks[start:stop] for start, stop in pairwise(bounds)]
        # Each read's excess over its cell's floor beside the line
        # (``normalized``): one floor for the cell, not each read's own.
        self._normalized = [
            excess[start:stop] / cell_floor if cell_floor > 0 else _NONE
            for (start, stop), cell_floor in zip(pairwise(bounds), floor.tolist(), strict=True)
        ]
        control_order = np.argsort(controls.cell, kind="stable")
        control_cell = controls.cell[control_order]
        control_excess = controls.excess[control_order]
        control_floor, control_sizes = group_medians(
            controls.flanks[control_order], control_cell, count
        )
        self._control_normalized = [
            control_excess[start:stop] / cell_floor if cell_floor > 0 else _NONE
            for (start, stop), cell_floor in zip(
                pairwise([0, *np.cumsum(control_sizes).tolist()]),
                control_floor.tolist(),
                strict=True,
            )
        ]
        # The share of each sensor's windows that count as independent reads.
        locations = list(dict.fromkeys(location for location, _speed_bin, _phase in self.keys))
        read_location = np.array(
            [locations.index(location) for location, _speed_bin, _phase in self.keys],
            dtype=np.intp,
        )[cell]
        timed = ~np.isnan(t_s)
        self._shares = {
            location: independent_share(t_s[timed & (read_location == code)], window_s)
            for code, location in enumerate(locations)
        }
        # Each driving phase's judges (``_judges``) and the phases that hear
        # the order (``heard_phases``), worked out once: every verdict on the
        # order asks for them again.
        self._judged: dict[str | None, dict[str, _Judge]] = {}
        self._hearing: set[tuple[str, str]] | None = None

    def heard_cells(self) -> dict[CellKey, SensorOrderLevel]:
        """The order's own level, over the floor beside its line, in each cell where it is heard.

        A sensor hears the order where the middle of all its reads stands out
        of their scatter (``heard_sensors``): a speed bin's few windows
        cannot tell a strong order from the scatter its own beat with the
        floor adds, the drive's can. In each of its cells where the line then
        stands ``heard_peak_over_floor`` clear of the floor beside it, as a
        ranked peak must, the cell hears the order: at that sensor, at that
        speed, in that driving phase, whether or not it ever ranked among a
        window's peaks.
        """
        heard = self.heard_sensors()
        phases = self.heard_phases()
        return {
            key: self._level(key[0], (cell,), heard=True)
            for cell, key in enumerate(self.keys)
            if key[0] in heard and (key[0], key[2]) in phases and self._clear[cell]
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
            if self._stands_out(judges[location], cells, SENSOR_STANDARD_ERRORS)
        }
        if self.braking_alone:
            braking = self._judges(_BRAKING_PHASE)
            heard |= {
                location
                for location, cells in self._by_location(phases=(_BRAKING_PHASE,)).items()
                if any(self._clear[cell] for cell in cells)
                and self._stands_out(braking[location], cells, SENSOR_STANDARD_ERRORS)
            }
        return heard

    def heard_phases(self) -> set[tuple[str, str]]:
        """The (sensor, driving phase) pairs where the middle of the phase's reads stands out.

        A clear ranked peak near the line counts for the order only there: in
        the guided coast-down in neutral the engine idles, and a body mode the
        swept line passes is no part of the engine's order.
        """
        if self._hearing is None:
            self._hearing = {
                (location, phase)
                for phase in {phase for _location, _speed_bin, phase in self.keys}
                for judges in (self._judges(phase),)
                for location, cells in self._by_location(phases=(phase,)).items()
                if self._stands_out(judges[location], cells, _PHASE_STANDARD_ERRORS)
            }
        return set(self._hearing)

    def _by_location(
        self, speeds: Collection[str] = (), phases: Collection[str] = ()
    ) -> dict[str, list[int]]:
        """Each sensor's cells (at speed bins *speeds*, in driving phases *phases* when given)."""
        by_location: dict[str, list[int]] = defaultdict(list)
        for cell, (location, speed_bin, phase) in enumerate(self.keys):
            if (not speeds or speed_bin in speeds) and (not phases or phase in phases):
                by_location[location].append(cell)
        return by_location

    def _stands_out(self, judge: _Judge, cells: Sequence[int], standard_errors: float) -> bool:
        """Whether the middle of the *cells*' reads stands *standard_errors* over zero."""
        reads = [self._normalized[cell] for cell in cells]
        return stands_out(
            np.concatenate(reads) if reads else _NONE,
            judge.scatter,
            judge.independent_share,
            standard_errors,
        )

    def _judges(self, phase: str | None = None) -> dict[str, _Judge]:
        """Each sensor's read scatter and independent share, which its reads are judged by.

        The scatter is that of the control reads beside the line, where the
        order is not (``read_scatter``): the median distance of a control
        read from its own cell's middle, over the cells of a few control
        reads or more, else from the middle of all the sensor's control
        reads. A strong order's own beat with the floor does not widen it, so
        a faint order beside a strong one is judged by the floor's scatter
        alone. Without control reads (the line runs near the spectrum's
        edge), the reads' own distance from their cell's middle over the
        cells of a few windows or more: the order's level changing with speed
        is not scatter, and a pothole's few wild reads do not widen it. Over
        the cells of driving phase *phase* when given: a stop's windows
        scatter more than a cruise's.
        """
        judges = self._judged.get(phase)
        if judges is not None:
            return judges
        judges = self._judged[phase] = {}
        for location, cells in self._by_location(phases=() if phase is None else (phase,)).items():
            judges[location] = _Judge(
                scatter=read_scatter(
                    [self._control_normalized[cell] for cell in cells],
                    [self._normalized[cell] for cell in cells],
                ),
                independent_share=self._shares[location],
            )
        return judges

    def _level(self, location: str, cells: Sequence[int], *, heard: bool) -> SensorOrderLevel:
        """The order's level over *cells* (0 unless *heard*): its power over the floor while there.

        Each cell's middle read while the order is there (``present_level``),
        weighed by the reads that place it.
        """
        present = [self._present[cell] for cell in cells if self._windows[cell]]
        reads = sum(count for _middle, count in present)
        excess = sum(middle * count for middle, count in present) / reads if reads else 0.0
        return SensorOrderLevel(
            location=location,
            level_g=sqrt(excess) if heard and excess > 0 else 0.0,
            floor_g=sqrt(float(np.median(np.concatenate([self._flanks[cell] for cell in cells])))),
            windows=sum(self._windows[cell] for cell in cells),
            read_g=sqrt(excess) if excess > 0 else 0.0,
        )

    def sensor_levels(
        self, speeds: Collection[str], phases: Collection[str] = ()
    ) -> tuple[SensorOrderLevel, ...]:
        """The order's own level at each sensor over the cells at speed bins *speeds*.

        Every speed bin when *speeds* is empty; only the cells of the driving
        phases *phases* when given (brake judder is there only while braking,
        and the windows between stops would dilute it). The middle of the windows'
        power over the floor is taken before its root: where the order is
        absent it is as often below zero as above. A sensor whose reads do not
        stand out of their scatter (``stands_out``) reads 0; a sensor
        with too few reads over the drive to place a level
        (``MIN_INDEPENDENT_READS``) has none. Strongest first.
        """
        judges = self._judges(next(iter(phases)) if len(phases) == 1 else None)
        drive = self._by_location()
        levels = [
            self._level(
                location,
                cells,
                heard=self._stands_out(judges[location], cells, SENSOR_STANDARD_ERRORS),
            )
            for location, cells in self._by_location(speeds, phases).items()
            if sum(self._windows[cell] for cell in drive[location])
            * judges[location].independent_share
            >= MIN_INDEPENDENT_READS
        ]
        return tuple(sorted(levels, key=lambda level: (-level.level_g, level.location)))
