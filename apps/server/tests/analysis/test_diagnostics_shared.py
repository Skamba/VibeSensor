from __future__ import annotations

from math import inf, nan

from vibesensor.analysis.orders._hypothesis_catalog import (
    order_hypothesis_path_compliance_by_key,
)
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.dsp.order_bands import (
    build_diagnostic_settings,
    build_order_bands,
    order_peak_tolerance_hz,
    vehicle_orders_hz,
)

_DEFAULT_SPEED_MPS = 27.7777777778  # 100 km/h


def _default_settings_and_orders() -> tuple[AnalysisSettingsSnapshot, dict[str, float]]:
    """Return ``(settings, orders)`` at the default 100 km/h test speed."""
    settings = build_diagnostic_settings({})
    orders = vehicle_orders_hz(speed_mps=_DEFAULT_SPEED_MPS, settings=settings)
    assert orders is not None
    return settings, orders


def test_order_peak_tolerance_hz_honors_floor_and_compliance() -> None:
    # 0.5 Hz absolute floor dominates at low frequency.
    assert order_peak_tolerance_hz(predicted_hz=5.0, path_compliance=1.0) == 0.5
    # Above the floor: 8% relative, widened by sqrt(path compliance).
    assert order_peak_tolerance_hz(predicted_hz=20.0, path_compliance=1.0) == 20.0 * 0.08
    assert (
        abs(
            order_peak_tolerance_hz(predicted_hz=20.0, path_compliance=1.5) - 20.0 * 0.08 * 1.5**0.5
        )
        < 1e-12
    )


def test_live_order_bands_match_diagnostics_match_window() -> None:
    """Live bands must show exactly the window post-run diagnostics match peaks in."""
    settings = build_diagnostic_settings({})
    for speed_mps in (5.0, _DEFAULT_SPEED_MPS, 40.0):
        orders = vehicle_orders_hz(speed_mps=speed_mps, settings=settings)
        assert orders is not None
        compliance_by_key = order_hypothesis_path_compliance_by_key()
        for band in build_order_bands(orders, settings):
            key = "driveshaft_1x" if band["key"] == "driveshaft_engine_1x" else band["key"]
            expected_half_width_hz = order_peak_tolerance_hz(
                predicted_hz=band["center_hz"],
                path_compliance=compliance_by_key[key],
            )
            half_width_hz = band["center_hz"] * band["tolerance"]
            assert abs(half_width_hz - expected_half_width_hz) < 1e-9, band


def test_vehicle_orders_hz_uses_tire_deflection_factor() -> None:
    """vehicle_orders_hz should compute frequencies with the deflected circumference."""
    settings_no_deflection = build_diagnostic_settings({"tire_deflection_factor": 1.0})
    settings_with_deflection = build_diagnostic_settings({"tire_deflection_factor": 0.97})

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
