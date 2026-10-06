"""The live FFT input filters only the block's tail yet matches filtering the whole window."""

from __future__ import annotations

import numpy as np
import pytest

from vibesensor.dsp.constants import FFT_N, WAVEFORM_BUFFER_SECONDS
from vibesensor.dsp.fft_analysis import medfilt3
from vibesensor.live.compute import _filtered_fft_input
from vibesensor.live.models import FloatArray, MetricsSnapshot
from vibesensor.live.processor import SignalProcessor

_CLIENT_ID = "aabbccddeeff"


def _full_window_reference(snapshot: MetricsSnapshot) -> FloatArray | None:
    """The previous implementation: median-filter the whole time window, keep the FFT tail."""
    fft_block = snapshot.fft_block
    if fft_block is None:
        return None
    if snapshot.time_window.shape[1] >= fft_block.shape[1]:
        return medfilt3(snapshot.time_window)[:, -fft_block.shape[1] :]
    return medfilt3(fft_block)


def _spiky_samples(rng: np.random.Generator, count: int) -> np.ndarray:
    """Raw ADXL-style int16 samples: two tones, noise and isolated transport spikes."""
    t = np.arange(count) / 800.0
    tone = 300.0 * np.sin(2 * np.pi * 37.0 * t) + 120.0 * np.sin(2 * np.pi * 121.0 * t)
    samples = tone[:, None] + rng.normal(0.0, 40.0, size=(count, 3))
    spike_idx = rng.choice(count, size=max(1, count // 50), replace=False)
    samples[spike_idx, rng.integers(0, 3, size=spike_idx.size)] = 4000.0
    return np.clip(np.round(samples), -32768, 32767).astype(np.int16)


def _processor_snapshot(
    *, sample_rate_hz: int, waveform_seconds: int, fft_n: int, samples: np.ndarray
) -> MetricsSnapshot:
    processor = SignalProcessor(
        sample_rate_hz=sample_rate_hz,
        waveform_seconds=waveform_seconds,
        waveform_display_hz=120,
        fft_n=fft_n,
        spectrum_min_hz=5.0,
        spectrum_max_hz=200.0,
        accel_scale_g_per_lsb=1.0 / 256.0,
    )
    # Feed in packet-sized chunks so the ring buffer wraps like it does live.
    for start in range(0, samples.shape[0], 200):
        processor.ingest(_CLIENT_ID, samples[start : start + 200], sample_rate_hz=sample_rate_hz)
    buf = processor._buffers[_CLIENT_ID]
    return processor._snapshot_locked(_CLIENT_ID, buf, sample_rate_hz)


@pytest.mark.parametrize("sample_rate_hz", [400, 800, 1600])
@pytest.mark.parametrize(
    ("waveform_seconds", "fill_samples"),
    [
        pytest.param(WAVEFORM_BUFFER_SECONDS, FFT_N - 1, id="less-than-one-fft-block"),
        pytest.param(WAVEFORM_BUFFER_SECONDS, FFT_N, id="exactly-one-fft-block"),
        pytest.param(WAVEFORM_BUFFER_SECONDS, FFT_N + 1, id="one-sample-of-history"),
        pytest.param(WAVEFORM_BUFFER_SECONDS, 3 * FFT_N + 17, id="partial-window"),
        pytest.param(WAVEFORM_BUFFER_SECONDS, 40_000, id="full-wrapped-window"),
        pytest.param(1, 40_000, id="window-shorter-than-fft-block"),
    ],
)
def test_tail_filter_matches_full_window_filter(
    sample_rate_hz: int, waveform_seconds: int, fill_samples: int
) -> None:
    rng = np.random.default_rng(sample_rate_hz + fill_samples)
    snapshot = _processor_snapshot(
        sample_rate_hz=sample_rate_hz,
        waveform_seconds=waveform_seconds,
        fft_n=FFT_N,
        samples=_spiky_samples(rng, fill_samples),
    )

    expected = _full_window_reference(snapshot)
    actual = _filtered_fft_input(snapshot)

    if expected is None:
        assert actual is None
        return
    assert actual is not None
    assert actual.dtype == expected.dtype
    np.testing.assert_array_equal(actual, expected, strict=True)


@pytest.mark.parametrize("window_samples", [8, 9, 10, 64])
@pytest.mark.parametrize(
    "nan_columns",
    [
        pytest.param((), id="finite"),
        pytest.param((0,), id="nan-in-old-history"),
        pytest.param((-9,), id="nan-just-before-block"),
        pytest.param((-8,), id="nan-at-block-start"),
        pytest.param((-8, -7), id="nan-run-at-block-start"),
        pytest.param((-4, -1), id="nan-inside-and-at-end"),
    ],
)
def test_tail_filter_matches_full_window_filter_around_gaps(
    window_samples: int, nan_columns: tuple[int, ...]
) -> None:
    fft_n = 8
    rng = np.random.default_rng(window_samples)
    time_window = rng.normal(0.0, 1.0, size=(3, window_samples)).astype(np.float32)
    time_window[1, ::5] = 50.0  # isolated spikes
    for column in nan_columns:
        if -window_samples <= column < window_samples:
            time_window[:, column] = np.nan
    snapshot = MetricsSnapshot(
        client_id=_CLIENT_ID,
        sample_rate_hz=800,
        ingest_generation=1,
        time_window=time_window,
        fft_block=time_window[:, -fft_n:],
    )

    np.testing.assert_array_equal(
        _filtered_fft_input(snapshot), _full_window_reference(snapshot), strict=True
    )
