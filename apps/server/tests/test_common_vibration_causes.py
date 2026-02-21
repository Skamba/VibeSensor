from __future__ import annotations

from dataclasses import dataclass
from math import pi

import pytest

from vibesensor.constants import KMH_TO_MPS
from vibesensor.diagnostics_shared import (
    build_diagnostic_settings,
    classify_peak_hz,
    tolerance_for_order,
    vehicle_orders_hz,
)

"""
Common-cause cases are based on recurring issues documented in:
- Firestone: https://www.firestonecompleteautocare.com/blog/maintenance/why-is-my-car-shaking/
- AA1Car wheel/tire vibration: https://www.aa1car.com/library/wheel_balancing.htm
- AA1Car driveline vibration: https://www.aa1car.com/library/vibrations.htm
- AA1Car brake pulsation/vibration: https://www.aa1car.com/library/brake_pedal_pulsates.htm
"""


SPEED_KMH = 100.0
SPEED_MPS = SPEED_KMH * KMH_TO_MPS


@dataclass(frozen=True, slots=True)
class CauseCase:
    cause: str
    expected_key: str
    peak_hz: float


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
    circumference_m = pi * diameter_m
    wheel_hz_manual = SPEED_MPS / circumference_m
    drive_hz_manual = wheel_hz_manual * settings["final_drive_ratio"]
    engine_hz_manual = drive_hz_manual * settings["current_gear_ratio"]

    assert orders["wheel_hz"] == pytest.approx(wheel_hz_manual, rel=1e-6)
    assert orders["drive_hz"] == pytest.approx(drive_hz_manual, rel=1e-6)
    assert orders["engine_hz"] == pytest.approx(engine_hz_manual, rel=1e-6)

    # Sanity anchors for regression readability at 100 km/h defaults.
    assert orders["wheel_hz"] == pytest.approx(12.55244, rel=1e-4)
    assert orders["drive_hz"] == pytest.approx(38.66153, rel=1e-4)
    assert orders["engine_hz"] == pytest.approx(24.74338, rel=1e-4)


def test_tolerance_window_is_respected_for_order_classification() -> None:
    settings, orders = _default_orders()

    wheel_tol = tolerance_for_order(
        settings["wheel_bandwidth_pct"],
        orders["wheel_hz"],
        orders["wheel_uncertainty_pct"],
        min_abs_band_hz=settings["min_abs_band_hz"],
        max_band_half_width_pct=settings["max_band_half_width_pct"],
    )
    # Inside tolerance should classify as wheel1.
    inside_hz = orders["wheel_hz"] * (1.0 + (0.75 * wheel_tol))
    inside_cls = classify_peak_hz(peak_hz=inside_hz, speed_mps=SPEED_MPS, settings=settings)
    assert inside_cls["key"] == "wheel1"

    # Outside tolerance should not classify as wheel1.
    outside_hz = orders["wheel_hz"] * (1.0 + (1.45 * wheel_tol))
    outside_cls = classify_peak_hz(peak_hz=outside_hz, speed_mps=SPEED_MPS, settings=settings)
    assert outside_cls["key"] != "wheel1"


def _common_cause_cases() -> list[CauseCase]:
    settings, orders = _default_orders()
    return [
        CauseCase("wheel_tire_imbalance", "wheel1", orders["wheel_hz"] * 1.010),
        CauseCase("bent_rim", "wheel1", orders["wheel_hz"] * 0.992),
        CauseCase("tire_flat_spot_or_radial_runout", "wheel1", orders["wheel_hz"] * 1.022),
        CauseCase("brake_rotor_thickness_variation", "wheel1", orders["wheel_hz"] * 0.985),
        CauseCase("tire_non_uniformity_harmonic", "wheel2_eng1", orders["wheel_hz"] * 2.0),
        CauseCase("driveshaft_imbalance", "shaft1", orders["drive_hz"] * 1.014),
        CauseCase("cv_joint_or_u_joint_wear", "shaft1", orders["drive_hz"] * 0.986),
        CauseCase("engine_misfire_or_combustion_roughness", "eng1", orders["engine_hz"]),
        CauseCase("engine_second_order_imbalance", "eng2", (orders["engine_hz"] * 2.0) * 0.988),
        CauseCase("road_or_suspension_input", "road", 7.8),
    ]


@pytest.mark.parametrize("case", _common_cause_cases(), ids=lambda c: c.cause)
def test_common_vibration_causes_classify_as_expected(case: CauseCase) -> None:
    settings = build_diagnostic_settings({})
    cls = classify_peak_hz(
        peak_hz=case.peak_hz,
        speed_mps=SPEED_MPS,
        settings=settings,
    )
    assert cls["key"] == case.expected_key
