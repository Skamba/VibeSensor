"""Which orders the live spectra hear, by the report's rule over the last few seconds.

A peak inside an order's band is not the order: a healthy wheel's wheel-hop
hump often sits in the Wheel 1x or 2x band. The report reads each order at its
own line in every window and asks whether the reads stand out of the floor
beside the line (``dsp/line_significance.py``), then hears the order in each
speed bin where the line also stands clear of that floor. The live view asks
the same of each sensor's latest spectra over ``READ_SPAN_S``, one read per
sensor every ``READ_INTERVAL_S``, and of the current speed bin's reads: a
light, recent version of the report's per-sensor verdict. It decides nothing;
the report does, over the whole drive. See "The live view and the report" in
docs/metrics.md.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from statistics import median

from vibesensor.domain.finding import speed_bin_label
from vibesensor.dsp.line_significance import (
    CONTROL_REACHES,
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
from vibesensor.dsp.window_spectrum import (
    LineRead,
    WindowSpectrum,
    line_half_width_hz,
    line_reach_hz,
)
from vibesensor.live.payload_types import OrderBandPayload

__all__ = [
    "HEARD_VERDICTS",
    "READ_INTERVAL_S",
    "READ_SPAN_S",
    "LiveSpectrum",
    "OrderHearing",
]

READ_INTERVAL_S = 1.0
"""How often each sensor's latest spectrum is read at every order's line (s).

Spectra 1 s apart in a 2.56 s window overlap, and spectra closer together
add little independent evidence (``independent_share``) for the work: the
read and its verdict cost a few percent of the processing tick at this rate.
"""

READ_SPAN_S = 10.0
"""How far back the reads an order is judged by go (s): 10 reads per sensor."""

HEARD_VERDICTS = 2
"""How many verdicts in a row, each on a new read, must hear an order before it shows.

