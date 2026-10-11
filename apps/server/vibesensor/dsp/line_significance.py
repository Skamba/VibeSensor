"""Whether an order's line reads stand out of the floor: one rule for the report and live view.

A read (``LineRead``) is a window's power at an order's line over the floor
beside it. Where the order is absent the reads scatter about zero by the
floor's own randomness, so a sensor hears an order only where the middle of
its reads stands out of that scatter and the line stands clear of the floor,
as a ranked peak must. The post-stop order tracking judges a whole drive's
reads by this rule (``analysis/orders/tracking.py``), the live view the last
few seconds' (``live/order_hearing.py``). See "Order-tracked reads" in
docs/order_tracking.md.

The reads are arrays: a drive's are one array per column, its groups
(``group_medians``, ``present_levels``) placed by sorting, not a list per
cell. ``np.median`` is ``statistics.median`` to the bit (the middle value,
or the mean of the two middle ones), and a level's weighted mean keeps
Python's ``sum`` in first-seen order, so the verdicts do not depend on which
form the reads take. The live view's per-second ``clear`` keeps its few
reads as lists and shares the same comparison (``clear_of``).
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise
from math import ceil, cos, pi, sin, sqrt
from statistics import median
from typing import overload

import numpy as np
import numpy.typing as npt
from numpy.typing import ArrayLike

__all__ = [
    "CONTROL_REACHES",
    "HEARD_OVER_FLOOR",
    "MIN_INDEPENDENT_READS",
    "MIN_SCATTER_READS",
    "SENSOR_STANDARD_ERRORS",
    "clear",
    "clear_of",
    "deviations",
    "group_medians",
    "independent_share",
    "normalized",
    "present_level",
    "present_levels",
    "presence_block_s",
    "read_scatter",
    "scatter",
    "stands_out",
]

# A line stands clear of the floor beside it at 6 dB, three times the floor's
# power: as a ranked peak must stand over its window's floor to be heard
# ("Heard matches" in docs/order_tracking.md).
HEARD_OVER_FLOOR = 2.0
# A sensor hears an order only where the middle of its reads stands this many
# standard errors over zero. Where the order is absent the reads scatter about
# zero by the floor's own randomness. One drive asks this of about ten orders
# at each of about five sensors; at three standard errors (one-sided 0.13 %)
# about one drive in fifteen has one absent sensor hear an order.
SENSOR_STANDARD_ERRORS = 3.0
# The standard deviation of normal scatter is 1.4826 times its median absolute
# deviation, and the median of n normal reads scatters sqrt(pi / 2) = 1.2533
# times more than their mean (Rousseeuw & Croux, JASA 88(424), 1993).
_MAD_TO_SD = 1.4826
_MEDIAN_SPREAD = 1.2533
# A group's middle is placed by this many reads or more before its reads'
# distances from it count towards the scatter.
MIN_SCATTER_READS = 5
# A sensor with fewer independent reads than this places no level, heard or not.
MIN_INDEPENDENT_READS = 2.0
# An intermittent order is placed over the stretches it is there: its reads
# are judged in blocks of this many window lengths (5.1 s at 2.56 s).
_PRESENCE_BLOCK_WINDOWS = 2.0
# A window's control reads sit this many of its line read's reaches either
# side of the line: clear of the line's band and flanks, close enough to read
# the same stretch of floor.
CONTROL_REACHES = 2.0
# Groups sorted as the rows of one padded array while it holds at most this
# many cells per value (``group_medians``).
_PADDED_PER_VALUE = 4
_NONE: npt.NDArray[np.float64] = np.empty(0)


def normalized(excess: ArrayLike, flanks: ArrayLike) -> npt.NDArray[np.float64]:
    """Each read's excess over the reads' floor beside the line (their median flanks).

    One floor for the group, not each read's own: a read whose flanks dip by
    chance would weigh more, and the reads would stand over zero where the
    order is absent. None where that floor is not over zero (an empty array).
    """
    floor_reads = np.asarray(flanks, dtype=np.float64)
    floor = float(np.median(floor_reads)) if floor_reads.size else 0.0
    return np.asarray(excess, dtype=np.float64) / floor if floor > 0 else _NONE


def clear(excess: Sequence[float], flanks: Sequence[float]) -> bool:
    """Whether the reads' middle stands ``HEARD_OVER_FLOOR`` (6 dB) over the floor beside them."""
    return bool(clear_of(median(excess), median(flanks)))


