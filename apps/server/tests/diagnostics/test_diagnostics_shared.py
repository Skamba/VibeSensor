from __future__ import annotations

from math import inf, nan

from vibesensor.order_bands import (
    build_diagnostic_settings,
    tolerance_for_order,
    vehicle_orders_hz,
)

_DEFAULT_SPEED_MPS = 27.7777777778  # 100 km/h


def _default_settings_and_orders() -> tuple[dict, dict]:
    """Return ``(settings, orders)`` at the default 100 km/h test speed."""
    settings = build_diagnostic_settings({})
    orders = vehicle_orders_hz(speed_mps=_DEFAULT_SPEED_MPS, settings=settings)
    assert orders is not None
    return settings, orders


def test_tolerance_for_order_honors_floor_and_cap() -> None:
    rel = tolerance_for_order(
        6.0,
        5.0,
        0.0,
        min_abs_band_hz=0.5,
        max_band_half_width_pct=8.0,
    )
    # 0.5 Hz absolute minimum at 5 Hz means at least 10% relative, but cap is 8%.
    assert rel == 0.08


def test_vehicle_orders_hz_uses_tire_deflection_factor() -> None:
    """vehicle_orders_hz should compute frequencies with the deflected circumference."""
    from vibesensor.analysis_settings import DEFAULT_ANALYSIS_SETTINGS

    settings_no_deflection = dict(DEFAULT_ANALYSIS_SETTINGS)
    settings_no_deflection["tire_deflection_factor"] = 1.0
    settings_with_deflection = dict(DEFAULT_ANALYSIS_SETTINGS)
    settings_with_deflection["tire_deflection_factor"] = 0.97

    orders_no = vehicle_orders_hz(speed_mps=30.0, settings=settings_no_deflection)
    orders_with = vehicle_orders_hz(speed_mps=30.0, settings=settings_with_deflection)
    assert orders_no is not None and orders_with is not None

    # With deflection (smaller circumference), wheel Hz should be higher.
    assert orders_with["wheel_hz"] > orders_no["wheel_hz"]
    # The ratio should be approximately 1/0.97 ≈ 1.0309
    ratio = orders_with["wheel_hz"] / orders_no["wheel_hz"]
    assert abs(ratio - 1.0 / 0.97) < 1e-6


def test_vehicle_orders_hz_returns_none_for_non_finite_inputs() -> None:
    settings = build_diagnostic_settings({})
    assert vehicle_orders_hz(speed_mps=nan, settings=settings) is None
    assert vehicle_orders_hz(speed_mps=inf, settings=settings) is None
