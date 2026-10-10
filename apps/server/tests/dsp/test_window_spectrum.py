"""Order-tracked reads: one window read at an order's line, and the reads judged per sensor.

Order tracking reads an order's own level at its line in every window and
takes the middle of the reads per sensor (``analysis/orders/tracking.py``);
these are the properties the simulator benchmark cannot isolate.
"""

from __future__ import annotations

import numpy as np
import pytest

from vibesensor.analysis.orders.tracking import TrackedCells
from vibesensor.dsp.fft_analysis import SpectralAnalysisComputer
from vibesensor.dsp.window_spectrum import (
    LineRead,
    WindowSpectrum,
    line_half_width_hz,
    line_reads,
    peak_scale_g,
    tone_line_level_g,
)

_FS = 800
_N = 2048
_T = np.arange(_N) / _FS
_COMPUTER = SpectralAnalysisComputer(fft_n=_N, spectrum_min_hz=5.0, spectrum_max_hz=200.0)


def _spectrum(signal: np.ndarray, rng: np.random.Generator, noise_g: float = 0.002):
    block = rng.normal(0.0, noise_g, size=(3, _N))
    block[2] += signal
    spectrum = _COMPUTER.combined_spectrum(block.astype(np.float32), _FS)
    assert spectrum is not None
    (metrics,) = _COMPUTER.combined_strength_metrics([spectrum], _FS)
    return metrics, spectrum


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


def test_a_faint_tone_on_the_peak_scale_stands_over_the_floor_as_its_peak_does() -> None:
    # A tone near the 8 dB negligible edge, over 80 windows: its level alone
    # reads about 1 dB under its ranked peak, which holds the floor under it
    # too; on the peak's scale it reads as the peak does.
    rng = np.random.default_rng(7)
    levels, peaks, floors = [], [], []
    for index in range(80):
        hz = 31.3 + 0.013 * index
        metrics, spectrum = _spectrum(0.0009 * np.sin(2 * np.pi * hz * _T + index), rng)
        read = spectrum.line_read(hz, 0.0)
        assert read is not None
        levels.append(read.excess)
        peaks.append(next(p["amp"] for p in metrics["top_peaks"] if abs(p["hz"] - hz) < 0.5))
        floors.append(metrics["noise_floor_amp_g"])
    floor = float(np.median(floors))
    level = float(np.sqrt(np.median(levels)))

    def over_floor_db(amp: float) -> float:
        return float(20 * np.log10(amp / floor))

    peak_db = over_floor_db(float(np.mean(peaks)))
    assert 7.5 < peak_db < 8.5
    assert over_floor_db(level) < peak_db - 0.6
    assert over_floor_db(peak_scale_g(level, floor)) == pytest.approx(peak_db, abs=0.3)


def test_broadband_noise_alone_reads_no_level_on_average() -> None:
    rng = np.random.default_rng(5)
    reads = [_spectrum(np.zeros(_N), rng)[1].line_read(31.0, 0.0) for _ in range(200)]

    excess = np.mean([read.excess for read in reads if read is not None])
    flanks = np.mean([read.flanks for read in reads if read is not None])
    assert abs(excess) < 0.1 * flanks


def test_reads_taken_together_are_each_read_bit_for_bit() -> None:
    # Stacked reads keep one read's floating-point order: the drive's verdicts
    # are the same however its reads are taken. Lines across the whole
    # spectrum (both edges, off it), held and swept, on a floor that varies
    # over decades.
    rng = np.random.default_rng(11)
    freq = np.arange(5.0, 200.0, _FS / _N, dtype=np.float32)
    # Two spectra kept together as rows (as the replay keeps them), two on their own.
    rows = (10.0 ** rng.uniform(-5.0, -1.0, (2, freq.size))).astype(np.float32)
    spectra = [
        WindowSpectrum(freq_hz=freq, amp_g=rows[row], rows=rows, row=row) for row in range(2)
    ] + [
        WindowSpectrum(
            freq_hz=freq,
            amp_g=(10.0 ** rng.uniform(-5.0, -1.0, freq.size)).astype(np.float32),
        )
        for _ in range(2)
    ]
    reads = [
        (spectra[index % 4], float(hz), float(half_width))
        for index, (hz, half_width) in enumerate(
            zip(rng.uniform(0.0, 210.0, 3000), rng.choice([0.0, 0.3, 2.0, 9.0], 3000), strict=True)
        )
    ]

    spectra_of = {id(spectrum): index for index, spectrum in enumerate(spectra)}
    excess, flanks, taken = line_reads(
        spectra,
        np.array([spectra_of[id(spectrum)] for spectrum, _hz, _half_width in reads]),
        np.array([hz for _spectrum, hz, _half_width in reads]),
        np.array([half_width for _spectrum, _hz, half_width in reads]),
    )
    together = [
        LineRead(excess=read_excess, flanks=read_flanks) if read else None
        for read_excess, read_flanks, read in zip(excess, flanks, taken, strict=True)
    ]

    assert together == [spectrum.line_read(hz, half_width) for spectrum, hz, half_width in reads]
    assert sum(read is None for read in together) > 100
    assert sum(read is not None for read in together) > 2000


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


