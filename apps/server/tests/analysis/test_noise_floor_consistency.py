"""Regression tests: live processing and core lib noise floor must agree.

Fixes GitHub issue #297 — duplicate noise floor computation using
different algorithms (numpy percentile vs core-lib pure-Python percentile).
"""

from __future__ import annotations

import numpy as np
import pytest

from vibesensor.processing.fft import noise_floor
from vibesensor.vibration_strength import noise_floor_amp_p20_g

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _core_noise_floor_from_array(arr: np.ndarray) -> float:
    """Replicate the band/finite filtering that _noise_floor does, then call
    the core lib — used as the expected-value oracle.

    For a single non-negative finite value, returns that value directly;
    ``noise_floor_amp_p20_g`` would treat it as DC-only and return 0.0,
    but ``fft.noise_floor`` returns the value itself (no minimum to strip).
    """
    if arr.size == 0:
        return 0.0
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return 0.0
    non_neg = sorted(float(v) for v in finite if v >= 0.0)
    if not non_neg:
        return 0.0
    if len(non_neg) == 1:
        # fft.noise_floor returns the single element directly rather than
        # delegating to noise_floor_amp_p20_g (which returns 0.0 for n=1).
        return non_neg[0]
    return noise_floor_amp_p20_g(
        combined_spectrum_amp_g=non_neg,
    )


# ---------------------------------------------------------------------------
# Parametrised consistency: live == core lib for various array sizes
# ---------------------------------------------------------------------------

_SIZES = [2, 3, 5, 10, 20, 50, 100, 256, 512, 1024]


@pytest.mark.parametrize("n", _SIZES, ids=[f"n={n}" for n in _SIZES])
def test_live_matches_core_random(n: int) -> None:
    """noise_floor must return the same value as the core lib
    noise_floor_amp_p20_g for random spectra of varying length.
    """
    rng = np.random.default_rng(seed=42 + n)
    amps = rng.random(n).astype(np.float32) * 0.05  # realistic g range

    live = noise_floor(amps)
    expected = _core_noise_floor_from_array(amps)

    assert live == pytest.approx(expected, abs=1e-9), f"n={n}: live={live}, core={expected}"


# ---------------------------------------------------------------------------
# Edge cases (parametrised)
# ---------------------------------------------------------------------------


def _realistic_spectrum() -> np.ndarray:
    """Hand-crafted spectrum mimicking a real FFT output."""
    rng = np.random.default_rng(seed=999)
    amps = np.abs(rng.normal(loc=0.001, scale=0.0005, size=512).astype(np.float32))
    amps[50], amps[120], amps[200] = 0.05, 0.08, 0.03
    return amps


_EDGE_CASES: list[tuple[str, np.ndarray, bool]] = [
    ("empty", np.array([], dtype=np.float32), True),
    ("all_nan", np.array([float("nan")] * 5, dtype=np.float32), True),
    ("single_element", np.array([0.042], dtype=np.float32), False),
    ("two_elements", np.array([0.01, 0.05], dtype=np.float32), False),
    ("negatives_filtered", np.array([0.0, -0.01, 0.02, 0.03, 0.04, 0.05], dtype=np.float32), False),
    ("realistic_spectrum", _realistic_spectrum(), False),
]


@pytest.mark.parametrize(
    ("label", "arr", "expect_zero"),
    _EDGE_CASES,
    ids=[c[0] for c in _EDGE_CASES],
)
def test_consistency_edge_cases(label: str, arr: np.ndarray, expect_zero: bool) -> None:
    """noise_floor must agree with core lib on edge-case inputs."""
    live = noise_floor(arr)
    expected = _core_noise_floor_from_array(arr)
    if expect_zero:
        assert live == expected == 0.0
    else:
        assert live == pytest.approx(expected, abs=1e-9)
