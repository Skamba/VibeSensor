from __future__ import annotations

import pytest

from vibesensor.shared.analysis_settings_schema import ANALYSIS_SETTINGS_FIELDS
from vibesensor.shared.json_utils import as_float_or_none
from vibesensor.shared.order_bands import (
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
    assert result.tire_width_mm == 285.0
    assert result.rim_in == 21.0


def test_build_diagnostic_settings_override() -> None:
    result = build_diagnostic_settings({"tire_width_mm": 225.0})
    assert result.tire_width_mm == 225.0


def test_build_diagnostic_settings_ignores_unknown() -> None:
    result = build_diagnostic_settings({"unknown_key": 99.0})
    assert not hasattr(result, "unknown_key")


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
    settings = build_diagnostic_settings({})
    assert vehicle_orders_hz(speed_mps=None, settings=settings) is None
    assert vehicle_orders_hz(speed_mps=0.0, settings=settings) is None
    assert vehicle_orders_hz(speed_mps=-1.0, settings=settings) is None


def test_vehicle_orders_with_defaults() -> None:
    result = vehicle_orders_hz(speed_mps=25.0, settings=build_diagnostic_settings({}))
    assert result is not None
    assert result["wheel_hz"] > 0
    assert result["drive_hz"] > 0
    assert result["engine_hz"] > 0
    # drive_hz should be > wheel_hz (final_drive_ratio > 1)
    assert result["drive_hz"] > result["wheel_hz"]


def test_vehicle_orders_bad_tire_returns_none() -> None:
    settings = build_diagnostic_settings({"tire_width_mm": 0.0})
    assert vehicle_orders_hz(speed_mps=25.0, settings=settings) is None


def test_vehicle_orders_bad_ratios_returns_none() -> None:
    settings = build_diagnostic_settings({"final_drive_ratio": 0.0})
    assert vehicle_orders_hz(speed_mps=25.0, settings=settings) is None


def test_vehicle_orders_projects_boundary_settings_into_order_reference_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeSpec:
        def orders_hz_from_speed_mps(self, speed_mps: float | None) -> dict[str, float] | None:
            assert speed_mps == 25.0
            return {
                "wheel_hz": 1.0,
                "drive_hz": 2.0,
                "engine_hz": 3.0,
                "wheel_uncertainty_pct": 0.1,
                "drive_uncertainty_pct": 0.2,
                "engine_uncertainty_pct": 0.3,
            }

    def _fake_from_settings(data: dict[str, object]):
        captured.update(data)
        return _FakeSpec()

    monkeypatch.setattr(
        "vibesensor.shared.order_bands.order_reference_spec_from_snapshot",
        lambda snapshot: _fake_from_settings(
            {key: getattr(snapshot, key) for key in ANALYSIS_SETTINGS_FIELDS}
        ),
    )

    result = vehicle_orders_hz(
        speed_mps=25.0,
        settings=build_diagnostic_settings({"final_drive_ratio": 3.55}),
    )

    assert result == {
        "wheel_hz": 1.0,
        "drive_hz": 2.0,
        "engine_hz": 3.0,
        "wheel_uncertainty_pct": 0.1,
        "drive_uncertainty_pct": 0.2,
        "engine_uncertainty_pct": 0.3,
    }
    assert captured["final_drive_ratio"] == 3.55
    assert captured["tire_width_mm"] == 285.0
