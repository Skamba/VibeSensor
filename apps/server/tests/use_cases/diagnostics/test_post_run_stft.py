from __future__ import annotations

from math import pi

import numpy as np
import pytest

from vibesensor.shared.types.whole_run_analysis import (
    WholeRunWindowDescriptor,
    WholeRunWindowPolicy,
)
from vibesensor.use_cases.diagnostics.post_run_raw_windows import (
    PostRunRawSensorWindow,
    PostRunRawWindow,
    PostRunRawWindowDataQualityFlag,
)
from vibesensor.use_cases.diagnostics.post_run_stft import (
    PostRunStftConfig,
    compute_post_run_dense_stft,
)

_RUN_ID = "run-stft"
_SAMPLE_RATE_HZ = 64
_FFT_N = 64


def _policy() -> WholeRunWindowPolicy:
    return WholeRunWindowPolicy(
        sample_rate_hz=_SAMPLE_RATE_HZ,
        window_size_samples=_FFT_N,
        stride_samples=32,
        overlap_samples=32,
        feature_interval_s=0.5,
    )


def _window_descriptor(index: int = 0) -> WholeRunWindowDescriptor:
    return WholeRunWindowDescriptor.from_policy(
        window_index=index,
        sample_start=index * 32,
        policy=_policy(),
    )


def _tone(freq_hz: float, *, amplitude: float = 1000.0, phase_rad: float = 0.0) -> np.ndarray:
    t = np.arange(_FFT_N, dtype=np.float64) / float(_SAMPLE_RATE_HZ)
    x = np.round(amplitude * np.sin((2.0 * pi * freq_hz * t) + phase_rad)).astype(np.int16)
    return np.stack([x, np.zeros_like(x), np.zeros_like(x)], axis=1)


def _raw_window(
    samples: np.ndarray,
    *,
    window_index: int = 0,
    flags: tuple[PostRunRawWindowDataQualityFlag, ...] = (),
    returned_sample_count: int | None = None,
) -> PostRunRawWindow:
    descriptor = _window_descriptor(window_index)
    sensor = PostRunRawSensorWindow(
        run_id=_RUN_ID,
        client_id="sensor-a",
        location="front_left",
        window=descriptor,
        sample_rate_hz=_SAMPLE_RATE_HZ,
        axis_x_i16=samples[:, 0],
        axis_y_i16=samples[:, 1],
        axis_z_i16=samples[:, 2],
        requested_sample_start=descriptor.sample_start,
        requested_sample_count=descriptor.sample_count,
        returned_sample_start=descriptor.sample_start if samples.size else None,
        returned_sample_count=(
            int(samples.shape[0]) if returned_sample_count is None else returned_sample_count
        ),
        data_quality_flags=flags,
    )
    return PostRunRawWindow(run_id=_RUN_ID, window=descriptor, sensors=(sensor,))


def _dominant_freq(window: PostRunRawWindow) -> float | None:
    result = compute_post_run_dense_stft(
        (window,),
        config=PostRunStftConfig(
            fft_size_samples=_FFT_N,
            spectrum_min_hz=1.0,
            spectrum_max_hz=30.0,
            accel_scale_g_per_lsb=0.001,
        ),
    )
    assert len(result.frames) == 1
    return result.frames[0].dominant_freq_hz


def test_dense_stft_detects_known_single_tone() -> None:
    frame_freq = _dominant_freq(_raw_window(_tone(8.0)))

    assert frame_freq == pytest.approx(8.0, abs=0.25)


def test_dense_stft_orders_two_tone_peaks_by_strength() -> None:
    samples = _tone(7.0, amplitude=1200.0)
    samples[:, 0] += _tone(15.0, amplitude=400.0)[:, 0]

    result = compute_post_run_dense_stft(
        (_raw_window(samples),),
        config=PostRunStftConfig(
            fft_size_samples=_FFT_N,
            spectrum_min_hz=1.0,
            spectrum_max_hz=30.0,
            accel_scale_g_per_lsb=0.001,
        ),
    )

    peaks = result.frames[0].top_peaks
    assert peaks[0]["hz"] == pytest.approx(7.0, abs=0.25)
    assert any(peak["hz"] == pytest.approx(15.0, abs=0.25) for peak in peaks[:4])


def test_dense_stft_tracks_sweep_across_windows() -> None:
    windows = [
        _raw_window(_tone(freq), window_index=index) for index, freq in enumerate((6.0, 9.0, 12.0))
    ]

    result = compute_post_run_dense_stft(
        windows,
        config=PostRunStftConfig(
            fft_size_samples=_FFT_N,
            spectrum_min_hz=1.0,
            spectrum_max_hz=30.0,
            accel_scale_g_per_lsb=0.001,
        ),
    )

    assert [frame.window_index for frame in result.frames] == [0, 1, 2]
    assert [frame.dominant_freq_hz for frame in result.frames] == pytest.approx(
        [6.0, 9.0, 12.0],
        abs=0.25,
    )


def test_dense_stft_handles_silence_with_empty_peaks() -> None:
    samples = np.zeros((_FFT_N, 3), dtype=np.int16)

    result = compute_post_run_dense_stft(
        (_raw_window(samples),),
        config=PostRunStftConfig(fft_size_samples=_FFT_N, accel_scale_g_per_lsb=0.001),
    )

    frame = result.frames[0]
    assert frame.dominant_freq_hz is None
    assert frame.top_peaks == ()
    assert np.allclose(frame.combined_amp_g, 0.0)


def test_dense_stft_keeps_noisy_tone_dominant() -> None:
    rng = np.random.default_rng(42)
    samples = _tone(11.0, amplitude=1000.0)
    noise = rng.normal(0.0, 80.0, size=samples.shape).astype(np.int16)
    samples = (samples + noise).astype(np.int16)

    frame_freq = _dominant_freq(_raw_window(samples))

    assert frame_freq == pytest.approx(11.0, abs=0.5)


def test_dense_stft_marks_partial_windows_without_padding_by_default() -> None:
    partial = _tone(10.0)[:24]

    result = compute_post_run_dense_stft(
        (
            _raw_window(
                partial,
                flags=("partial_window", "missing_samples", "low_sample_count"),
                returned_sample_count=24,
            ),
        ),
        config=PostRunStftConfig(
            fft_size_samples=_FFT_N,
            partial_window_policy="mark",
            accel_scale_g_per_lsb=0.001,
        ),
    )

    assert len(result.frames) == 1
    assert result.frames[0].coverage_state == "partial"
    assert result.frames[0].dominant_freq_hz is None
    assert np.allclose(result.frames[0].combined_amp_g, 0.0)


def test_dense_stft_can_zero_pad_partial_windows_explicitly() -> None:
    partial = _tone(10.0)[:40]

    result = compute_post_run_dense_stft(
        (
            _raw_window(
                partial,
                flags=("partial_window", "missing_samples"),
                returned_sample_count=40,
            ),
        ),
        config=PostRunStftConfig(
            fft_size_samples=_FFT_N,
            partial_window_policy="zero_pad",
            spectrum_min_hz=1.0,
            spectrum_max_hz=30.0,
            accel_scale_g_per_lsb=0.001,
        ),
    )

    frame = result.frames[0]
    assert frame.coverage_state == "partial"
    assert frame.dominant_freq_hz == pytest.approx(10.0, abs=0.75)


def test_dense_stft_rejects_invalid_config() -> None:
    with pytest.raises(ValueError, match="spectrum_max_hz >= spectrum_min_hz"):
        compute_post_run_dense_stft(
            (),
            config=PostRunStftConfig(spectrum_min_hz=20.0, spectrum_max_hz=10.0),
        )
