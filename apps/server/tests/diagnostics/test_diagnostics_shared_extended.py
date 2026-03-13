from __future__ import annotations

from vibesensor.json_utils import as_float_or_none
from vibesensor.order_bands import (
    build_diagnostic_settings,
    combined_relative_uncertainty,
    tolerance_for_order,
    vehicle_orders_hz,
)

# -- _as_float NaN/edge cases -------------------------------------------------


def test_as_float_nan_returns_none() -> None:
    assert as_float_or_none(float("nan")) is None


def test_as_float_inf_returns_none() -> None:
    # Canonical as_float_or_none rejects both NaN and Inf.
    result = as_float_or_none(float("inf"))
    assert result is None
    result_neg = as_float_or_none(float("-inf"))
    assert result_neg is None


def test_as_float_non_convertible() -> None:
    assert as_float_or_none(object()) is None
    assert as_float_or_none([1, 2]) is None


# -- build_diagnostic_settings ------------------------------------------------


def test_build_diagnostic_settings_defaults() -> None:
    result = build_diagnostic_settings(None)
    assert result["tire_width_mm"] == 285.0
    assert result["rim_in"] == 21.0


def test_build_diagnostic_settings_override() -> None:
    result = build_diagnostic_settings({"tire_width_mm": 225.0})
    assert result["tire_width_mm"] == 225.0


def test_build_diagnostic_settings_ignores_unknown() -> None:
    result = build_diagnostic_settings({"unknown_key": 99.0})
    assert "unknown_key" not in result


# -- combined_relative_uncertainty ---------------------------------------------


def test_combined_uncertainty_zero() -> None:
    assert combined_relative_uncertainty(0.0, 0.0) == 0.0


def test_combined_uncertainty_single() -> None:
    assert abs(combined_relative_uncertainty(3.0) - 3.0) < 1e-9


def test_combined_uncertainty_negative_ignored() -> None:
    assert combined_relative_uncertainty(-1.0, 3.0) == 3.0


# -- tolerance_for_order -------------------------------------------------------


def test_tolerance_for_order_zero_hz() -> None:
    result = tolerance_for_order(
        6.0,
        0.0,
        0.01,
        min_abs_band_hz=0.4,
        max_band_half_width_pct=8.0,
    )
    assert result == 0.0


def test_tolerance_for_order_basic() -> None:
    result = tolerance_for_order(6.0, 10.0, 0.01, min_abs_band_hz=0.4, max_band_half_width_pct=8.0)
    assert 0 < result < 0.08


# -- vehicle_orders_hz --------------------------------------------------------


def test_vehicle_orders_no_speed() -> None:
    assert vehicle_orders_hz(speed_mps=None, settings={}) is None
    assert vehicle_orders_hz(speed_mps=0.0, settings={}) is None
    assert vehicle_orders_hz(speed_mps=-1.0, settings={}) is None


def test_vehicle_orders_with_defaults() -> None:
    result = vehicle_orders_hz(speed_mps=25.0, settings={})
    assert result is not None
    assert result["wheel_hz"] > 0
    assert result["drive_hz"] > 0
    assert result["engine_hz"] > 0
    # drive_hz should be > wheel_hz (final_drive_ratio > 1)
    assert result["drive_hz"] > result["wheel_hz"]


def test_vehicle_orders_bad_tire_returns_none() -> None:
    settings = {"tire_width_mm": 0.0}
    assert vehicle_orders_hz(speed_mps=25.0, settings=settings) is None


def test_vehicle_orders_bad_ratios_returns_none() -> None:
    settings = {"final_drive_ratio": 0.0}
    assert vehicle_orders_hz(speed_mps=25.0, settings=settings) is None
