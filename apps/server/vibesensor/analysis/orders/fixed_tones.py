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
from collections.abc import Sequence

from vibesensor.analysis._sample_metrics import _estimate_strength_floor_amp_g
from vibesensor.analysis._types import Sample
from vibesensor.dsp.fixed_tones import (
    RingingTone,
    clear_peak_hz,
    ringing,
    ringing_tone,
    sensor_fixed_tones,
    tone_groups,
    tone_speed_bin,
    tone_width_hz,
)
from vibesensor.dsp.window_spectrum import WindowSpectrum

__all__ = [
    "fixed_tones",
    "ringing_tones",
    "without_fixed_tones",
]


def fixed_tones(
    samples: Sequence[Sample],
    peaks: Sequence[Sequence[tuple[float, float]]],
) -> list[tuple[float, ...]]:
    """The fixed tones (Hz) of each spectrum's sensor (``sensor_fixed_tones``).

    Only spectra taken while moving judge what is fixed; a tone found that way
    is a tone of every spectrum of that sensor.
    """
    by_sensor: dict[str, list[tuple[int, list[float]]]] = defaultdict(list)
    for index, sample in enumerate(samples):
        if sample.speed_kmh is not None and sample.speed_kmh > 0 and peaks[index]:
            floor_amp = _estimate_strength_floor_amp_g(sample) or 0.0
            by_sensor[sample.client_id].append(
                (tone_speed_bin(float(sample.speed_kmh)), clear_peak_hz(peaks[index], floor_amp))
            )
    by_client = {
        sensor: tuple(sensor_fixed_tones(spectra)) for sensor, spectra in by_sensor.items()
    }
    return [by_client.get(sample.client_id, ()) for sample in samples]


def _near_fixed_tone(hz: float, half_width_hz: float, tones: Sequence[float]) -> bool:
    """Whether a band ``hz ± half_width_hz`` takes in one of *tones*."""
    return any(abs(hz - tone) <= half_width_hz + tone_width_hz(tone) for tone in tones)


def without_fixed_tones(
    peaks: Sequence[Sequence[tuple[float, float]]],
    tones: Sequence[Sequence[float]],
) -> list[list[tuple[float, float]]]:
    """Each spectrum's peaks without those at its sensor's fixed tones (``fixed_tones``)."""
    return [
        [(hz, amp) for hz, amp in sample_peaks if not _near_fixed_tone(hz, 0.0, sample_tones)]
        for sample_peaks, sample_tones in zip(peaks, tones, strict=True)
    ]


def ringing_tones(
    samples: Sequence[Sample],
    tones: Sequence[Sequence[float]],
    window_s: float,
) -> list[tuple[RingingTone, ...]]:
    """Each spectrum's sensor's fixed tones that ring as a line, not a broad hump.

    Each run of the car's tones within a tone's width of each other (one
    tone's peaks wandering over neighbouring bins, ``tone_groups``) is read as
    a line over its span in every spectrum of each sensor, as an order is
    (``WindowSpectrum.line_read``), and judged by ``ringing``: it rings at a
    sensor where its reads stand out of their scatter there, whether or not
    the peak picker held it fixed at that sensor. A ringing tone reaches as
    far as its power leaks.
    """
    by_sensor: dict[str, list[tuple[int, WindowSpectrum]]] = defaultdict(list)
    for index, sample in enumerate(samples):
        if sample.spectrum is not None:
            by_sensor[sample.client_id].append((index, sample.spectrum))
    candidates = sorted({tone for spectra in by_sensor.values() for tone in tones[spectra[0][0]]})
    ringing_at: dict[str, tuple[RingingTone, ...]] = {}
    for sensor, spectra in by_sensor.items():
        kept: list[RingingTone] = []
        for group in tone_groups(candidates):
            centre, half_width = (group[0] + group[-1]) / 2.0, (group[-1] - group[0]) / 2.0
            excess: list[float] = []
            flanks: list[float] = []
            t_s: list[float] = []
            for index, spectrum in spectra:
                read = spectrum.line_read(centre, half_width)
                if read is not None:
                    excess.append(read.excess)
                    flanks.append(read.flanks)
                    t = samples[index].t_s
                    t_s.append(t if t is not None else float("nan"))
            rings = ringing(excess, flanks, t_s, window_s)
            if rings is not None:
                kept.extend(ringing_tone(group, *rings, spectra[0][1].bin_hz))
        ringing_at[sensor] = tuple(kept)
    return [ringing_at.get(sample.client_id, ()) for sample in samples]
