"""Order-match observation — typed internal frequency-domain match record."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import combinations
from math import floor
from statistics import median

__all__ = ["OrderMatchObservation", "frequency_tracking_slope", "trend_moves"]

_CLOSE_MATCH_THRESHOLD = 0.05  # 5% relative error
# The order-match tolerance is several percent wide, so a speed that moves less
# than this cannot tell an order from a fixed tone it passes.
_MIN_TRACKING_SPAN = 0.1
_MIN_TRACKING_POINTS = 4
# Pairwise slopes grow quadratically; an evenly spaced subset keeps it cheap.
_MAX_TRACKING_POINTS = 200
_TRACKING_TREND_BIN_S = 2.0
_MIN_TREND_TO_NOISE = 2.0


@dataclass(frozen=True, slots=True)
class OrderMatchObservation:
    """A single frequency-domain order/reference match observation.

    Records the predicted vs observed frequency at a given time and speed,
    with amplitude and spatial location context. ``heard`` is the order
    analysis's one verdict on the match: the order itself, not floor-level road
    noise the matcher landed on near its predicted frequency (see "Heard
    matches" in ``docs/order_tracking.md``).
    """

    predicted_hz: float
    matched_hz: float
    rel_error: float
    amp: float
    location: str
    t_s: float | None = None
    speed_kmh: float | None = None
    phase: str | None = None
    heard: bool = False

    def __post_init__(self) -> None:
        if self.predicted_hz <= 0:
            raise ValueError("predicted_hz must be > 0")
        if self.rel_error < 0:
            raise ValueError("rel_error must be >= 0")

    @property
    def is_close_match(self) -> bool:
        """Whether this observation is a close frequency match."""
        return self.rel_error <= _CLOSE_MATCH_THRESHOLD

    @property
    def frequency_error_hz(self) -> float:
        """Absolute frequency error in Hz."""
        return abs(self.predicted_hz - self.matched_hz)


def frequency_tracking_slope(points: Sequence[OrderMatchObservation]) -> float | None:
    """How the matched frequency moves with the predicted one (robust Theil-Sen slope).

    An order's peaks follow its prediction (slope near 1); a fixed-frequency tone
    that the prediction sweeps past stays put (slope near 0). Only meaningful
    when the speed really changed over the windows judged (``trend_moves``): at a
    steady speed an order and a fixed tone look the same, and speed-reading noise
    flattens the slope. ``None`` with too few points.
    """
    if len(points) < _MIN_TRACKING_POINTS:
        return None
    step = -(-len(points) // _MAX_TRACKING_POINTS)
    sample = points[::step]
    slopes = [
        (b.matched_hz - a.matched_hz) / (b.predicted_hz - a.predicted_hz)
        for a, b in combinations(sample, 2)
        if b.predicted_hz != a.predicted_hz
    ]
    return median(slopes) if slopes else None


def trend_moves(values_at: Iterable[tuple[float, float]]) -> bool:
    """Whether a ``(t_s, value)`` series really moves over time.

    The trend is the median of each ``_TRACKING_TREND_BIN_S`` time bin. It must
    move by at least ``_MIN_TRACKING_SPAN`` of its median and by more than
    ``_MIN_TREND_TO_NOISE`` times the typical spread inside one bin, so reading
    noise (speed jitter) around a steady value does not count as movement.
    """
    by_bin: dict[int, list[float]] = defaultdict(list)
    for t_s, value in values_at:
        by_bin[floor(t_s / _TRACKING_TREND_BIN_S)].append(value)
    if len(by_bin) < 2:
        return False
    trend = [median(values) for values in by_bin.values()]
    span = max(trend) - min(trend)
    noise = median(max(values) - min(values) for values in by_bin.values())
    return span >= _MIN_TRACKING_SPAN * median(trend) and span > _MIN_TREND_TO_NOISE * noise