def test_a_broad_resonance_under_the_line_reads_almost_no_level() -> None:
    # A body mode 6 Hz wide bends the floor under the line: read over a flat
    # floor it would read 8 % of the floor's power as the order's.
    freq = np.arange(5.0, 200.0, _FS / _N)
    amp = 0.001 + 0.02 / (1.0 + ((freq - 40.0) / 6.0) ** 2)
    spectrum = WindowSpectrum(freq_hz=freq.astype(np.float32), amp_g=amp.astype(np.float32))

    read = spectrum.line_read(40.0, 0.0)

    assert read is not None
    assert abs(read.excess) < 0.01 * read.flanks


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
    # cruising windows at the same speed: over both it reads half its level.
    rng = np.random.default_rng(13)
    cells = TrackedCells(window_s=2.56, braking_alone=True)
    for index in range(10):
        read = LineRead(excess=1e-4 + rng.normal(0.0, 1e-6), flanks=1e-6)
        cells.add(("front_left", "60-70", "braking"), read, 3.0 * index)
    for index in range(30):
        read = LineRead(excess=rng.normal(0.0, 1e-6), flanks=1e-6)
        cells.add(("front_left", "60-70", ""), read, 30 + 3.0 * index)

    (whole,) = cells.sensor_levels({"60-70"})
    (braking,) = cells.sensor_levels({"60-70"}, ("braking",))
    (any_stop,) = cells.sensor_levels((), ("braking",))

    assert braking.level_g == pytest.approx(0.01, rel=0.01)
    assert any_stop == braking
    assert whole.read_g == pytest.approx(0.005, rel=0.01)
    assert braking.floor_g == pytest.approx(0.001)
    assert cells.heard_sensors() == {"front_left"}


def test_a_cell_hears_an_order_only_in_a_driving_phase_its_sensor_hears_it_in() -> None:
    # Brake judder clear through 20 braking windows, absent from 60 cruising
    # ones; the three cruising windows of one speed bin happen to stand
    # clear: that bin does not hear the judder, as the cruising reads do not.
    rng = np.random.default_rng(31)
    cells = TrackedCells(window_s=2.56, braking_alone=True)
    for index in range(20):
        read = LineRead(excess=1e-4 + rng.normal(0.0, 1e-6), flanks=1e-6)
        cells.add(("front_left", "60-70", "braking"), read, 3.0 * index)
    for index in range(57):
        read = LineRead(excess=rng.normal(0.0, 1e-6), flanks=1e-6)
        cells.add(("front_left", ("50-60", "70-80")[index % 2], ""), read, 100 + 3.0 * index)
    for index in range(3):
        cells.add(("front_left", "40-50", ""), LineRead(1e-5, 1e-6), 300 + 3.0 * index)

    assert cells.heard_cells().keys() == {("front_left", "60-70", "braking")}


@pytest.mark.parametrize(("hop_s", "heard"), [(2.56, True), (0.25, False)])
def test_a_level_is_read_only_where_it_stands_out_of_the_reads_scatter(
    hop_s: float, heard: bool
) -> None:
    # Reads scattering by the floor's randomness (0.4 of the floor's power)
    # about a faint order 0.2 of it: over 200 independent windows the order
    # stands out; over 200 windows 0.25 s apart, overlapping so much that they
    # read the floor as about 40 independent ones would, it does not.
    cells = TrackedCells(window_s=2.56)
    for index in range(200):
        excess = 0.2 + 0.4 * (-1) ** index
        cells.add(("rear_left", "90-100", ""), LineRead(excess=excess, flanks=1.0), hop_s * index)

    (level,) = cells.sensor_levels(())

    assert (level.level_g > 0) is heard
    assert level.floor_g == pytest.approx(1.0)


