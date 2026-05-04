"""Opt-in benchmark for dense post-run STFT over POSTRUN-01 window DTOs."""

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
)
from vibesensor.use_cases.diagnostics.post_run_stft import (
    PostRunStftConfig,
    compute_post_run_dense_stft,
)

_SAMPLE_RATE_HZ = 800
_FFT_N = 2048
_DURATION_S = 30 * 60
_SENSOR_COUNT = 4
_STRIDE_SAMPLES = 800
_WINDOW_COUNT = ((_SAMPLE_RATE_HZ * _DURATION_S) - _FFT_N) // _STRIDE_SAMPLES + 1


@pytest.fixture(scope="session")
def dense_stft_windows() -> tuple[PostRunRawWindow, ...]:
    policy = WholeRunWindowPolicy(
        sample_rate_hz=_SAMPLE_RATE_HZ,
        window_size_samples=_FFT_N,
        stride_samples=_STRIDE_SAMPLES,
        overlap_samples=_FFT_N - _STRIDE_SAMPLES,
        feature_interval_s=float(_STRIDE_SAMPLES) / float(_SAMPLE_RATE_HZ),
    )
    base_t = np.arange(_FFT_N, dtype=np.float64) / float(_SAMPLE_RATE_HZ)
    windows: list[PostRunRawWindow] = []
    for window_index in range(_WINDOW_COUNT):
        descriptor = WholeRunWindowDescriptor.from_policy(
            window_index=window_index,
            sample_start=window_index * _STRIDE_SAMPLES,
            policy=policy,
        )
        sensors: list[PostRunRawSensorWindow] = []
        for sensor_index in range(_SENSOR_COUNT):
            freq_hz = 18.0 + (sensor_index * 7.0) + (window_index % 11)
            x = np.round(
                900.0 * np.sin((2.0 * pi * freq_hz * base_t) + (sensor_index * 0.2))
            ).astype(np.int16)
            y = np.round(500.0 * np.sin(2.0 * pi * (freq_hz + 3.0) * base_t)).astype(np.int16)
            z = np.round(250.0 * np.sin(2.0 * pi * (freq_hz * 0.5) * base_t)).astype(np.int16)
            sensors.append(
                PostRunRawSensorWindow(
                    run_id="run-stft-benchmark",
                    client_id=f"sensor-{sensor_index:02d}",
                    location=f"location-{sensor_index}",
                    window=descriptor,
                    sample_rate_hz=_SAMPLE_RATE_HZ,
                    axis_x_i16=x,
                    axis_y_i16=y,
                    axis_z_i16=z,
                    requested_sample_start=descriptor.sample_start,
                    requested_sample_count=descriptor.sample_count,
                    returned_sample_start=descriptor.sample_start,
                    returned_sample_count=descriptor.sample_count,
                    data_quality_flags=(),
                )
            )
        windows.append(
            PostRunRawWindow(
                run_id="run-stft-benchmark",
                window=descriptor,
                sensors=tuple(sensors),
            )
        )
    return tuple(windows)


@pytest.mark.benchmark(group="post-run-dense-stft")
def test_post_run_dense_stft_benchmark(benchmark, dense_stft_windows) -> None:
    config = PostRunStftConfig(
        fft_size_samples=_FFT_N,
        spectrum_min_hz=1.0,
        spectrum_max_hz=250.0,
        accel_scale_g_per_lsb=0.001,
    )

    benchmark.extra_info["duration_s"] = _DURATION_S
    benchmark.extra_info["sensor_count"] = _SENSOR_COUNT
    benchmark.extra_info["window_count"] = len(dense_stft_windows)
    result = benchmark.pedantic(
        compute_post_run_dense_stft,
        args=(dense_stft_windows,),
        kwargs={"config": config},
        iterations=1,
        rounds=1,
        warmup_rounds=0,
    )

    assert len(result.frames) == len(dense_stft_windows) * _SENSOR_COUNT
