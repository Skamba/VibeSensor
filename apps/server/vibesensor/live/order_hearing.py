"""Which orders the live spectra hear, by the report's rule over the last few seconds.

A peak inside an order's band is not the order: a healthy wheel's wheel-hop
hump often sits in the Wheel 1x or 2x band. The report reads each order at its
own line in every window and asks whether the reads stand out of the floor
beside the line (``dsp/line_significance.py``), then hears the order in each
speed bin where the line also stands clear of that floor. The live view asks
the same of each sensor's latest spectra over ``READ_SPAN_S``, one read per
sensor every ``READ_INTERVAL_S``, and of the current speed bin's reads: a
light, recent version of the report's per-sensor verdict. As the report does,
it does not read an order's line where it reaches a fixed tone that rings at
that sensor (a fan, a pump, a mount resonance), placed by the report's rule
(``dsp/fixed_tones.py``) over the drive so far. It decides nothing; the report
does, over the whole drive. See "The live view and the report" in
docs/metrics.md.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from statistics import median

from vibesensor.domain.finding import speed_bin_label
from vibesensor.dsp.fixed_tones import (
    RingingTone,
    clear_peak_hz,
    ringing,
    ringing_tone,
    sensor_fixed_tones,
    tone_groups,
    tone_speed_bin,
)
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
    "TONE_SPECTRA_PER_BIN",
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

TONE_SPECTRA_PER_BIN = 10
"""How many of a sensor's latest reads per speed bin place its fixed tones.

The report places a sensor's fixed tones from every spectrum of the drive,
judged per speed bin (``dsp/fixed_tones.py``); the live view from the latest
reads in each speed bin the drive has been through, so a tone that starts
(the blower switched on) is placed again where the car drives next.
"""

# Speeds further apart than this do not place the speed's rate of change
# (``tracking.speed_rates_kmh_per_s`` holds the report's reads to the same).
_MAX_RATE_SPAN_S = 2.0


@dataclass(frozen=True, slots=True)
class LiveSpectrum:
    """A sensor's latest combined spectrum, its generation and its window's length (s).

    *peaks* are its ranked peaks (hz, amp) as a recorded sample keeps them,
    *floor_amp_g* the spectrum's floor: they place the sensor's fixed tones.
    """

    generation: int
    spectrum: WindowSpectrum
    window_s: float
    peaks: tuple[tuple[float, float], ...] = ()
    floor_amp_g: float = 0.0


@dataclass(frozen=True, slots=True)
class _Read:
    """One read at a line (or beside it): when, in which speed bin, where, and what it read."""

    t_s: float
    speed_bin: str
    line: LineRead
    hz: float
    reach_hz: float

    def on(self, spans: Sequence[tuple[float, float]]) -> bool:
        """Whether the read reaches a ringing tone or its leak (``_on_tone``)."""
        return _on_tone(spans, self.hz, self.reach_hz)


def _spans(tones: Sequence[RingingTone]) -> tuple[tuple[float, float], ...]:
    """The stretches (Hz) *tones* and their leaks cover, merged where they meet."""
    spans: list[tuple[float, float]] = []
    for low, high in sorted((tone.hz - tone.reach_hz, tone.hz + tone.reach_hz) for tone in tones):
        if spans and low <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], high))
        else:
            spans.append((low, high))
    return tuple(spans)


def _on_tone(spans: Sequence[tuple[float, float]], hz: float, reach_hz: float) -> bool:
    """Whether a band ``hz ± reach_hz`` reaches a span (``RingingTone.takes_in``, any tone)."""
    return any(low - reach_hz <= hz <= high + reach_hz for low, high in spans)


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

    def drop_on(self, spans: Sequence[tuple[float, float]]) -> None:
        """Forget the reads that reach a tone found ringing since they were read."""
        self.reads = deque(read for read in self.reads if not read.on(spans))
        self.controls = deque(read for read in self.controls if not read.on(spans))

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


@dataclass(slots=True)
class _SensorTones:
    """One sensor's latest clear peaks per speed bin, its recent spectra and its ringing tones."""

    # Each speed bin's latest reads' clear peaks (``TONE_SPECTRA_PER_BIN`` each).
    by_bin: dict[int, deque[list[float]]] = field(default_factory=dict)
    # The spectra of the last ``READ_SPAN_S``, which a fixed tone's ringing is judged over.
    spectra: deque[tuple[float, WindowSpectrum]] = field(default_factory=deque)
    fixed: tuple[float, ...] = ()
    # The stretches the ringing tones and their leaks cover (``_spans``).
    spans: tuple[tuple[float, float], ...] = ()
    # The newest spectrum whose peaks are noted.
    generation: int = -1

    def keep(self, now_s: float, spectrum: WindowSpectrum) -> None:
        """Keep a read's spectrum for ``READ_SPAN_S``, which ringing is judged over."""
        self.spectra.append((now_s, spectrum))
        while self.spectra and self.spectra[0][0] < now_s - READ_SPAN_S:
            self.spectra.popleft()

    def note(self, speed_kmh: float | None, live: LiveSpectrum) -> None:
        """Note every new spectrum's clear peaks, as the report has every window's."""
        if live.generation == self.generation:
            return
        self.generation = live.generation
        # As the report: only spectra taken while moving, with peaks, place the tones.
        if speed_kmh is None or speed_kmh <= 0 or not live.peaks:
            return
        speed_bin = tone_speed_bin(speed_kmh)
        peaks = self.by_bin.get(speed_bin)
        if peaks is None:
            peaks = self.by_bin[speed_bin] = deque(maxlen=TONE_SPECTRA_PER_BIN)
        peaks.append(clear_peak_hz(live.peaks, live.floor_amp_g))

    def place(self) -> None:
        self.fixed = tuple(
            sensor_fixed_tones(
                [(speed_bin, peaks) for speed_bin, reads in self.by_bin.items() for peaks in reads]
            )
        )

    def judge(self, groups: Sequence[Sequence[float]], window_s: float) -> None:
        """The car's tone *groups* that ring here over the recent spectra (``ringing``)."""
        kept: list[RingingTone] = []
        for group in groups:
            centre, half_width = (group[0] + group[-1]) / 2.0, (group[-1] - group[0]) / 2.0
            excess: list[float] = []
            flanks: list[float] = []
            t_s: list[float] = []
            for t, spectrum in self.spectra:
                read = spectrum.line_read(centre, half_width)
                if read is not None:
                    excess.append(read.excess)
                    flanks.append(read.flanks)
                    t_s.append(t)
            rings = ringing(excess, flanks, t_s, window_s)
            if rings is not None:
                kept.extend(ringing_tone(group, *rings, self.spectra[-1][1].bin_hz))
        self.spans = _spans(kept)


