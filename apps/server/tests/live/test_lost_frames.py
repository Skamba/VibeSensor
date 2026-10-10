"""A frame lost on the way keeps its time in the live FFT block.

The spectrum of a sensor that lost frames must describe the time it is stamped
with (its analysis time range): the signal of that span, at its frequencies and
levels, and nothing from before it.
"""

from __future__ import annotations

from collections.abc import Callable, Collection

import numpy as np
import pytest

from vibesensor.dsp.constants import FFT_N, SAMPLE_RATE_HZ
from vibesensor.dsp.fft_analysis import SpectralAnalysisComputer
from vibesensor.live.processor import SignalProcessor

_CLIENT_ID = "aabbccddeeff"
_FRAME_SAMPLES = 200
_FRAME_US = _FRAME_SAMPLES * 1_000_000 // SAMPLE_RATE_HZ
_T0_US = 50_000_000
_BIN_HZ = SAMPLE_RATE_HZ / FFT_N

type Signal = Callable[[np.ndarray], np.ndarray]


def _samples(signal: Signal, *, frames: int) -> np.ndarray:
    """*frames* frames of ``signal(t_s)`` plus a little noise (g, z on top of gravity)."""
    t_s = np.arange(frames * _FRAME_SAMPLES) / SAMPLE_RATE_HZ
    vibration = signal(t_s) + 0.002 * np.random.default_rng(0).standard_normal(t_s.size)
    samples = np.column_stack([0.3 * vibration, 0.3 * vibration, 1.0 + vibration])
    return samples.astype(np.float32)


def _stream(signal: Signal, *, frames: int, lost: Collection[int] = ()) -> SignalProcessor:
    """Send *frames* stamped frames of ``_samples(signal)``, losing *lost*."""
    processor = SignalProcessor(
        sample_rate_hz=SAMPLE_RATE_HZ,
        waveform_seconds=8,
        waveform_display_hz=120,
        fft_n=FFT_N,
        spectrum_min_hz=5.0,
        spectrum_max_hz=200.0,
    )
    samples = _samples(signal, frames=frames)
    for index in range(frames):
        if index in lost:
            continue
        processor.ingest(
            _CLIENT_ID,
            samples[index * _FRAME_SAMPLES : (index + 1) * _FRAME_SAMPLES],
            sample_rate_hz=SAMPLE_RATE_HZ,
            t0_us=_T0_US + index * _FRAME_US,
        )
    processor.compute_metrics(_CLIENT_ID)
    return processor


def _peaks(processor: SignalProcessor) -> list[tuple[float, float]]:
    combined = processor.latest_metrics(_CLIENT_ID)["combined"]
    return [(peak["hz"], peak["amp"]) for peak in combined["peaks"]]


def _peak_near(processor: SignalProcessor, hz: float) -> tuple[float, float] | None:
    near = [peak for peak in _peaks(processor) if abs(peak[0] - hz) <= 2 * _BIN_HZ]
    return max(near, key=lambda peak: peak[1], default=None)


def test_spectrum_holds_nothing_from_before_its_time_range() -> None:
    # A 40 Hz shake that stops 50 ms before the last FFT block starts, over a
    # steady 15 Hz hum. Losing two frames inside the block must not pull the
    # shake back into it.
    frames = 30
    block_start_s = frames * _FRAME_SAMPLES / SAMPLE_RATE_HZ - FFT_N / SAMPLE_RATE_HZ
    stop_s = block_start_s - 0.05

    def shake(t_s: np.ndarray) -> np.ndarray:
        hum = 0.02 * np.sin(2 * np.pi * 15.0 * t_s)
        return hum + np.where(t_s < stop_s, 0.05 * np.sin(2 * np.pi * 40.0 * t_s), 0.0)

    processor = _stream(shake, frames=frames, lost={22, 23})

    time_range = processor.latest_analysis_time_range(_CLIENT_ID)
    assert time_range is not None
    assert time_range.start_s - _T0_US / 1e6 == pytest.approx(block_start_s)
    assert time_range.end_s - time_range.start_s == pytest.approx(FFT_N / SAMPLE_RATE_HZ)
    assert _peak_near(processor, 15.0) is not None, _peaks(processor)
    assert _peak_near(processor, 40.0) is None, _peaks(processor)


