"""Stateless rotational-speed payload builders."""

from __future__ import annotations

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.domain.speed_source import SpeedSource
from vibesensor.shared.constants import SECONDS_PER_MINUTE
from vibesensor.shared.order_bands import build_order_bands, vehicle_orders_hz
from vibesensor.shared.types.backend_types import ResolvedSpeedSource
from vibesensor.shared.types.payload_types import (
    RotationalSpeedsPayload,
    RotationalSpeedValuePayload,
)


def rotational_basis_speed_source(
    selected_source: str,
    *,
    gps_enabled: bool,
    fallback_active: bool = False,
    resolution_source: ResolvedSpeedSource | None = None,
) -> str:
    """Determine the basis speed source label for rotational RPM display."""
    return SpeedSource.resolve_basis_label(
        str(selected_source or "gps"),
        gps_enabled=gps_enabled,
        fallback_active=fallback_active,
        resolution_source=resolution_source,
    )


def build_rotational_speeds_payload(
    *,
    basis_speed_source: str,
    speed_mps: float | None,
    analysis_settings: AnalysisSettingsSnapshot,
) -> RotationalSpeedsPayload:
    """Assemble the ``rotational_speeds`` sub-dict for the WS payload."""
    if speed_mps is None or speed_mps <= 0:
        reason: str | None = "speed_unavailable"
        orders_hz = None
    else:
        orders_hz = vehicle_orders_hz(speed_mps=speed_mps, settings=analysis_settings)
        reason = "invalid_vehicle_settings" if orders_hz is None else None

    if reason is not None:
        _component: RotationalSpeedValuePayload = {
            "rpm": None,
            "mode": "calculated",
            "reason": reason,
        }
        return {
            "basis_speed_source": basis_speed_source,
            "wheel": {**_component},
            "driveshaft": {**_component},
            "engine": {**_component},
            "order_bands": None,
        }

    assert orders_hz is not None
    wheel_rpm = float(orders_hz["wheel_hz"]) * SECONDS_PER_MINUTE
    drive_rpm = float(orders_hz["drive_hz"]) * SECONDS_PER_MINUTE
    engine_rpm = float(orders_hz["engine_hz"]) * SECONDS_PER_MINUTE

    return {
        "basis_speed_source": basis_speed_source,
        "wheel": {"rpm": wheel_rpm, "mode": "calculated", "reason": None},
        "driveshaft": {"rpm": drive_rpm, "mode": "calculated", "reason": None},
        "engine": {"rpm": engine_rpm, "mode": "calculated", "reason": None},
        "order_bands": build_order_bands(orders_hz, analysis_settings),
    }
