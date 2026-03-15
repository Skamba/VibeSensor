from __future__ import annotations

from math import pi

import pytest

from vibesensor.use_cases.diagnostics.order_bands import (
    build_diagnostic_settings,
    vehicle_orders_hz,
)
from vibesensor.shared.constants import KMH_TO_MPS

"""
Common-cause cases are based on recurring issues documented in:
- Firestone: https://www.firestonecompleteautocare.com/blog/maintenance/why-is-my-car-shaking/
- AA1Car wheel/tire vibration: https://www.aa1car.com/library/wheel_balancing.htm
- AA1Car driveline vibration: https://www.aa1car.com/library/vibrations.htm
- AA1Car brake pulsation/vibration: https://www.aa1car.com/library/brake_pedal_pulsates.htm
"""


SPEED_KMH = 100.0
SPEED_MPS = SPEED_KMH * KMH_TO_MPS


def _default_orders() -> tuple[dict[str, float], dict[str, float]]:
    settings = build_diagnostic_settings({})
    orders = vehicle_orders_hz(speed_mps=SPEED_MPS, settings=settings)
    assert orders is not None
    return settings, orders


def test_default_100_kmh_order_calculation_matches_vehicle_spec() -> None:
    settings, orders = _default_orders()

    # Independent manual calculation from default tire and drivetrain values.
    sidewall_mm = settings["tire_width_mm"] * (settings["tire_aspect_pct"] / 100.0)
    diameter_m = ((settings["rim_in"] * 25.4) + (2.0 * sidewall_mm)) / 1000.0
    circumference_m = pi * diameter_m * settings["tire_deflection_factor"]
    wheel_hz_manual = SPEED_MPS / circumference_m
    drive_hz_manual = wheel_hz_manual * settings["final_drive_ratio"]
    engine_hz_manual = drive_hz_manual * settings["current_gear_ratio"]

    assert orders["wheel_hz"] == pytest.approx(wheel_hz_manual, rel=1e-6)
    assert orders["drive_hz"] == pytest.approx(drive_hz_manual, rel=1e-6)
    assert orders["engine_hz"] == pytest.approx(engine_hz_manual, rel=1e-6)

    # Sanity anchors for regression readability at 100 km/h defaults with 0.97 deflection.
    assert orders["wheel_hz"] == pytest.approx(12.9407, rel=1e-4)
    assert orders["drive_hz"] == pytest.approx(39.8572, rel=1e-4)
    assert orders["engine_hz"] == pytest.approx(25.5086, rel=1e-4)
