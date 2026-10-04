"""Vehicle order frequencies need a moving car, a valid tire and valid ratios."""

from __future__ import annotations

import pytest

from vibesensor.dsp.order_bands import build_diagnostic_settings, vehicle_orders_hz


@pytest.mark.parametrize("speed_mps", [None, 0.0, -1.0])
def test_no_orders_without_forward_speed(speed_mps: float | None) -> None:
    assert vehicle_orders_hz(speed_mps=speed_mps, settings=build_diagnostic_settings({})) is None


@pytest.mark.parametrize(
    "overrides",
    [{"tire_width_mm": 0.0}, {"final_drive_ratio": 0.0}],
    ids=["no-tire", "no-final-drive"],
)
def test_no_orders_without_a_valid_tire_or_final_drive(overrides: dict[str, float]) -> None:
    assert vehicle_orders_hz(speed_mps=25.0, settings=build_diagnostic_settings(overrides)) is None
