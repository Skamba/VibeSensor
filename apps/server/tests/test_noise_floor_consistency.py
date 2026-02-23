"""Regression tests: live processing and core lib noise floor must agree.

Fixes GitHub issue #297 — duplicate noise floor computation using
different algorithms (numpy percentile vs core-lib pure-Python percentile).
"""

from __future__ import annotations

import numpy as np
import pytest
from vibesensor_core.vibration_strength import noise_floor_amp_p20_g

from vibesensor.processing import SignalProcessor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _core_noise_floor_from_array(arr: np.ndarray) -> float:
    """Replicate the band/finite filtering that _noise_floor does, then call
    the core lib — used as the expected-value oracle."""
    if arr.size == 0:
        return 0.0
    band = arr[1:] if arr.size > 1 else arr
    finite = band[np.isfinite(band)]
    if finite.size == 0:
        return 0.0
    return noise_floor_amp_p20_g(
        combined_spectrum_amp_g=sorted(float(v) for v in finite if v >= 0.0),
    )


# ---------------------------------------------------------------------------
# Parametrised consistency: live == core lib for various array sizes
# ---------------------------------------------------------------------------

_SIZES = [2, 3, 5, 10, 20, 50, 100, 256, 512, 1024]


@pytest.mark.parametrize("n", _SIZES, ids=[f"n={n}" for n in _SIZES])
def test_live_matches_core_random(n: int) -> None:
    """SignalProcessor._noise_floor must return the same value as the core lib
    noise_floor_amp_p20_g for random spectra of varying length."""
    rng = np.random.default_rng(seed=42 + n)
    amps = rng.random(n).astype(np.float32) * 0.05  # realistic g range

    live = SignalProcessor._noise_floor(amps)
    expected = _core_noise_floor_from_array(amps)

    assert live == pytest.approx(expected, abs=1e-9), (
        f"n={n}: live={live}, core={expected}"
    )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_consistency_empty() -> None:
    arr = np.array([], dtype=np.float32)
    assert SignalProcessor._noise_floor(arr) == _core_noise_floor_from_array(arr) == 0.0


def test_consistency_all_nan() -> None:
    arr = np.array([float("nan")] * 5, dtype=np.float32)
    assert SignalProcessor._noise_floor(arr) == _core_noise_floor_from_array(arr) == 0.0


def test_consistency_single_element() -> None:
    arr = np.array([0.042], dtype=np.float32)
    live = SignalProcessor._noise_floor(arr)
    expected = _core_noise_floor_from_array(arr)
    assert live == pytest.approx(expected, abs=1e-9)


def test_consistency_two_elements() -> None:
    arr = np.array([0.01, 0.05], dtype=np.float32)
    live = SignalProcessor._noise_floor(arr)
    expected = _core_noise_floor_from_array(arr)
    assert live == pytest.approx(expected, abs=1e-9)


def test_consistency_with_negatives_filtered() -> None:
    """Negative amplitudes (physically meaningless) should be excluded."""
    arr = np.array([0.0, -0.01, 0.02, 0.03, 0.04, 0.05], dtype=np.float32)
    live = SignalProcessor._noise_floor(arr)
    expected = _core_noise_floor_from_array(arr)
    assert live == pytest.approx(expected, abs=1e-9)


def test_consistency_realistic_spectrum() -> None:
    """Hand-crafted spectrum mimicking a real FFT output."""
    rng = np.random.default_rng(seed=999)
    # Background noise ~0.001g with a few peaks
    amps = rng.normal(loc=0.001, scale=0.0005, size=512).astype(np.float32)
    amps = np.abs(amps)
    # Inject a few peaks
    amps[50] = 0.05
    amps[120] = 0.08
    amps[200] = 0.03

    live = SignalProcessor._noise_floor(amps)
    expected = _core_noise_floor_from_array(amps)
    assert live == pytest.approx(expected, abs=1e-9)
