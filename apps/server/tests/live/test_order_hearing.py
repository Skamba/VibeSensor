"""Which orders the live spectra hear: the report's line-significance rule over recent reads.

``OrderHearing`` reads each sensor's latest spectrum at every order band's
line once a second and asks the report's question of the last ten seconds'
reads (``dsp/line_significance.py``); these are the properties the simulated
drives cannot isolate.
"""

from __future__ import annotations

import numpy as np

from vibesensor.dsp.fft_analysis import SpectralAnalysisComputer
from vibesensor.live.order_hearing import READ_INTERVAL_S, LiveSpectrum, OrderHearing
from vibesensor.live.payload_types import OrderBandPayload

_FS = 800
_N = 2048
_WINDOW_S = _N / _FS
_T = np.arange(_N) / _FS
_COMPUTER = SpectralAnalysisComputer(fft_n=_N, spectrum_min_hz=5.0, spectrum_max_hz=200.0)


def _band(key: str, center_hz: float) -> OrderBandPayload:
    return {
        "key": key,
        "code": key.upper(),
        "center_hz": center_hz,
        "tolerance": 0.05,
    }


def _spectrum(
    generation: int, rng: np.random.Generator, signal: np.ndarray | None = None
) -> LiveSpectrum:
    block = rng.normal(0.0, 0.002, size=(3, _N))
    if signal is not None:
        block[2] += signal
    spectrum = _COMPUTER.combined_spectrum(block.astype(np.float32), _FS)
    assert spectrum is not None
    return LiveSpectrum(generation=generation, spectrum=spectrum, window_s=_WINDOW_S)


def _tone(hz: float, amp_g: float = 0.01) -> np.ndarray:
    return amp_g * np.sin(2 * np.pi * hz * _T + 0.7 * hz)


def _hump(rng: np.random.Generator, center_hz: float, width_hz: float, amp_g: float) -> np.ndarray:
    """Noise shaped into a resonance several Hz wide: a wheel-hop hump, not a line."""
    spectrum = np.fft.rfft(rng.normal(0.0, 1.0, _N))
    freqs = np.fft.rfftfreq(_N, 1.0 / _FS)
    spectrum *= np.exp(-0.5 * ((freqs - center_hz) / width_hz) ** 2)
    hump = np.fft.irfft(spectrum, _N)
    return amp_g * hump / np.std(hump)


def test_a_line_one_sensor_hears_is_heard_there_alone_strongest_first() -> None:
    rng = np.random.default_rng(5)
    hearing = OrderHearing()
    bands = [_band("wheel_1x", 14.2), _band("engine_2x", 61.0)]
    for step in range(12):
        hearing.update(
            step * READ_INTERVAL_S,
            100.0,
            bands,
            {
                "front-left": _spectrum(step, rng, _tone(14.2, 0.02)),
                "front-right": _spectrum(step, rng, _tone(14.2, 0.006)),
                "rear-left": _spectrum(step, rng),
            },
        )

    assert hearing.heard_at("wheel_1x") == ["front-left", "front-right"]
    assert hearing.heard_at("engine_2x") == []


def test_noise_and_a_wide_hump_in_the_band_are_not_heard() -> None:
    # A healthy wheel's wheel-hop hump sits in the band; its floor rises with it.
    rng = np.random.default_rng(8)
    hearing = OrderHearing()
    bands = [_band("wheel_1x", 14.2), _band("wheel_2x", 28.4), _band("driveshaft_1x", 45.0)]
    for step in range(15):
        hearing.update(
            step * READ_INTERVAL_S,
            100.0,
            bands,
            {
                "front-left": _spectrum(step, rng, _hump(rng, 14.2, 3.0, 0.02)),
                "rear-left": _spectrum(step, rng),
            },
        )
        assert [hearing.heard_at(band["key"]) for band in bands] == [[], [], []]


def test_a_line_is_heard_only_in_the_speed_bin_where_it_stands_clear() -> None:
    # A swept line that passed a body mode, or an order that stopped: the last
    # ten seconds still stand out, but the current speed bin's reads do not.
    rng = np.random.default_rng(13)
    hearing = OrderHearing()
    bands = [_band("wheel_1x", 14.2)]
    heard = []
    for step in range(12):
        speed_kmh, signal = (100.0, _tone(14.2, 0.02)) if step < 9 else (112.0, None)
        hearing.update(
            step * READ_INTERVAL_S, speed_kmh, bands, {"front-left": _spectrum(step, rng, signal)}
        )
        heard.append(bool(hearing.heard_at("wheel_1x")))

    # Five reads place a verdict; it shows once two in a row hear the order.
    assert heard[:9] == [False] * 5 + [True] * 4
    assert heard[9:] == [False] * 3


def test_reads_wait_for_the_interval_and_a_new_spectrum() -> None:
    rng = np.random.default_rng(21)
    hearing = OrderHearing()
    bands = [_band("wheel_1x", 14.2)]
    same = _spectrum(0, rng, _tone(14.2, 0.02))
    # The same spectrum many times over is one read: not enough to judge.
    for step in range(20):
        hearing.update(step * 0.25, 100.0, bands, {"front-left": same})
    assert hearing.heard_at("wheel_1x") == []

    # A sensor that goes away is forgotten.
    for step in range(8):
        hearing.update(
            10.0 + step, 100.0, bands, {"front-left": _spectrum(step + 1, rng, _tone(14.2, 0.02))}
        )
    assert hearing.heard_at("wheel_1x") == ["front-left"]
    hearing.update(30.0, 100.0, bands, {})
    assert hearing.heard_at("wheel_1x") == []
