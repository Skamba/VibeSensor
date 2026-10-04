"""Tire and order references refuse invalid inputs instead of producing wrong frequencies."""

from __future__ import annotations

from math import inf, nan

import pytest
from test_support.core import TEST_CAR_ASPECTS

from vibesensor.domain.car import Car
from vibesensor.domain.order_reference import OrderReferenceSpec
from vibesensor.domain.tire_spec import AxleTireSetup, TireSpec
from vibesensor.settings.order_reference_settings import order_reference_spec_from_mapping

_D = {"tire_width_mm": 285.0, "tire_aspect_pct": 30.0, "rim_in": 21.0}


@pytest.mark.parametrize(
    "aspects",
    [
        pytest.param({"tire_aspect_pct": 30.0, "rim_in": 21.0}, id="missing-width"),
        pytest.param({"tire_width_mm": 285.0, "rim_in": 21.0}, id="missing-aspect"),
        pytest.param({"tire_width_mm": 285.0, "tire_aspect_pct": 30.0}, id="missing-rim"),
        pytest.param({**_D, "tire_width_mm": 0}, id="zero-width"),
        pytest.param({**_D, "tire_aspect_pct": 0}, id="zero-aspect"),
        pytest.param({**_D, "rim_in": 0}, id="zero-rim"),
        pytest.param({**_D, "tire_width_mm": -1}, id="negative-width"),
        pytest.param({**_D, "tire_width_mm": nan}, id="nan-width"),
        pytest.param({**_D, "tire_aspect_pct": inf}, id="inf-aspect"),
    ],
)
def test_tire_spec_from_aspects_rejects_invalid_inputs(aspects: dict[str, float]) -> None:
    assert TireSpec.from_aspects(aspects) is None


def test_car_tire_circumference_no_aspects_returns_none() -> None:
    """Car.tire_circumference_m returns None when car has no tire aspects."""
    car = Car(name="No Tires")
    assert car.tire_circumference_m is None


def _default_spec() -> OrderReferenceSpec:
    spec = order_reference_spec_from_mapping(TEST_CAR_ASPECTS)
    assert spec is not None
    return spec


def test_engine_rpm_from_wheel_hz_non_finite_inputs_return_none() -> None:
    """Non-finite inputs must return None to avoid propagating nan/inf."""
    spec = _default_spec()
    assert spec.engine_rpm_from_wheel_hz(float("nan")) is None
    assert spec.engine_rpm_from_wheel_hz(float("inf")) is None


def test_engine_hz_returns_none_without_gear() -> None:
    """engine_hz returns None when gear ratio is zero."""
    tire = TireSpec(width_mm=285.0, aspect_pct=30.0, rim_in=21.0)
    spec = OrderReferenceSpec(
        tire_setup=AxleTireSetup.square(tire),
        final_drive_ratio=3.08,
        current_gear_ratio=0.0,
        speed_uncertainty_pct=1.0,
        tire_diameter_uncertainty_pct=1.0,
        final_drive_uncertainty_pct=0.1,
        gear_uncertainty_pct=0.2,
    )
    assert spec.engine_hz(10.0) is None


def test_engine_rpm_from_wheel_hz_zero_wheel_hz_returns_zero() -> None:
    """Zero wheel Hz (stopped vehicle) must return 0.0, not None."""
    spec = _default_spec()
    result = spec.engine_rpm_from_wheel_hz(0.0)
    assert result == 0.0