@overload
def clear_of(excess_middle: float, flanks_middle: float) -> bool: ...
@overload
def clear_of(
    excess_middle: npt.NDArray[np.float64], flanks_middle: npt.NDArray[np.float64]
) -> npt.NDArray[np.bool_]: ...
def clear_of(
    excess_middle: float | npt.NDArray[np.float64], flanks_middle: float | npt.NDArray[np.float64]
) -> bool | npt.NDArray[np.bool_]:
    """``clear`` of reads given by their middle excess and flanks (or arrays of groups')."""
    over = (HEARD_OVER_FLOOR * HEARD_OVER_FLOOR - 1.0) * flanks_middle
    return (excess_middle >= over) & (over > 0)


def presence_block_s(window_s: float) -> float:
    """How long the blocks are that ``present_level`` judges reads in (s)."""
    return _PRESENCE_BLOCK_WINDOWS * window_s


def present_level(
    excess: ArrayLike, flanks: ArrayLike, t_s: ArrayLike, block_s: float
) -> tuple[float, int]:
    """The middle read where the line is there, and how many reads place it.

    The reads (each at its time *t_s*, NaN where unknown) are split into
    blocks *block_s* long; a block where the line stands clear (``clear``) is a
    stretch it is there. The middle read over those blocks, weighed by their
    reads; all the reads' middle where no block is clear. An order there for
    half the drive (a misfire that comes and goes) reads its level while there,
    not half of it. ``present_levels`` of one group.
    """
    reads = np.asarray(excess, dtype=np.float64)
    levels, counts = present_levels(
        reads,
        np.asarray(flanks, dtype=np.float64),
        np.asarray(t_s, dtype=np.float64),
        np.zeros(reads.size, dtype=np.intp),
        1,
        block_s,
    )
    return levels[0], counts[0]


def present_levels(
    excess: npt.NDArray[np.float64],
    flanks: npt.NDArray[np.float64],
    t_s: npt.NDArray[np.float64],
    group: npt.NDArray[np.intp],
    groups: int,
    block_s: float,
) -> tuple[list[float], list[int]]:
    """``present_level`` of each of *groups* groups of reads at once (*group* is each read's).

    Each group's blocks are weighed in the order their first read comes, as
    one group at a time weighs them. A group without reads reads NaN.
    """
    middle, sizes = group_medians(excess, group, groups)
    levels, counts = middle.tolist(), sizes.tolist()
    timed = np.flatnonzero(~np.isnan(t_s))
    if block_s <= 0 or not timed.size:
        return levels, counts
    # Each timed read's block within its group, numbered in (group, block) order.
    read_group = group[timed]
    block = np.floor_divide(t_s[timed], block_s).astype(np.int64)
    order = np.lexsort((block, read_group))
    starts = np.ones(timed.size, dtype=np.bool_)
    starts[1:] = (read_group[order][1:] != read_group[order][:-1]) | (
        block[order][1:] != block[order][:-1]
    )
    block_of = np.empty(timed.size, dtype=np.intp)
    block_of[order] = np.cumsum(starts) - 1
    first = order[starts]
    blocks = first.size
    block_excess, block_sizes = group_medians(excess[timed], block_of, blocks)
    block_flanks, _sizes = group_medians(flanks[timed], block_of, blocks)
    there = np.flatnonzero(
        (block_sizes >= MIN_SCATTER_READS) & clear_of(block_excess, block_flanks)
    )
    # The blocks there, by group, each group's in the order their first read comes.
    there = there[np.lexsort((first[there], read_group[first[there]]))]
    there_group = read_group[first[there]].tolist()
    there_middle = block_excess[there].tolist()
    there_reads = block_sizes[there].tolist()
    bounds = [0, *(np.flatnonzero(np.diff(read_group[first[there]])) + 1).tolist(), len(there)]
    for start, stop in pairwise(bounds):
        if start == stop:
            continue
        reads = sum(there_reads[start:stop])
        levels[there_group[start]] = (
            sum(
                middle * count
                for middle, count in zip(
                    there_middle[start:stop], there_reads[start:stop], strict=True
                )
            )
            / reads
        )
        counts[there_group[start]] = reads
    return levels, counts