class OrderHearing:
    """The sensors that hear each live order band, strongest first, over the last few seconds."""

    __slots__ = (
        "_generations",
        "_heard",
        "_next_read_s",
        "_reads",
        "_speed",
        "_tone_turn",
        "_tones",
    )

    def __init__(self) -> None:
        self._reads: dict[tuple[str, str], _Reads] = {}
        self._generations: dict[str, int] = {}
        self._heard: dict[str, list[str]] = {}
        self._tones: dict[str, _SensorTones] = {}
        self._next_read_s = float("-inf")
        self._tone_turn = 0
        self._speed: tuple[float, float] | None = None

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
        """Note each new spectrum's peaks; every ``READ_INTERVAL_S``, read the lines and judge.

        Called on every live payload: the fixed tones are placed from every
        spectrum's peaks, the lines read once a second.
        """
        for client_id, live in spectra.items():
            tones = self._tones.get(client_id)
            if tones is None:
                tones = self._tones[client_id] = _SensorTones()
            tones.note(speed_kmh, live)
        if now_s < self._next_read_s:
            return
        self._next_read_s = now_s + READ_INTERVAL_S
        rate = self._speed_rate(now_s, speed_kmh)
        fresh = {
            client_id: live
            for client_id, live in spectra.items()
            if self._generations.get(client_id) != live.generation
        }
        for client_id, live in fresh.items():
            self._generations[client_id] = live.generation
            self._tones[client_id].keep(now_s, live.spectrum)
        self._place_tones(spectra)
        for client_id, live in fresh.items():
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
        for client_id in [cid for cid in self._tones if cid not in spectra]:
            del self._tones[client_id]
        self._heard = self._judge(speed_bin_label(speed_kmh or 0.0))

    def _place_tones(self, spectra: Mapping[str, LiveSpectrum]) -> None:
        """Place one sensor's fixed tones, in turn, and judge which of the car's ring there.

        One sensor a read keeps each read's work small; each sensor's tones are
        placed and judged again every few seconds. As the report: a tone fixed
        at one sensor is judged at every sensor, whether or not the peak picker
        held it fixed there. Order reads already taken on a tone that now rings
        are forgotten.
        """
        clients = sorted(client_id for client_id in self._tones if client_id in spectra)
        if not clients:
            return
        self._tone_turn = (self._tone_turn + 1) % len(clients)
        client_id = clients[self._tone_turn]
        tones = self._tones[client_id]
        tones.place()
        groups = tone_groups(sorted({hz for other in self._tones.values() for hz in other.fixed}))
        before = tones.spans
        tones.judge(groups, spectra[client_id].window_s)
        if tones.spans and tones.spans != before:
            for (reads_client, _band), reads in self._reads.items():
                if reads_client == client_id:
                    reads.drop_on(tones.spans)

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
        """One read at the band's line, and the two control reads beside it, as the report reads.

        Not where the line, or a control read, reaches a fixed tone ringing at
        the sensor or that tone's leak: the tone's level is no part of the order's.
        """
        spectrum = live.spectrum
        line_hz = band["center_hz"]
        half_width_hz = line_half_width_hz(line_hz, speed_kmh, rate_kmh_per_s, live.window_s)
        reach_hz = line_reach_hz(half_width_hz, spectrum.bin_hz)
        sensor_tones = self._tones.get(client_id)
        spans = sensor_tones.spans if sensor_tones is not None else ()
        if _on_tone(spans, line_hz, reach_hz):
            return
        line = spectrum.line_read(line_hz, half_width_hz)
        if line is None:
            return
        key = (client_id, band["key"])
        reads = self._reads.get(key)
        if reads is None:
            reads = self._reads[key] = _Reads(window_s=live.window_s)
        speed_bin = speed_bin_label(speed_kmh or 0.0)
        reads.reads.append(_Read(now_s, speed_bin, line, line_hz, reach_hz))
        offset_hz = CONTROL_REACHES * reach_hz
        for control_hz in (line_hz - offset_hz, line_hz + offset_hz):
            if _on_tone(spans, control_hz, reach_hz):
                continue
            control = spectrum.line_read(control_hz, half_width_hz)
            if control is not None:
                reads.controls.append(_Read(now_s, speed_bin, control, control_hz, reach_hz))

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
