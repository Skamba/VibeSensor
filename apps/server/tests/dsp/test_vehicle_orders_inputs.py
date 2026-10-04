"""Each order family needs only its own references; measured RPM drives the engine."""

from __future__ import annotations

import pytest
from test_support.core import TEST_CAR_ASPECTS

from vibesensor.dsp.order_bands import build_order_bands, vehicle_orders_hz
from vibesensor.settings.analysis_settings_codec import analysis_settings_snapshot_from_mapping

_TIRE_ONLY = {
    key: value
    for key, value in TEST_CAR_ASPECTS.items()
    if key not in {"final_drive_ratio", "current_gear_ratio"}
}


def _settings(aspects: dict[str, float]):
    return analysis_settings_snapshot_from_mapping(aspects)


@pytest.mark.parametrize("speed_mps", [None, 0.0, -1.0])
def test_no_orders_without_forward_speed(speed_mps: float | None) -> None:
    assert vehicle_orders_hz(speed_mps=speed_mps, settings=_settings(TEST_CAR_ASPECTS)) == {}


def test_tire_only_car_still_gets_wheel_orders() -> None:
    orders = vehicle_orders_hz(speed_mps=25.0, settings=_settings(_TIRE_ONLY))

    assert set(orders) == {"wheel_hz", "wheel_uncertainty_pct"}
    assert [band["key"] for band in build_order_bands(orders)] == ["wheel_1x", "wheel_2x"]


def test_final_drive_without_gear_adds_driveshaft_but_not_engine() -> None:
    aspects = {**_TIRE_ONLY, "final_drive_ratio": TEST_CAR_ASPECTS["final_drive_ratio"]}

    orders = vehicle_orders_hz(speed_mps=25.0, settings=_settings(aspects))

    assert "drive_hz" in orders
    assert "engine_hz" not in orders


def test_measured_rpm_gives_engine_orders_without_ratios() -> None:
    orders = vehicle_orders_hz(
        speed_mps=25.0, settings=_settings(_TIRE_ONLY), measured_engine_rpm=2400.0
    )

    assert orders["engine_hz"] == pytest.approx(40.0)
    assert orders["engine_uncertainty_pct"] == 0.0
    assert "drive_hz" not in orders
    assert {"engine_1x", "engine_2x"} <= {band["key"] for band in build_order_bands(orders)}


def test_measured_rpm_overrides_the_top_gear_estimate() -> None:
    estimated = vehicle_orders_hz(speed_mps=25.0, settings=_settings(TEST_CAR_ASPECTS))
    measured = vehicle_orders_hz(
        speed_mps=25.0, settings=_settings(TEST_CAR_ASPECTS), measured_engine_rpm=3000.0
    )

    assert measured["engine_hz"] == pytest.approx(50.0)
    assert measured["engine_hz"] != pytest.approx(estimated["engine_hz"])