def test_a_few_impacts_do_not_hide_an_order_from_the_sensor_that_hears_it() -> None:
    # An order 4 times the floor's power, read with the floor's own scatter,
    # and 4 of its 44 windows struck by road impacts 400 times it: judged by
    # the spread of all reads the impacts would hide it, by their middle
    # spread they do not, and they do not lift its level.
    rng = np.random.default_rng(17)
    cells = TrackedCells(window_s=2.56)
    for index in range(44):
        excess = 1600.0 if index % 11 == 5 else 4.0 + rng.normal(0.0, 1.0)
        cells.add(("rear_left", "50-60", ""), LineRead(excess, 1.0), 2.56 * index)

    (level,) = cells.sensor_levels(())

    assert level.level_g == pytest.approx(2.0, rel=0.1)


def test_an_order_is_heard_where_it_stands_clear_at_a_sensor_that_hears_it_over_the_drive() -> None:
    # A strong order at one sensor scatters its own reads widely (a line's
    # power beats with the floor under it). Over the drive the sensor hears
    # it, and every speed bin where it stands 6 dB clear of the floor beside
    # it hears it; the speed bin where it fades under that does not. A
    # sensor whose reads scatter about zero hears it nowhere.
    cells = TrackedCells(window_s=2.56)
    for bin_index, middle in enumerate((6.0, 5.0, 4.0, 1.0)):
        speed_bin = f"{60 + 10 * bin_index}-{70 + 10 * bin_index}"
        for index in range(8):
            t_s = 100.0 * bin_index + 2.56 * index
            spread = 3.0 * (-1) ** index
            cells.add(("rear_right", speed_bin, ""), LineRead(middle + spread, 1.0), t_s)
            cells.add(("rear_left", speed_bin, ""), LineRead(0.1 + spread / 4, 1.0), t_s)

    heard = cells.heard_cells()

    assert sorted(key[1] for key in heard) == ["60-70", "70-80", "80-90"]
    assert {key[0] for key in heard} == {"rear_right"}
    assert heard[("rear_right", "60-70", "")].level_g == pytest.approx(np.sqrt(6.0))


def test_an_order_there_part_of_the_drive_reads_its_level_while_there() -> None:
    # A misfire four times the floor's power in the first half of a steady
    # cruise and gone in the second: its level is read over the stretches it
    # is there, not halved by the stretches it is not.
    rng = np.random.default_rng(29)
    cells = TrackedCells(window_s=2.56)
    for index in range(80):
        excess = (4.0 if index < 40 else 0.0) + rng.normal(0.0, 0.5)
        cells.add(("engine_bay", "70-80", ""), LineRead(excess, 1.0), 1.0 * index)

    (level,) = cells.sensor_levels(())

    assert level.level_g == pytest.approx(2.0, rel=0.05)


def test_an_order_is_judged_by_the_floor_scatter_beside_its_line() -> None:
    # A faint order whose reads beat widely with the floor under it (a
    # strong neighbouring line in the same band): judged by its own reads'
    # scatter it is lost, judged by the control reads beside the line, which
    # scatter as the floor alone does, it stands out. The verdict is taken
    # again once the control reads are in.
    cells = TrackedCells(window_s=2.56)
    key = ("front_left", "80-90", "")
    for index in range(60):
        cells.add(key, LineRead(1.0 + 3.0 * (-1) ** index, 1.0), 2.56 * index)

    assert cells.heard_sensors() == set()

    controls = [0.3 * (-1) ** index for index in range(60)]
    cells.add_reads(key, [], [], [], [], controls, [1.0] * len(controls))

    assert cells.heard_sensors() == {"front_left"}


def test_a_sensor_with_too_few_reads_places_no_level() -> None:
    # A sensor that dropped out after two windows reads no level, not a level
    # of 0 that would place the order elsewhere.
    cells = TrackedCells(window_s=2.56)
    for index in range(30):
        cells.add(("rear_left", "60-70", ""), LineRead(4.0, 1.0), 2.56 * index)
    for index in range(1):
        cells.add(("rear_right", "60-70", ""), LineRead(0.0, 1.0), 2.56 * index)

    assert [level.location for level in cells.sensor_levels(())] == ["rear_left"]
