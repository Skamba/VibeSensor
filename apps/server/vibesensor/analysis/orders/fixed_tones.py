"""Fixed-frequency tones: spectral peaks that stay put while the speed changes.

A body or seat resonance, a mirror buzz or an idle-speed engine tone rings at
the same frequency whatever the speed. A road-speed order sweeps past such a
tone, and while its tolerance window holds the tone the matcher lands on it:
the order then borrows the tone's level at every sensor that feels the tone,
and a crossing at a speed the drive lingers at reads as an order of its own.
A peak at a sensor's fixed tone is no evidence for an order that follows the
speed, so the speed-following hypotheses are matched without those peaks.
The rule is shared with the live view (``dsp/fixed_tones.py``); see "Fixed
tones" in ``docs/order_tracking.md``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

import numpy as np
import numpy.typing as npt

from vibesensor.analysis.drive_table import DriveTable
from vibesensor.dsp.fixed_tones import (
    RingingTone,
    ringing,
    ringing_tone,
    sensor_fixed_tones,
    tone_groups,
    tone_speed_bin,
    tone_width_hz,
)
from vibesensor.dsp.line_significance import HEARD_OVER_FLOOR
from vibesensor.dsp.window_spectrum import WindowSpectrum

__all__ = [
    "fixed_tones",
    "ringing_tones",
    "without_fixed_tones",
]


def fixed_tones(table: DriveTable) -> dict[str, tuple[float, ...]]:
    """The fixed tones (Hz) of each sensor (``sensor_fixed_tones``), by client id.

    Only spectra taken while moving judge what is fixed, each by its analysed
    peaks that stand out from its floor (``clear_peak_hz``); a tone found that
    way is a tone of every spectrum of that sensor.
    """
    peak_row = table.peak_row
    # ``clear_peak_hz``: 6 dB over the spectrum's floor (0 where it has none).
    clear = table.peak_amp >= HEARD_OVER_FLOOR * table.floor_or_zero[peak_row]
    clear_hz = table.peak_hz[clear].tolist()
    clear_start = np.zeros(table.size + 1, dtype=np.intp)
    np.cumsum(np.bincount(peak_row[clear], minlength=table.size), out=clear_start[1:])
    judged = np.flatnonzero(table.moving & (np.diff(table.peak_start) > 0))
    by_sensor: dict[int, list[tuple[int, list[float]]]] = defaultdict(list)
    for client, speed_kmh, start, end in zip(
        table.client_of[judged].tolist(),
        table.speed_kmh[judged].tolist(),
        clear_start[judged].tolist(),
        clear_start[judged + 1].tolist(),
        strict=True,
    ):
        by_sensor[client].append((tone_speed_bin(speed_kmh), clear_hz[start:end]))
    return {
        table.clients[client]: tuple(sensor_fixed_tones(spectra))
        for client, spectra in by_sensor.items()
    }


def without_fixed_tones(
    table: DriveTable, tones: Mapping[str, Sequence[float]]
) -> npt.NDArray[np.bool_]:
    """Which analysed peaks are clear of their sensor's fixed tones (``fixed_tones``).

    A peak within a tone's width (``tone_width_hz``) of one is at it.
    """
    clear = np.ones(table.peak_row.size, dtype=np.bool_)
    peak_client = table.client_of[table.peak_row]
    for client, name in enumerate(table.clients):
        at_client = np.flatnonzero(peak_client == client)
        if not at_client.size:
            continue
        hz = table.peak_hz[at_client]
        for tone in tones.get(name, ()):
            clear[at_client[np.abs(hz - tone) <= 0.0 + tone_width_hz(tone)]] = False
    return clear


def ringing_tones(
    table: DriveTable,
    tones: Mapping[str, Sequence[float]],
    window_s: float,
) -> list[tuple[RingingTone, ...]]:
    """Each spectrum's sensor's fixed tones that ring as a line, not a broad hump.

    Each run of the car's tones within a tone's width of each other (one
    tone's peaks wandering over neighbouring bins, ``tone_groups``) is read as
    a line over its span in every spectrum of each sensor, as an order is
    (``WindowSpectrum.line_read``), and judged by ``ringing``: it rings at a
    sensor where its reads stand out of their scatter there, whether or not
    the peak picker held it fixed at that sensor. A ringing tone reaches as
    far as its power leaks. *tones* are each sensor's fixed tones by client id.
    """
    by_sensor: dict[int, list[tuple[float, WindowSpectrum]]] = defaultdict(list)
    for client, time_s, spectrum in zip(
        table.client_of.tolist(), table.t_s.tolist(), table.spectra, strict=True
    ):
        if spectrum is not None:
            by_sensor[client].append((time_s, spectrum))
    candidates = sorted(
        {tone for client in by_sensor for tone in tones.get(table.clients[client], ())}
    )
    ringing_at: list[tuple[RingingTone, ...]] = [()] * len(table.clients)
    for client, spectra in by_sensor.items():
        kept: list[RingingTone] = []
        for group in tone_groups(candidates):
            centre, half_width = (group[0] + group[-1]) / 2.0, (group[-1] - group[0]) / 2.0
            excess: list[float] = []
            flanks: list[float] = []
            t_s: list[float] = []
            for t, spectrum in spectra:
                read = spectrum.line_read(centre, half_width)
                if read is not None:
                    excess.append(read.excess)
                    flanks.append(read.flanks)
                    t_s.append(t)
            rings = ringing(excess, flanks, t_s, window_s)
            if rings is not None:
                kept.extend(ringing_tone(group, *rings, spectra[0][1].bin_hz))
        ringing_at[client] = tuple(kept)
    return [ringing_at[client] for client in table.client_of.tolist()]