def test_tone_keeps_frequency_and_level_across_lost_frames() -> None:
    # Two lost frames put 0.5 s between the samples either side of the gap: a
    # 27 Hz tone is half a cycle further on there, out of phase with the
    # samples before the gap if they were stacked against those after it.
    def tone(t_s: np.ndarray) -> np.ndarray:
        return 0.02 * np.sin(2 * np.pi * 27.0 * t_s)

    clean = _peak_near(_stream(tone, frames=30), 27.0)
    lossy = _peak_near(_stream(tone, frames=30, lost={23, 24}), 27.0)

    assert clean is not None and lossy is not None
    assert lossy[0] == pytest.approx(clean[0], abs=_BIN_HZ / 2)
    assert lossy[1] == pytest.approx(clean[1], rel=0.15)


def test_lossy_spectrum_reads_the_noise_floor_the_raw_replay_reads() -> None:
    # A sensor that lost frames keeps its live rows where the post-stop raw
    # replay has no complete window, so its floor must be the replay's: a floor
    # read lower raises everything above it, ordinary road noise included.
    def hum(t_s: np.ndarray) -> np.ndarray:
        return 0.005 * np.sin(2 * np.pi * 15.0 * t_s)

    replay = SpectralAnalysisComputer(fft_n=FFT_N, spectrum_min_hz=5.0, spectrum_max_hz=200.0)
    spectrum = replay.combined_spectrum(_samples(hum, frames=30)[-FFT_N:].T, SAMPLE_RATE_HZ)
    assert spectrum is not None
    (replayed,) = replay.combined_strength_metrics([spectrum], SAMPLE_RATE_HZ)

    def live_floor(lost: set[int]) -> float:
        combined = _stream(hum, frames=30, lost=lost).latest_metrics(_CLIENT_ID)["combined"]
        return combined["strength_metrics"]["noise_floor_amp_g"]

    assert live_floor(set()) == pytest.approx(replayed["noise_floor_amp_g"], rel=1e-4)
    lossy_db = 20 * np.log10(live_floor({22, 23}) / replayed["noise_floor_amp_g"])
    assert abs(lossy_db) < 0.5


def test_mostly_lost_block_has_no_spectrum() -> None:
    def tone(t_s: np.ndarray) -> np.ndarray:
        return 0.02 * np.sin(2 * np.pi * 27.0 * t_s)

    processor = _stream(tone, frames=30, lost=set(range(21, 28)))

    assert _peaks(processor) == []
    time_range = processor.latest_analysis_time_range(_CLIENT_ID)
    assert time_range is not None
    assert time_range.end_s - _T0_US / 1e6 == pytest.approx(30 * _FRAME_US / 1e6)


@pytest.mark.parametrize(
    ("lost", "moves"),
    [
        pytest.param(set(), 0, id="none-lost"),
        pytest.param({26, 27}, -1, id="late-frames-lost"),
        pytest.param({22, 23}, 1, id="early-frames-lost"),
    ],
)
def test_spectrum_time_is_where_its_samples_present_weigh_in(lost: set[int], moves: int) -> None:
    # A sweeping tone: its peak sits at its frequency at the spectrum's time,
    # which lost frames pull away from the block's middle (speed is read there).
    def tone(t_s: np.ndarray) -> np.ndarray:
        return 0.02 * np.sin(2 * np.pi * 27.0 * t_s)

    processor = _stream(tone, frames=30, lost=lost)

    time_range = processor.latest_analysis_time_range(_CLIENT_ID)
    assert time_range is not None
    middle_s = (time_range.start_s + time_range.end_s) / 2
    shift_s = time_range.centre_s - middle_s
    if moves == 0:
        assert shift_s == pytest.approx(0.0, abs=1e-9)
    else:
        assert 0.1 < moves * shift_s < 0.5
