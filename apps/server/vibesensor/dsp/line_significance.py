"""Whether an order's line reads stand out of the floor: one rule for the report and live view.

A read (``LineRead``) is a window's power at an order's line over the floor
beside it. Where the order is absent the reads scatter about zero by the
floor's own randomness, so a sensor hears an order only where the middle of
its reads stands out of that scatter and the line stands clear of the floor,
as a ranked peak must. The post-stop order tracking judges a whole drive's
reads by this rule (``analysis/orders/tracking.py``), the live view the last
few seconds' (``live/order_hearing.py``). See "Order-tracked reads" in
docs/order_tracking.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise
from math import ceil, cos, pi, sin, sqrt
from statistics import median

__all__ = [
    "CONTROL_REACHES",
    "HEARD_OVER_FLOOR",
    "MIN_INDEPENDENT_READS",
    "MIN_SCATTER_READS",
    "SENSOR_STANDARD_ERRORS",
    "clear",
    "deviations",
    "independent_share",
    "normalized",
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
# A window's control reads sit this many of its line read's reaches either
# side of the line: clear of the line's band and flanks, close enough to read
# the same stretch of floor.
CONTROL_REACHES = 2.0


def normalized(excess: Sequence[float], flanks: Sequence[float]) -> list[float]:
    """Each read's excess over the reads' floor beside the line (their median flanks).

    One floor for the group, not each read's own: a read whose flanks dip by
    chance would weigh more, and the reads would stand over zero where the
    order is absent.
    """
    floor = median(flanks) if flanks else 0.0
    return [read / floor for read in excess] if floor > 0 else []


def clear(excess: Sequence[float], flanks: Sequence[float]) -> bool:
    """Whether the reads' middle stands ``HEARD_OVER_FLOOR`` (6 dB) over the floor beside them."""
    return median(excess) >= (HEARD_OVER_FLOOR * HEARD_OVER_FLOOR - 1.0) * median(flanks) > 0


def scatter(distances: Sequence[float]) -> float:
    """One read's scatter: the median distance from the middle, scaled to a standard deviation."""
    return _MAD_TO_SD * median(abs(distance) for distance in distances)


def deviations(groups: Sequence[Sequence[float]], min_pooled: int) -> list[float]:
    """Each read's distance from its group's middle, over the groups of a few reads or more.

    From the middle of all the reads where no group has that many, if there
    are *min_pooled* or more.
    """
    distances = [
        read - middle
        for reads in groups
        if len(reads) >= MIN_SCATTER_READS
        for middle in (median(reads),)
        for read in reads
    ]
    pooled = [read for reads in groups for read in reads]
    if distances or len(pooled) < max(1, min_pooled):
        return distances
    middle = median(pooled)
    return [read - middle for read in pooled]


def stands_out(
    reads: Sequence[float], read_scatter: float, share: float, standard_errors: float
) -> bool:
    """Whether the middle of the normalized *reads* stands *standard_errors* over zero.

    The standard error is ``1.2533 * scatter / sqrt(n_ind)``, ``n_ind`` the
    reads counted as independent (*share* of them, ``independent_share``).
    """
    if not reads:
        return False
    independent = max(1.0, len(reads) * share)
    return median(reads) > standard_errors * _MEDIAN_SPREAD * read_scatter / sqrt(independent)


def _hann_overlap(shift: float) -> float:
    """The overlap correlation of two Hann windows *shift* of their length apart.

    Harris, *Proc. IEEE* 66(1), 1978: 16.7 % at half a window.
    """
    if shift >= 1.0:
        return 0.0
    turn = 2.0 * pi * shift
    return ((1.0 - shift) * (2.0 + cos(turn)) + 3.0 * sin(turn) / (2.0 * pi)) / 3.0


def independent_share(times_s: Sequence[float], window_s: float) -> float:
    """The share of windows read at *times_s* that count as independent reads.

    Windows ``hop`` apart overlap; the power two Hann windows read of the
    same noise correlates as the square of their overlap correlation, so
    ``n`` windows read the noise as ``n / (1 + 2 sum_k rho(k hop)^2)``
    independent ones would (Welch, *IEEE Trans. Audio Electroacoust.*
    15(2), 1967): about a fifth of them 0.25 s apart in a 2.56 s window.
    """
    times = sorted(set(times_s))
    if len(times) < 2 or window_s <= 0:
        return 1.0
    step = median(later - earlier for earlier, later in pairwise(times)) / window_s
    if step <= 0:
        return 1.0
    shared = sum(_hann_overlap(k * step) ** 2 for k in range(1, ceil(1.0 / step)))
    return 1.0 / (1.0 + 2.0 * shared)
