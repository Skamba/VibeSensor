"""Benchmark comparing numpy pocketfft vs pyFFTW for the processing rfft hot path.

These are opt-in explicit benchmarks (``benchmark_*.py`` filenames are not
collected under the default ``test_*`` pattern). Invoke with::

    pytest apps/server/tests/infra/processing/benchmark_rfft_backend.py \
        --benchmark-only --benchmark-columns=min,mean,median,stddev,rounds

The benchmark mirrors the real processing payload shape: one
``(axes, fft_n)`` window per call, windowed with a Hann window, with the
rfft taken along the sample axis. It covers the FFT size we actually run
in production (``fft_n=2048``, the canonical ``FFT_N`` in
``vibesensor.shared.constants.dsp``) and a wider sweep so the
speedup trend on the target platform (x86_64 GitHub runner today,
aarch64 Raspberry Pi later) is visible.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from vibesensor.infra.processing.fft import _get_rfft_plan

# Representative shapes: always 3 axes (x/y/z); vary fft_n from small-real to
# large-synthetic so the FFTW-vs-pocketfft crossover is visible.
_AXES_COUNT = 3
_FFT_SIZES = (256, 512, 1024, 2048, 4096, 8192)


def _make_inputs(fft_n: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(0xF17_F17)
    block = rng.standard_normal((_AXES_COUNT, fft_n)).astype(np.float32)
    window = np.hanning(fft_n).astype(np.float32)
    return block, window


def _numpy_rfft_call(block: np.ndarray, window: np.ndarray) -> Callable[[], np.ndarray]:
    def _call() -> np.ndarray:
        return np.abs(np.fft.rfft(block * window, axis=1)).astype(np.float32)

    return _call


def _pyfftw_rfft_call(block: np.ndarray, window: np.ndarray) -> Callable[[], np.ndarray]:
    plan = _get_rfft_plan(_AXES_COUNT, block.shape[1])
    # Warm the plan/output buffer so the first measured iteration doesn't pay
    # one-time FFTW_MEASURE cost.
    np.multiply(block, window, out=plan.input_array)
    plan()

    def _call() -> np.ndarray:
        np.multiply(block, window, out=plan.input_array)
        plan()
        return np.abs(plan.output_array)

    return _call


@pytest.mark.benchmark(group="rfft-backend")
@pytest.mark.parametrize("fft_n", _FFT_SIZES)
def test_rfft_numpy_baseline(benchmark, fft_n: int) -> None:
    block, window = _make_inputs(fft_n)
    call = _numpy_rfft_call(block, window)
    benchmark.extra_info["backend"] = "numpy.fft.rfft"
    benchmark.extra_info["fft_n"] = fft_n
    result = benchmark(call)
    assert result.shape == (_AXES_COUNT, fft_n // 2 + 1)


@pytest.mark.benchmark(group="rfft-backend")
@pytest.mark.parametrize("fft_n", _FFT_SIZES)
def test_rfft_pyfftw_planned(benchmark, fft_n: int) -> None:
    block, window = _make_inputs(fft_n)
    call = _pyfftw_rfft_call(block, window)
    benchmark.extra_info["backend"] = "pyfftw.FFTW"
    benchmark.extra_info["fft_n"] = fft_n
    result = benchmark(call)
    assert result.shape == (_AXES_COUNT, fft_n // 2 + 1)


def test_rfft_numerical_equivalence() -> None:
    """Sanity: pyFFTW plan output matches numpy rfft within float32 tolerance."""
    for fft_n in _FFT_SIZES:
        block, window = _make_inputs(fft_n)
        np_result = np.abs(np.fft.rfft(block * window, axis=1)).astype(np.float32)

        plan = _get_rfft_plan(_AXES_COUNT, fft_n)
        np.multiply(block, window, out=plan.input_array)
        plan()
        pf_result = np.abs(plan.output_array)

        np.testing.assert_allclose(np_result, pf_result, rtol=1e-4, atol=1e-4)
