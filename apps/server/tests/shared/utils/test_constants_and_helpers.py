"""Tests for vibesensor.shared.constants and OrderReferenceSpec vehicle dynamics."""

from __future__ import annotations

import pytest

from vibesensor.domain import OrderReferenceSpec
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.shared.constants.analysis import SILENCE_DB
from vibesensor.shared.constants.dsp import PEAK_BANDWIDTH_HZ, PEAK_SEPARATION_HZ
from vibesensor.shared.constants.units import KMH_TO_MPS, MPS_TO_KMH
from vibesensor.shared.order_reference_settings import order_reference_spec_from_mapping

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_mps_kmh_round_trip() -> None:
    assert abs(MPS_TO_KMH * KMH_TO_MPS - 1.0) < 1e-15


def test_kmh_to_mps_value() -> None:
    assert abs(100.0 * KMH_TO_MPS - 27.7778) < 0.001


def test_core_analysis_constants_have_expected_ranges() -> None:
    assert SILENCE_DB < 0
    assert PEAK_BANDWIDTH_HZ > 0
    assert PEAK_SEPARATION_HZ > 0


# ---------------------------------------------------------------------------
# OrderReferenceSpec wheel_hz / engine_hz helpers
# ---------------------------------------------------------------------------


def _make_spec() -> OrderReferenceSpec:
    """Build a spec using default analysis settings."""
    spec = order_reference_spec_from_mapping(AnalysisSettingsSnapshot.DEFAULTS)
    assert spec is not None
    return spec


def test_wheel_hz_from_speed_kmh_basic() -> None:
    spec = _make_spec()
    circ = spec.tire_circumference_m
    result = spec.wheel_hz_from_speed_kmh(100.0)
    assert result is not None
    expected = (100.0 * KMH_TO_MPS) / circ
    assert abs(result - expected) < 1e-9


@pytest.mark.parametrize(
    ("speed", "func"),
    [
        (0.0, "kmh"),
        (-10.0, "kmh"),
        (0.0, "mps"),
    ],
    ids=[
        "kmh-zero-speed",
        "kmh-neg-speed",
        "mps-zero-speed",
    ],
)
def test_wheel_hz_returns_none_for_invalid_input(speed: float, func: str) -> None:
    spec = _make_spec()
    if func == "kmh":
        assert spec.wheel_hz_from_speed_kmh(speed) is None
    else:
        assert spec.wheel_hz(speed) is None


def test_wheel_hz_from_speed_mps_basic() -> None:
    spec = _make_spec()
    circ = spec.tire_circumference_m
    result = spec.wheel_hz(27.78)
    assert result is not None
    assert abs(result - 27.78 / circ) < 1e-9


def test_wheel_hz_mps_kmh_consistency() -> None:
    """Both wheel_hz helpers must agree for the same physical speed."""
    spec = _make_spec()
    speed_kmh = 90.0
    speed_mps = speed_kmh * KMH_TO_MPS
    from_kmh = spec.wheel_hz_from_speed_kmh(speed_kmh)
    from_mps = spec.wheel_hz(speed_mps)
    assert from_kmh is not None
    assert from_mps is not None
    assert abs(from_kmh - from_mps) < 1e-9


# ---------------------------------------------------------------------------
# engine_rpm helper
# ---------------------------------------------------------------------------


def test_engine_rpm_basic() -> None:
    spec = _make_spec()
    wh = spec.wheel_hz(10.0 * spec.tire_circumference_m)
    assert wh is not None
    rpm = spec.engine_rpm_from_wheel_hz(wh)
    assert rpm is not None
