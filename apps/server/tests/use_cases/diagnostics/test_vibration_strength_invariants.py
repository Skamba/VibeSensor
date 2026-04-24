"""Property-focused invariants for the core vibration-strength dB helpers."""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vibesensor.vibration_strength import (
    compute_db,
    compute_db_or_none,
    relative_level_db_scalar,
    vibration_strength_db_scalar,
)

_MIN_SUBNORMAL = math.nextafter(0.0, 1.0)
_MIN_NORMAL = float(np.finfo(np.float64).tiny)
_EDGE_VALUES = (
    0.0,
    -0.0,
    _MIN_SUBNORMAL,
    _MIN_NORMAL,
    1e-300,
    1e-100,
    1e-12,
    1e-9,
    1.0,
    1e6,
    1e100,
)


def _valid_strength_value_strategy() -> st.SearchStrategy[float]:
    return st.one_of(
        st.sampled_from(_EDGE_VALUES),
        st.floats(
            min_value=0.0,
            max_value=1e12,
            allow_nan=False,
            allow_infinity=False,
            allow_subnormal=True,
            width=64,
        ),
    )


def _epsilon_strategy() -> st.SearchStrategy[float | None]:
    return st.one_of(
        st.none(),
        st.sampled_from((0.0, _MIN_SUBNORMAL, _MIN_NORMAL, 1e-12, 1e-6, 1.0)),
        st.floats(
            min_value=0.0,
            max_value=1e6,
            allow_nan=False,
            allow_infinity=False,
            allow_subnormal=True,
            width=64,
        ),
    )


@settings(deadline=None, max_examples=200)
@given(floor=_valid_strength_value_strategy())
def test_strength_db_scalar_is_zero_when_peak_equals_floor(floor: float) -> None:
    result = vibration_strength_db_scalar(peak_band_rms_amp_g=floor, floor_amp_g=floor)
    assert result == pytest.approx(0.0, abs=1e-12)


@settings(deadline=None, max_examples=200)
@given(
    floor=_valid_strength_value_strategy(),
    peak_pair=st.tuples(_valid_strength_value_strategy(), _valid_strength_value_strategy()).map(
        lambda pair: tuple(sorted(pair))
    ),
)
def test_strength_db_scalar_is_monotonic_in_peak_amplitude(
    floor: float,
    peak_pair: tuple[float, float],
) -> None:
    lower_peak, higher_peak = peak_pair
    lower_db = vibration_strength_db_scalar(
        peak_band_rms_amp_g=lower_peak,
        floor_amp_g=floor,
    )
    higher_db = vibration_strength_db_scalar(
        peak_band_rms_amp_g=higher_peak,
        floor_amp_g=floor,
    )
    assert higher_db >= lower_db


@settings(deadline=None, max_examples=200)
@given(
    peak=_valid_strength_value_strategy(),
    floor_pair=st.tuples(_valid_strength_value_strategy(), _valid_strength_value_strategy()).map(
        lambda pair: tuple(sorted(pair))
    ),
)
def test_strength_db_scalar_is_non_increasing_as_floor_rises(
    peak: float,
    floor_pair: tuple[float, float],
) -> None:
    lower_floor, higher_floor = floor_pair
    low_floor_db = vibration_strength_db_scalar(
        peak_band_rms_amp_g=peak,
        floor_amp_g=lower_floor,
    )
    high_floor_db = vibration_strength_db_scalar(
        peak_band_rms_amp_g=peak,
        floor_amp_g=higher_floor,
    )
    assert high_floor_db <= low_floor_db + 1e-12


@settings(deadline=None, max_examples=200)
@given(
    peak=_valid_strength_value_strategy(),
    floor=_valid_strength_value_strategy(),
    epsilon_g=_epsilon_strategy(),
)
def test_strength_db_scalar_stays_finite_for_extreme_valid_inputs(
    peak: float,
    floor: float,
    epsilon_g: float | None,
) -> None:
    result = vibration_strength_db_scalar(
        peak_band_rms_amp_g=peak,
        floor_amp_g=floor,
        epsilon_g=epsilon_g,
    )
    assert math.isfinite(result)
    assert abs(result) < 5000.0


@pytest.mark.parametrize(
    ("peak", "floor", "expected_sign"),
    [
        pytest.param(-0.0, 0.0, 0, id="negative-zero-equality"),
        pytest.param(_MIN_SUBNORMAL, 0.0, 1, id="subnormal-above-zero-floor"),
        pytest.param(0.0, _MIN_SUBNORMAL, -1, id="zero-below-subnormal-floor"),
        pytest.param(math.nextafter(1.0, 2.0), 1.0, 1, id="nextafter-up-positive"),
        pytest.param(1.0, math.nextafter(1.0, 2.0), -1, id="nextafter-down-negative"),
    ],
)
def test_strength_db_scalar_handles_subnormal_and_boundary_cases(
    peak: float,
    floor: float,
    expected_sign: int,
) -> None:
    result = vibration_strength_db_scalar(peak_band_rms_amp_g=peak, floor_amp_g=floor)
    assert math.isfinite(result)
    if expected_sign == 0:
        assert result == pytest.approx(0.0, abs=1e-12)
    elif expected_sign > 0:
        assert result >= 0.0
    else:
        assert result <= 0.0


@settings(deadline=None, max_examples=200)
@given(peak=_valid_strength_value_strategy(), floor=_valid_strength_value_strategy())
def test_public_db_wrappers_match_scalar_contract(peak: float, floor: float) -> None:
    expected = vibration_strength_db_scalar(
        peak_band_rms_amp_g=peak,
        floor_amp_g=floor,
    )
    assert compute_db(peak, floor) == pytest.approx(expected)
    assert relative_level_db_scalar(level_amp_g=peak, reference_amp_g=floor) == pytest.approx(
        expected
    )
    assert compute_db_or_none(peak, floor) == pytest.approx(expected)


def test_compute_db_or_none_preserves_none_contract() -> None:
    assert compute_db_or_none(None, 0.01) is None
    assert compute_db_or_none(0.01, None) is None
