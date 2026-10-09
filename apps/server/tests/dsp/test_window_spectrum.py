"""Order-tracked reads: one window read at an order's line, and the reads averaged per sensor.

Order tracking reads an order's own level at its line in every window and
averages it over windows (``analysis/orders/tracking.py``); these are the
properties the simulator benchmark cannot isolate.
"""

from __future__ import annotations

import numpy as np
import pytest

from vibesensor.analysis.orders.tracking import TrackedCells, line_half_width_hz
from vibesensor.dsp.fft_analysis import SpectralAnalysisComputer
from vibesensor.dsp.window_spectrum import LineRead, WindowSpectrum, tone_line_level_g

_FS = 800
_N = 2048
_T = np.arange(_N) / _FS
_COMPUTER = SpectralAnalysisComputer(fft_n=_N, spectrum_min_hz=5.0, spectrum_max_hz=200.0)


def _spectrum(signal: np.ndarray, rng: np.random.Generator, noise_g: float = 0.002):
    block = rng.normal(0.0, noise_g, size=(3, _N))
    block[2] += signal
    computed = _COMPUTER.compute_combined_strength_metrics(block.astype(np.float32), _FS)
    assert computed is not None
    return computed


def test_a_steady_tone_reads_its_peak_level() -> None:
    # Over its floor the read is the tone's own share of the level a ranked peak reports.
    rng = np.random.default_rng(3)
    metrics, spectrum = _spectrum(0.05 * np.sin(2 * np.pi * 47.3 * _T), rng)
    read = spectrum.line_read(47.3, 0.0)

    assert read is not None
    peak = metrics["top_peaks"][0]
    assert peak["hz"] == pytest.approx(47.3, abs=0.2)
    assert np.sqrt(read.excess + read.flanks) == pytest.approx(peak["amp"], rel=0.05)
    assert read.excess > 50 * read.flanks


@pytest.mark.parametrize("hz", [23.0, 47.3])
def test_a_tone_on_one_axis_reads_the_level_its_peak_amplitude_gives(hz: float) -> None:
    # The felt ranking turns workshop limits (a tone's peak on one axis) into reads.
    rng = np.random.default_rng(11)
    _metrics, spectrum = _spectrum(0.03 * np.sin(2 * np.pi * hz * _T), rng)
    read = spectrum.line_read(hz, 0.0)

    assert read is not None
    assert np.sqrt(read.excess) == pytest.approx(tone_line_level_g(0.03, _FS / _N), rel=0.05)


def test_broadband_noise_alone_reads_no_level_on_average() -> None:
    rng = np.random.default_rng(5)
    reads = [_spectrum(np.zeros(_N), rng)[1].line_read(31.0, 0.0) for _ in range(200)]

    excess = np.mean([read.excess for read in reads if read is not None])
    flanks = np.mean([read.flanks for read in reads if read is not None])
    assert abs(excess) < 0.1 * flanks


def test_a_line_swept_by_a_speed_change_reads_its_whole_sweep() -> None:
    # Braking from 100 km/h at 5 m/s² (18 km/h per s) sweeps a 45 Hz order
    # ±10 Hz within the window: read over the sweep, it holds the steady
    # tone's level; read at the centre alone, a quarter of it.
    rng = np.random.default_rng(7)
    rate_kmh_per_s, speed_kmh, centre_hz = -18.0, 100.0, 45.0
    hz = centre_hz * (1.0 + rate_kmh_per_s * (_T - _T.mean()) / speed_kmh)
    phase = 2 * np.pi * np.cumsum(hz) / _FS
    _metrics, swept = _spectrum(0.05 * np.sin(phase), rng)
    _metrics, steady = _spectrum(0.05 * np.sin(2 * np.pi * centre_hz * _T), rng)
    half_width = line_half_width_hz(centre_hz, speed_kmh, rate_kmh_per_s, _N / _FS)

    over_sweep = swept.line_read(centre_hz, half_width)
    at_centre = swept.line_read(centre_hz, 0.0)
    held = steady.line_read(centre_hz, 0.0)

    assert over_sweep is not None and at_centre is not None and held is not None
    assert over_sweep.excess == pytest.approx(held.excess, rel=0.2)
    assert at_centre.excess < 0.5 * held.excess


def test_a_line_at_the_edge_of_the_spectrum_reads_the_flank_it_has() -> None:
    freq = np.arange(5.0, 200.0, _FS / _N, dtype=np.float32)
    amp = np.full(freq.shape, 0.001, dtype=np.float32)
    amp[np.argmin(np.abs(freq - 6.6))] = 0.03
    spectrum = WindowSpectrum(freq_hz=freq, amp_g=amp)

    read = spectrum.line_read(6.6, 0.0)

    assert read is not None
    assert read.flanks == pytest.approx(0.001**2, rel=1e-3)
    assert spectrum.line_read(5.4, 0.0) is None


def test_an_order_heard_only_while_braking_reads_its_level_over_the_stops_alone() -> None:
    # Brake judder at one sensor through 10 braking windows, absent from the 30
    # cruising windows at the same speed: averaged over both it reads half its level.
    cells = TrackedCells(window_s=2.56)
    for index in range(10):
        cells.add(("front_left", "60-70", True), LineRead(excess=1e-4, flanks=1e-6), 3.0 * index)
    for index in range(30):
        cells.add(
            ("front_left", "60-70", False), LineRead(excess=0.0, flanks=1e-6), 30 + 3.0 * index
        )

    (whole,) = cells.sensor_levels({("60-70", True), ("60-70", False)})
    (braking,) = cells.sensor_levels({("60-70", True)}, braking_only=True)
    (any_stop,) = cells.sensor_levels((), braking_only=True)

    assert braking.level_g == pytest.approx(0.01)
    assert any_stop == braking
    assert whole.level_g == pytest.approx(0.005)
    assert braking.floor_g == pytest.approx(0.001)


@pytest.mark.parametrize(("hop_s", "heard"), [(2.56, True), (0.25, False)])
def test_a_level_is_read_only_where_it_stands_out_of_the_reads_scatter(
    hop_s: float, heard: bool
) -> None:
    # Reads scattering by the floor's randomness (0.4 of the floor's power)
    # about a faint order 0.1 of it: over 200 independent windows the order
    # stands out; over 200 windows 0.25 s apart, overlapping so much that they
    # read the floor as about 40 independent ones would, it does not.
    cells = TrackedCells(window_s=2.56)
    for index in range(200):
        excess = 0.1 + 0.4 * (-1) ** index
        cells.add(
            ("rear_left", "90-100", False), LineRead(excess=excess, flanks=1.0), hop_s * index
        )

    (level,) = cells.sensor_levels(())

    assert (level.level_g > 0) is heard
    assert level.floor_g == pytest.approx(1.0)