The report gives one verdict per drive, three standard errors out, so about
one healthy drive in fifteen has one absent sensor hear an order. The live
view gives one every ``READ_INTERVAL_S``: on its own, a verdict that blinks on
for one read is the floor's chance, as often as every few drives.
"""

# Speeds further apart than this do not place the speed's rate of change
# (``tracking.speed_rates_kmh_per_s`` holds the report's reads to the same).
_MAX_RATE_SPAN_S = 2.0


@dataclass(frozen=True, slots=True)
class LiveSpectrum:
    """A sensor's latest combined spectrum, its generation and its window's length (s)."""

    generation: int
    spectrum: WindowSpectrum
    window_s: float


@dataclass(frozen=True, slots=True)
class _Read:
    """One read at a line (or beside it): when, in which speed bin, and what it read."""

    t_s: float
    speed_bin: str
    line: LineRead


@dataclass(slots=True)
class _Reads:
    """One sensor's recent reads at one order's line, and the control reads beside it."""

    window_s: float
    reads: deque[_Read] = field(default_factory=deque)
    controls: deque[_Read] = field(default_factory=deque)
    # The verdicts in a row that heard the order, and the newest read they judged.
    heard_verdicts: int = 0
    judged_s: float = float("-inf")

    def trim(self, oldest_s: float) -> None:
        for queue in (self.reads, self.controls):
            while queue and queue[0].t_s < oldest_s:
                queue.popleft()

    def heard_level(self, speed_bin: str) -> float | None:
        """The middle read (g²) at speed bin *speed_bin* where the reads hear the order.

        ``None`` where they do not. The report's verdict on one sensor in one
        cell (``TrackedCells.heard_cells``): the middle of all the reads stands
        three standard errors out of the control reads' scatter, and in the
        current speed bin the line stands 6 dB clear of the floor beside it.
        A swept line that passes a body mode stands clear only while it
        passes, in the speed bin it passed it in.
        """
        if len(self.reads) < MIN_SCATTER_READS:
            return None
        # The cheap half first: most lines stand nowhere near clear of the floor.
        here = [read.line for read in self.reads if read.speed_bin == speed_bin]
        if not here or not clear([line.excess for line in here], [line.flanks for line in here]):
            return None
        share = independent_share([read.t_s for read in self.reads], self.window_s)
        if len(self.reads) * share < MIN_INDEPENDENT_READS:
            return None
        reads = normalized(
            [read.line.excess for read in self.reads], [read.line.flanks for read in self.reads]
        )
        controls = normalized(
            [read.line.excess for read in self.controls],
            [read.line.flanks for read in self.controls],
        )
        distances = deviations([controls], MIN_SCATTER_READS) or deviations([reads], 1)
        if not stands_out(reads, scatter(distances or [0.0]), share, SENSOR_STANDARD_ERRORS):
            return None
        return median(line.excess for line in here)


class OrderHearing:
    """The sensors that hear each live order band, strongest first, over the last few seconds."""

    __slots__ = ("_generations", "_heard", "_next_read_s", "_reads", "_speed")

    def __init__(self) -> None:
        self._reads: dict[tuple[str, str], _Reads] = {}
        self._generations: dict[str, int] = {}
        self._heard: dict[str, list[str]] = {}
        self._next_read_s = float("-inf")
        self._speed: tuple[float, float] | None = None

    def due(self, now_s: float) -> bool:
        """Whether ``update`` at *now_s* reads: one read every ``READ_INTERVAL_S``."""
        return now_s >= self._next_read_s

    def heard_at(self, band_key: str) -> list[str]:
        """The client ids that hear the band's order, strongest first."""
        return self._heard.get(band_key, [])

    def update(
        self,
        now_s: float,
        speed_kmh: float | None,
        bands: Sequence[OrderBandPayload],
        spectra: Mapping[str, LiveSpectrum],
    ) -> None:
        """Read the new spectra at each band's line every ``READ_INTERVAL_S`` and re-judge."""
        if not self.due(now_s):
            return
        self._next_read_s = now_s + READ_INTERVAL_S
        rate = self._speed_rate(now_s, speed_kmh)
        for client_id, live in spectra.items():
            if self._generations.get(client_id) == live.generation:
                continue
            self._generations[client_id] = live.generation
            for band in bands:
                self._read(now_s, client_id, band, live, speed_kmh, rate)
        oldest_s = now_s - READ_SPAN_S
        keys = {band["key"] for band in bands}
        for key in list(self._reads):
            reads = self._reads[key]
            reads.trim(oldest_s)
            if key[0] not in spectra or key[1] not in keys or not reads.reads:
                del self._reads[key]
        for client_id in [cid for cid in self._generations if cid not in spectra]:
            del self._generations[client_id]
        self._heard = self._judge(speed_bin_label(speed_kmh or 0.0))

    def _speed_rate(self, now_s: float, speed_kmh: float | None) -> float:
        previous, self._speed = self._speed, None if speed_kmh is None else (now_s, speed_kmh)
        if previous is None or speed_kmh is None or not 0 < now_s - previous[0] <= _MAX_RATE_SPAN_S:
            return 0.0
        return (speed_kmh - previous[1]) / (now_s - previous[0])

    def _read(
        self,
        now_s: float,
        client_id: str,
        band: OrderBandPayload,
        live: LiveSpectrum,
        speed_kmh: float | None,
        rate_kmh_per_s: float,
    ) -> None:
        """One read at the band's line, and the two control reads beside it, as the report reads."""
        spectrum = live.spectrum
        line_hz = band["center_hz"]
        half_width_hz = line_half_width_hz(line_hz, speed_kmh, rate_kmh_per_s, live.window_s)
        line = spectrum.line_read(line_hz, half_width_hz)
        if line is None:
            return
        key = (client_id, band["key"])
        reads = self._reads.get(key)
        if reads is None:
            reads = self._reads[key] = _Reads(window_s=live.window_s)
        speed_bin = speed_bin_label(speed_kmh or 0.0)
        reads.reads.append(_Read(now_s, speed_bin, line))
        offset_hz = CONTROL_REACHES * line_reach_hz(half_width_hz, spectrum.bin_hz)
        for control_hz in (line_hz - offset_hz, line_hz + offset_hz):
            control = spectrum.line_read(control_hz, half_width_hz)
            if control is not None:
                reads.controls.append(_Read(now_s, speed_bin, control))

    def _judge(self, speed_bin: str) -> dict[str, list[str]]:
        """Each band's sensors that ``HEARD_VERDICTS`` verdicts in a row hear, strongest first."""
        levels: dict[str, list[tuple[float, str]]] = {}
        for (client_id, band_key), reads in self._reads.items():
            level = reads.heard_level(speed_bin)
            newest_s = reads.reads[-1].t_s
            if newest_s != reads.judged_s:
                reads.judged_s = newest_s
                reads.heard_verdicts = reads.heard_verdicts + 1 if level is not None else 0
            if level is not None and reads.heard_verdicts >= HEARD_VERDICTS:
                levels.setdefault(band_key, []).append((level, client_id))
        return {
            band_key: [
                client_id for _level, client_id in sorted(found, key=lambda x: (-x[0], x[1]))
            ]
            for band_key, found in levels.items()
        }
