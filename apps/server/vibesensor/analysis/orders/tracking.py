"""Order-tracked reads: an order's level at its own line in every window, at every sensor.

A window's ranked peaks show an order only where it stands out of that one
spectrum, and only at the sensors where it does. Read at the frequency the
order predicts in every window, whatever louder content the window holds
elsewhere, and averaged over the windows of one sensor at one speed, the
band's power over the floor beside it is the order's own level there: about
zero at a sensor the order does not reach over a smooth floor, and compared
between sensors by the order rather than by which window's peaks it ranked
in. A broad resonance at the line reads as a level of its own (its curvature
over the flanks). See "Order-tracked reads" in docs/order_tracking.md.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from math import sqrt

from vibesensor.analysis._types import Sample
from vibesensor.domain.order_match import SensorOrderLevel
from vibesensor.dsp.constants import FFT_N, SAMPLE_RATE_HZ
from vibesensor.dsp.window_spectrum import LineRead
from vibesensor.recording.run_schema import RunMetadata

__all__ = [
    "TrackedCells",
    "line_half_width_hz",
    "speed_rates_kmh_per_s",
    "window_duration_s",
]

# Speeds read further apart than this do not place the speed's rate of change.
_MAX_RATE_SPAN_S = 2.0


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


def line_half_width_hz(
    predicted_hz: float, speed_kmh: float | None, rate_kmh_per_s: float, window_s: float
) -> float:
    """How far an order's line sweeps either side of its centre within one window.

    A speed-following order moves with the speed: braking from 100 km/h at
    5 m/s² sweeps it 46 % over a 2.56 s window, smearing it over many bins.
    The read takes in the whole sweep.
    """
    if speed_kmh is None or speed_kmh <= 0:
        return 0.0
    return predicted_hz * abs(rate_kmh_per_s) * window_s / (2.0 * speed_kmh)


@dataclass(slots=True)
class _Sums:
    excess: float = 0.0
    flanks: float = 0.0
    windows: int = 0

    def add(self, read: LineRead) -> None:
        self.excess += read.excess
        self.flanks += read.flanks
        self.windows += 1

    def merge(self, other: _Sums) -> None:
        self.excess += other.excess
        self.flanks += other.flanks
        self.windows += other.windows


@dataclass(slots=True)
class TrackedCells:
    """One order's line reads summed by sensor, speed bin and braking."""

    cells: dict[tuple[str, str, bool], _Sums] = field(default_factory=dict)

    def add(self, key: tuple[str, str, bool], read: LineRead) -> None:
        cell = self.cells.get(key)
        if cell is None:
            cell = self.cells[key] = _Sums()
        cell.add(read)

    def sensor_levels(
        self, speeds: Collection[tuple[str, bool]], *, braking_only: bool = False
    ) -> tuple[SensorOrderLevel, ...]:
        """The order's own level at each sensor over the cells at *speeds* (speed bin, braking).

        Every cell when *speeds* is empty; only the braking cells with
        *braking_only* (brake judder is there only while braking, and the
        windows between stops would average it down). The windows' power over the floor is
        averaged before its root is taken: where the order is absent it is as
        often below zero as above. Strongest first.
        """
        by_location: dict[str, _Sums] = defaultdict(_Sums)
        for (location, speed_bin, braking), cell in self.cells.items():
            if braking_only and not braking:
                continue
            if not speeds or (speed_bin, braking) in speeds:
                by_location[location].merge(cell)
        levels = [
            SensorOrderLevel(
                location=location,
                level_g=sqrt(max(0.0, total.excess) / total.windows),
                floor_g=sqrt(total.flanks / total.windows),
                windows=total.windows,
            )
            for location, total in by_location.items()
            if total.windows
        ]
        return tuple(sorted(levels, key=lambda level: (-level.level_g, level.location)))