def group_medians(
    values: npt.NDArray[np.float64], group: npt.NDArray[np.intp], groups: int
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.intp]]:
    """Each of *groups* groups' median (``statistics.median``'s, exactly) and size.

    *group* is each value's group; NaN where a group is empty. Small groups
    are sorted as the rows of one padded array, else all values at once.
    """
    sizes = np.bincount(group, minlength=groups)
    medians = np.full(groups, np.nan)
    filled = np.flatnonzero(sizes)
    if not filled.size:
        return medians, sizes
    width = int(sizes.max())
    starts = np.cumsum(sizes) - sizes
    low = (sizes[filled] - 1) // 2
    high = sizes[filled] // 2
    if groups * width <= _PADDED_PER_VALUE * values.size:
        order = np.argsort(group, kind="stable")
        rows = np.full((groups, width), np.nan)
        rows[group[order], np.arange(values.size) - starts[group[order]]] = values[order]
        rows.sort(axis=1)
        lower, upper = rows[filled, low], rows[filled, high]
    else:
        ranked = values[np.lexsort((values, group))]
        lower, upper = ranked[starts[filled] + low], ranked[starts[filled] + high]
    medians[filled] = np.where(low == high, lower, (lower + upper) / 2.0)
    return medians, sizes


def scatter(distances: ArrayLike) -> float:
    """One read's scatter: the median distance from the middle, scaled to a standard deviation."""
    return _MAD_TO_SD * float(np.median(np.abs(np.asarray(distances, dtype=np.float64))))


def deviations(
    groups: Sequence[npt.NDArray[np.float64]], min_pooled: int
) -> npt.NDArray[np.float64]:
    """Each read's distance from its group's middle, over the groups of a few reads or more.

    From the middle of all the reads where no group has that many, if there
    are *min_pooled* or more.
    """
    distances = [reads - np.median(reads) for reads in groups if reads.size >= MIN_SCATTER_READS]
    if distances:
        return np.concatenate(distances)
    pooled = np.concatenate(groups) if groups else _NONE
    if pooled.size < max(1, min_pooled):
        return _NONE
    return pooled - np.median(pooled)


def read_scatter(
    controls: Sequence[npt.NDArray[np.float64]], reads: Sequence[npt.NDArray[np.float64]]
) -> float:
    """One read's scatter: that of the control reads beside the line, else of the reads.

    Each group's distances from its own middle (``deviations``): of the
    control reads, of a few or more pooled where no group has that many, else
    of the normalized reads themselves; 0 without any.
    """
    distances = deviations(controls, MIN_SCATTER_READS)
    if not distances.size:
        distances = deviations(reads, 1)
    return scatter(distances) if distances.size else 0.0


def stands_out(
    reads: npt.NDArray[np.float64], read_scatter: float, share: float, standard_errors: float
) -> bool:
    """Whether the middle of the normalized *reads* stands *standard_errors* over zero.

    The standard error is ``1.2533 * scatter / sqrt(n_ind)``, ``n_ind`` the
    reads counted as independent (*share* of them, ``independent_share``).
    """
    if not reads.size:
        return False
    independent = max(1.0, reads.size * share)
    return bool(
        float(np.median(reads))
        > standard_errors * _MEDIAN_SPREAD * read_scatter / sqrt(independent)
    )


def _hann_overlap(shift: float) -> float:
    """The overlap correlation of two Hann windows *shift* of their length apart.

    Harris, *Proc. IEEE* 66(1), 1978: 16.7 % at half a window.
    """
    if shift >= 1.0:
        return 0.0
    turn = 2.0 * pi * shift
    return ((1.0 - shift) * (2.0 + cos(turn)) + 3.0 * sin(turn) / (2.0 * pi)) / 3.0


def independent_share(times_s: ArrayLike, window_s: float) -> float:
    """The share of windows read at *times_s* that count as independent reads.

    Windows ``hop`` apart overlap; the power two Hann windows read of the
    same noise correlates as the square of their overlap correlation, so
    ``n`` windows read the noise as ``n / (1 + 2 sum_k rho(k hop)^2)``
    independent ones would (Welch, *IEEE Trans. Audio Electroacoust.*
    15(2), 1967): about a fifth of them 0.25 s apart in a 2.56 s window.
    """
    times = np.unique(np.asarray(times_s, dtype=np.float64))
    if times.size < 2 or window_s <= 0:
        return 1.0
    step = float(np.median(np.diff(times))) / window_s
    if step <= 0:
        return 1.0
    shared = sum(_hann_overlap(k * step) ** 2 for k in range(1, ceil(1.0 / step)))
    return 1.0 / (1.0 + 2.0 * shared)
